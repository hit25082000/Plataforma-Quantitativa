use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

/// `CREATE_NO_WINDOW` — subprocessos sem janela de consola (Windows).
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[cfg(target_os = "windows")]
fn command_no_console(cmd: &mut Command) {
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(target_os = "windows"))]
fn command_no_console(_cmd: &mut Command) {}
use tauri::Manager;
use tauri::State;
use tauri::WebviewUrl;
use tauri::webview::WebviewWindowBuilder;

const CONFIG_FILENAME: &str = "config.json";
const CONFIG_BACKUP_FILENAME: &str = "config.json.bak";
const CONFIG_TMP_FILENAME: &str = "config.json.tmp";
const CONFIG_CORRUPT_MSG: &str = "Arquivo de configuração corrompido. Não foi possível ler; alterações não foram salvas.";

/// Health do distributor. Ver docs/PORTS.md
const HEALTH_URL: &str = "http://127.0.0.1:8000/health";
const AGENT007_CHAT_URL: &str = "http://127.0.0.1:8000/api/agent007/chat";

#[derive(Default)]
pub struct ChildProcesses {
    pub engine: Mutex<Option<Child>>,
    pub distributor: Mutex<Option<Child>>,
    pub profit_ocr: Mutex<Option<Child>>,
}

/// Estado persistido de uma janela de widget (posição e tamanho).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WidgetWindowState {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
    #[serde(default)]
    pub visible: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AppConfig {
    pub profit_activation_key: Option<String>,
    pub profit_user: Option<String>,
    pub profit_password: Option<String>,
    /// OpenRouter / Agente 007 — ver distributor/config.py (AGENT007_*).
    #[serde(default)]
    pub agent007_api_key: Option<String>,
    #[serde(default)]
    pub agent007_model: Option<String>,
    #[serde(default)]
    pub agent007_base_url: Option<String>,
    #[serde(default)]
    pub agent007_openrouter_http_referer: Option<String>,
    #[serde(default)]
    pub agent007_openrouter_app_title: Option<String>,
    pub notifications_enabled: Option<bool>,
    pub sounds_enabled: Option<bool>,
    pub volume: Option<u8>,
    pub minimize_to_tray: Option<bool>,
    pub start_with_windows: Option<bool>,
    pub selected_ticker: Option<String>,
    pub selected_exchange: Option<String>,
    #[serde(default)]
    pub widget_windows: Option<HashMap<String, WidgetWindowState>>,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            profit_activation_key: None,
            profit_user: None,
            profit_password: None,
            agent007_api_key: None,
            agent007_model: None,
            agent007_base_url: None,
            agent007_openrouter_http_referer: None,
            agent007_openrouter_app_title: None,
            notifications_enabled: Some(true),
            sounds_enabled: Some(true),
            volume: Some(80),
            minimize_to_tray: Some(true),
            start_with_windows: Some(false),
            selected_ticker: Some("WINFUT".to_string()),
            selected_exchange: Some("BMF".to_string()),
            widget_windows: None,
        }
    }
}

/// IDs de widgets permitidos (alinhado ao frontend).
const VALID_WIDGET_IDS: &[&str] = &[
    "alert-feed",
    "macd",
    "flow-secagem",
    "buy-vs-sell",
    "top-brokers",
    "aggression-chart",
    "ifr-9",
    "ifr-30min",
    "ifr-18",
    "ubs-line",
    "vwap",
];

/// TCP do engine (SWITCH). Ver docs/PORTS.md
const ENGINE_CONTROL_PORT: u16 = 5556;

/// Porta HTTP do OCR. Env `PQ_OCR_PORT` (alinhar Python + frontend). Ver docs/PORTS.md
fn ocr_port() -> u16 {
    std::env::var("PQ_OCR_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(5558)
}

fn ocr_status_url() -> String {
    format!("http://127.0.0.1:{}/status", ocr_port())
}

fn ocr_positions_url() -> String {
    format!("http://127.0.0.1:{}/positions", ocr_port())
}

fn get_resources_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .resource_dir()
        .map_err(|e| format!("{e}"))
}

async fn profit_ocr_http_reachable() -> bool {
    let Ok(client) = reqwest::Client::builder()
        .timeout(Duration::from_millis(400))
        .build()
    else {
        return false;
    };
    client
        .get(ocr_status_url())
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

/// Garante processo Python do OCR (porta 5558) ao abrir o overlay — evita espera longa no retry do WebSocket.
async fn ensure_profit_ocr_running(
    app: tauri::AppHandle,
    processes: State<'_, ChildProcesses>,
) -> Result<(), String> {
    if profit_ocr_http_reachable().await {
        return Ok(());
    }

    let spawn_new = {
        let mut ocr_guard = processes.profit_ocr.lock().map_err(|e| e.to_string())?;
        match ocr_guard.as_mut() {
            Some(child) => match child.try_wait().map_err(|e| e.to_string())? {
                Some(_status) => {
                    *ocr_guard = None;
                    true
                }
                None => false,
            },
            None => true,
        }
    };

    if !spawn_new {
        for _ in 0..50 {
            if profit_ocr_http_reachable().await {
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        return Ok(());
    }

    let resources = get_resources_dir(&app)?;
    let res_sub = resources.join("resources");
    let script = res_sub.join("profit_ocr_service.py");
    if !script.exists() {
        return Ok(());
    }

    let stderr_path = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("{e}"))
        .ok()
        .map(|d| {
            let _ = std::fs::create_dir_all(&d);
            d.join("profit_ocr_stderr.log")
        });

    let open_stderr = |p: &Option<PathBuf>| -> Stdio {
        if let Some(path) = p {
            match std::fs::File::create(path) {
                Ok(f) => Stdio::from(f),
                Err(_) => Stdio::null(),
            }
        } else {
            Stdio::null()
        }
    };

    let script_str = script.to_string_lossy().to_string();
    let ocr_port_env = ocr_port().to_string();
    let stderr_io = open_stderr(&stderr_path);
    let mut py_cmd = Command::new("py");
    py_cmd
        .args(["-3", &script_str])
        .current_dir(&res_sub)
        .env("PQ_OCR_PORT", &ocr_port_env)
        .stdout(Stdio::null())
        .stderr(stderr_io);
    command_no_console(&mut py_cmd);
    let child = match py_cmd.spawn() {
        Ok(c) => c,
        Err(e_py) => {
            let stderr_io2 = open_stderr(&stderr_path);
            let mut alt = Command::new("python");
            alt.arg(&script_str)
                .current_dir(&res_sub)
                .env("PQ_OCR_PORT", &ocr_port_env)
                .stdout(Stdio::null())
                .stderr(stderr_io2);
            command_no_console(&mut alt);
            alt.spawn()
                .map_err(|e_py2| format!("Falha ao iniciar OCR (py: {e_py}, python: {e_py2})"))?
        }
    };

    {
        let mut ocr_guard = processes.profit_ocr.lock().map_err(|e| e.to_string())?;
        *ocr_guard = Some(child);
    }

    for _ in 0..50 {
        if profit_ocr_http_reachable().await {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    Ok(())
}

#[tauri::command]
pub async fn open_profit_overlay(
    app: tauri::AppHandle,
    processes: State<'_, ChildProcesses>,
) -> Result<(), String> {
    ensure_profit_ocr_running(app.clone(), processes).await?;
    if let Some(win) = app.get_webview_window("profit-overlay") {
        win.show().map_err(|e| e.to_string())?;
        win.set_always_on_top(true).map_err(|e| e.to_string())?;
        win.set_ignore_cursor_events(true)
            .map_err(|e| e.to_string())?;
    } else {
        let (screen_w, screen_h) = {
            let monitor = app
                .primary_monitor()
                .map_err(|e| e.to_string())?
                .ok_or("Monitor principal não encontrado")?;
            let size = monitor.size();
            (size.width as f64, size.height as f64)
        };

        let url = if cfg!(debug_assertions) {
            let u = url::Url::parse("http://localhost:5173").map_err(|e| e.to_string())?;
            WebviewUrl::External(u)
        } else {
            WebviewUrl::App(PathBuf::from("index.html"))
        };

        let window = WebviewWindowBuilder::new(&app, "profit-overlay", url)
            .title("Profit Overlay")
            .transparent(true)
            .decorations(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .resizable(false)
            .shadow(false)
            .inner_size(screen_w, screen_h)
            .position(0.0, 0.0)
            .build()
            .map_err(|e| e.to_string())?;

        window
            .set_ignore_cursor_events(true)
            .map_err(|e| e.to_string())?;
    }

    let (screen_w, _screen_h) = {
        let monitor = app
            .primary_monitor()
            .map_err(|e| e.to_string())?
            .ok_or("Monitor principal não encontrado")?;
        let size = monitor.size();
        (size.width as f64, size.height as f64)
    };

    let control_url = if cfg!(debug_assertions) {
        let u = url::Url::parse("http://localhost:5173").map_err(|e| e.to_string())?;
        WebviewUrl::External(u)
    } else {
        WebviewUrl::App(PathBuf::from("index.html"))
    };

    if let Some(ctrl) = app.get_webview_window("profit-overlay-control") {
        ctrl.show().map_err(|e| e.to_string())?;
        ctrl.set_always_on_top(true).map_err(|e| e.to_string())?;
    } else {
        let ctrl_w = 180.0;
        let ctrl_h = 56.0;
        let ctrl_x = (screen_w - ctrl_w - 16.0).max(0.0);
        let ctrl_y = 16.0;
        let _ = WebviewWindowBuilder::new(&app, "profit-overlay-control", control_url)
            .title("Overlay Control")
            .transparent(true)
            .decorations(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .resizable(false)
            .shadow(false)
            .inner_size(ctrl_w, ctrl_h)
            .position(ctrl_x, ctrl_y)
            .build()
            .map_err(|e| e.to_string())?;
    }

    Ok(())
}

#[tauri::command]
pub async fn close_profit_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("profit-overlay") {
        win.hide().map_err(|e| e.to_string())?;
    }
    if let Some(ctrl) = app.get_webview_window("profit-overlay-control") {
        ctrl.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Alvo de linha no overlay (preço + rótulo exibido na janela OCR).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OverlayTargetPayload {
    pub value: f64,
    #[serde(default)]
    pub label: String,
}

#[tauri::command]
pub async fn set_overlay_positions(targets: Vec<OverlayTargetPayload>) -> Result<(), String> {
    let client = reqwest::Client::new();
    let body = serde_json::json!({ "targets": targets });
    client
        .post(ocr_positions_url())
        .json(&body)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub async fn get_resource_path(app: tauri::AppHandle, name: String) -> Result<String, String> {
    let resources = get_resources_dir(&app)?;
    let path = resources.join(&name);
    Ok(path.to_string_lossy().to_string())
}

#[tauri::command]
pub async fn get_config_path(app: tauri::AppHandle) -> Result<String, String> {
    let config_dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("{e}"))?;
    std::fs::create_dir_all(&config_dir).map_err(|e| e.to_string())?;
    Ok(config_dir.join(CONFIG_FILENAME).to_string_lossy().to_string())
}

fn parse_config_contents(contents: &str) -> Result<AppConfig, String> {
    let trimmed = contents
        .strip_prefix('\u{feff}')
        .unwrap_or(contents)
        .trim();
    if trimmed.is_empty() {
        return Ok(AppConfig::default());
    }
    match serde_json::from_str::<AppConfig>(trimmed) {
        Ok(c) => Ok(c),
        Err(e) => {
            let msg = e.to_string();
            // Dois objetos colados, lixo após o `}`, etc. — `from_str` exige EOF; aqui lemos só o 1º valor.
            if msg.contains("trailing characters") {
                let mut de = serde_json::Deserializer::from_str(trimmed);
                AppConfig::deserialize(&mut de).map_err(|e2| {
                    format!("config.json inválido ou corrompido: {e2}")
                })
            } else {
                Err(format!("config.json inválido ou corrompido: {e}"))
            }
        }
    }
}

#[tauri::command]
pub async fn read_config(app: tauri::AppHandle) -> Result<AppConfig, String> {
    let path_str = get_config_path(app).await?;
    let path = PathBuf::from(&path_str);
    if !path.exists() {
        return Ok(AppConfig::default());
    }
    let contents = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    match parse_config_contents(&contents) {
        Ok(config) => Ok(config),
        Err(main_err) => {
            let backup_path = path
                .parent()
                .map(|p| p.join(CONFIG_BACKUP_FILENAME))
                .unwrap_or_else(|| PathBuf::from(CONFIG_BACKUP_FILENAME));
            if backup_path.exists() {
                if let Ok(backup_contents) = std::fs::read_to_string(&backup_path) {
                    match parse_config_contents(&backup_contents) {
                        Ok(config) => return Ok(config),
                        Err(backup_err) => {
                            return Err(format!(
                                "config.json inválido ou corrompido (principal: {main_err}; backup: {backup_err})"
                            ));
                        }
                    }
                }
            }
            Err(format!("config.json inválido ou corrompido: {main_err}"))
        }
    }
}

#[tauri::command]
pub async fn write_config(app: tauri::AppHandle, config: AppConfig) -> Result<(), String> {
    // Importante: este comando é chamado do frontend frequentemente com apenas um "patch"
    // de configurações (campos ausentes/null). Para evitar perda de dados (ex.: credenciais),
    // fazemos merge com o arquivo existente e só sobrescrevemos campos quando vierem como Some(_).
    let path_str = get_config_path(app.clone()).await?;
    let path = PathBuf::from(&path_str);

    let existing = match read_config(app.clone()).await {
        Ok(c) => c,
        Err(_) => {
            if path.exists() {
                return Err(CONFIG_CORRUPT_MSG.to_string());
            }
            AppConfig::default()
        }
    };

    let mut merged = existing;
    // Credenciais: nunca apagar por "None" (campo ausente/null no patch)
    if config.profit_activation_key.is_some() {
        merged.profit_activation_key = config.profit_activation_key;
    }
    if config.profit_user.is_some() {
        merged.profit_user = config.profit_user;
    }
    if config.profit_password.is_some() {
        merged.profit_password = config.profit_password;
    }

    if config.notifications_enabled.is_some() {
        merged.notifications_enabled = config.notifications_enabled;
    }
    if config.sounds_enabled.is_some() {
        merged.sounds_enabled = config.sounds_enabled;
    }
    if config.volume.is_some() {
        merged.volume = config.volume;
    }
    if config.minimize_to_tray.is_some() {
        merged.minimize_to_tray = config.minimize_to_tray;
    }
    if config.start_with_windows.is_some() {
        merged.start_with_windows = config.start_with_windows;
    }
    if config.selected_ticker.is_some() {
        merged.selected_ticker = config.selected_ticker;
    }
    if config.selected_exchange.is_some() {
        merged.selected_exchange = config.selected_exchange;
    }
    if config.widget_windows.is_some() {
        merged.widget_windows = config.widget_windows;
    }

    // Agente 007: campo presente no JSON (Some) atualiza; string vazia limpa. Ausente (None) não altera.
    if let Some(v) = config.agent007_api_key {
        merged.agent007_api_key = if v.trim().is_empty() {
            None
        } else {
            Some(v.trim().to_string())
        };
    }
    if let Some(v) = config.agent007_model {
        merged.agent007_model = if v.trim().is_empty() {
            None
        } else {
            Some(v.trim().to_string())
        };
    }
    if let Some(v) = config.agent007_base_url {
        merged.agent007_base_url = if v.trim().is_empty() {
            None
        } else {
            Some(v.trim().to_string())
        };
    }
    if let Some(v) = config.agent007_openrouter_http_referer {
        merged.agent007_openrouter_http_referer = if v.trim().is_empty() {
            None
        } else {
            Some(v.trim().to_string())
        };
    }
    if let Some(v) = config.agent007_openrouter_app_title {
        merged.agent007_openrouter_app_title = if v.trim().is_empty() {
            None
        } else {
            Some(v.trim().to_string())
        };
    }

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let contents = serde_json::to_string_pretty(&merged).map_err(|e| e.to_string())?;

    let tmp_path = path.parent().map(|p| p.join(CONFIG_TMP_FILENAME)).unwrap_or_else(|| PathBuf::from(CONFIG_TMP_FILENAME));
    std::fs::write(&tmp_path, &contents).map_err(|e| e.to_string())?;
    if let Ok(f) = std::fs::File::open(&tmp_path) {
        let _ = f.sync_all();
    }
    std::fs::rename(&tmp_path, &path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp_path);
        e.to_string()
    })?;
    if let Some(parent) = path.parent() {
        let backup_path = parent.join(CONFIG_BACKUP_FILENAME);
        let _ = std::fs::copy(&path, &backup_path);
    }
    Ok(())
}

#[tauri::command]
pub async fn check_health() -> Result<bool, String> {
    let client = reqwest::Client::new();
    let res = client
        .get(HEALTH_URL)
        .timeout(std::time::Duration::from_secs(2))
        .send()
        .await
        .map_err(|e| e.to_string());
    match res {
        Ok(r) => Ok(r.status().is_success()),
        Err(_) => Ok(false),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Agent007ChatMsg {
    pub role: String,
    pub content: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Agent007ChatApiResult {
    #[serde(default)]
    pub ok: bool,
    pub reply: Option<String>,
    pub error: Option<String>,
}

/// Proxy do chat Agente 007 → distributor (reqwest nativo; o `fetch` do WebView falha com CSP em devUrl).
#[tauri::command]
pub async fn agent007_chat_invoke(
    messages: Vec<Agent007ChatMsg>,
) -> Result<Agent007ChatApiResult, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(90))
        .build()
        .map_err(|e| e.to_string())?;
    let res = client
        .post(AGENT007_CHAT_URL)
        .json(&serde_json::json!({ "messages": messages }))
        .send()
        .await
        .map_err(|e| format!("Falha de rede ao distributor (127.0.0.1:8000): {e}"))?;
    let status = res.status();
    let text = res.text().await.map_err(|e| e.to_string())?;
    let mut val: Agent007ChatApiResult =
        serde_json::from_str(&text).map_err(|e| format!("Resposta inválida do distributor: {e}"))?;
    if !status.is_success() && val.error.is_none() {
        val.ok = false;
        val.error = Some(format!("HTTP {status}"));
    }
    Ok(val)
}

#[cfg(target_os = "windows")]
fn kill_stale_processes() {
    let mut c = Command::new("taskkill");
    c.args(["/F", "/IM", "engine.exe"])
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command_no_console(&mut c);
    let _ = c.status();
}

#[cfg(not(target_os = "windows"))]
fn kill_stale_processes() {}

#[tauri::command]
pub async fn spawn_engine(
    app: tauri::AppHandle,
    processes: State<'_, ChildProcesses>,
) -> Result<(), String> {
    kill_stale_processes();
    std::thread::sleep(Duration::from_millis(300));

    let resources = get_resources_dir(&app)?;
    let engine_dir = resources.join("resources");
    let engine_exe = engine_dir.join("engine.exe");

    if !engine_exe.exists() {
        return Err(format!(
            "engine.exe não encontrado em {}",
            engine_exe.display()
        ));
    }

    let config = read_config(app.clone()).await?;

    let key_ok = config
        .profit_activation_key
        .as_ref()
        .map(|s| !s.trim().is_empty())
        .unwrap_or(false);
    let user_ok = config
        .profit_user
        .as_ref()
        .map(|s| !s.trim().is_empty())
        .unwrap_or(false);
    let pass_ok = config
        .profit_password
        .as_ref()
        .map(|s| !s.is_empty())
        .unwrap_or(false);
    if !key_ok || !user_ok || !pass_ok {
        return Err(
            "Preencha as credenciais Profit em Configurações antes de iniciar o engine.".to_string(),
        );
    }

    let mut engine_guard = processes.engine.lock().map_err(|e| e.to_string())?;
    if let Some(ref mut child) = *engine_guard {
        if child.try_wait().ok().flatten().is_some() {
            *engine_guard = None;
        } else {
            return Err("Engine já está em execução".to_string());
        }
    }
    let engine_log_path = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("{e}"))
        .and_then(|dir| {
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
            Ok(dir.join("profit_engine.log").to_string_lossy().to_string())
        })
        .unwrap_or_else(|_| "profit_engine.log".to_string());

    let engine_stderr_path = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("{e}"))
        .and_then(|dir| {
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
            Ok(dir.join("engine_stderr.log"))
        })
        .ok();

    let stderr_cfg = if let Some(ref p) = engine_stderr_path {
        let f = std::fs::File::create(p).map_err(|e| e.to_string())?;
        Stdio::from(f)
    } else {
        Stdio::null()
    };

    // Debug session log in workspace root for agent instrumentation
    let debug_session_log = std::fs::canonicalize(&engine_dir).ok().and_then(|mut p| {
        for _ in 0..6 {
            p = p.parent()?.to_path_buf();
        }
        Some(p.join("debug-d74a7b.log"))
    });

    let mut cmd = Command::new(&engine_exe);
    cmd.current_dir(&engine_dir)
        .stdout(Stdio::null())
        .stderr(stderr_cfg)
        .env("DEBUG_LOG_PATH", &engine_log_path);

    if let Some(ref path) = debug_session_log {
        cmd.env("DEBUG_SESSION_LOG", path);
    }
    if let Some(key) = &config.profit_activation_key {
        cmd.env("PROFIT_ACTIVATION_KEY", key);
    }
    if let Some(user) = &config.profit_user {
        cmd.env("PROFIT_USER", user);
    }
    if let Some(pass) = &config.profit_password {
        cmd.env("PROFIT_PASSWORD", pass);
    }
    let raw_ticker = config.selected_ticker.as_deref().unwrap_or("WINFUT").trim().to_uppercase();
    let raw_exchange = config.selected_exchange.as_deref().unwrap_or("BMF").trim().to_uppercase();

    // "TESTE"/"SIM" is the mock feed; the DLL needs a real ticker/exchange
    let (ticker_env, exchange_env) = if raw_exchange == "SIM" || raw_ticker == "TESTE" {
        ("WINFUT".to_string(), "BMF".to_string())
    } else {
        (raw_ticker, raw_exchange)
    };

    cmd.env("PROFIT_TICKER", &ticker_env);
    let bolsa_dll = exchange_to_bolsa_dll(&exchange_env);
    cmd.env("PROFIT_BOLSA", bolsa_dll);

    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&engine_log_path)
    {
        let _ = writeln!(
            f,
            "{{\"message\":\"spawn_env\",\"data\":{{\"PROFIT_TICKER\":\"{}\",\"PROFIT_BOLSA\":\"{}\"}}}}",
            ticker_env, bolsa_dll
        );
    }

    command_no_console(&mut cmd);
    let child = cmd.spawn().map_err(|e| e.to_string())?;
    *engine_guard = Some(child);
    Ok(())
}

/// Env do processo Tauri tem prioridade sobre `config.json` (útil em dev/CI).
fn env_nonempty(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

fn apply_agent007_env(cmd: &mut Command, config: &AppConfig) {
    let api = env_nonempty("AGENT007_API_KEY")
        .or_else(|| env_nonempty("OPENROUTER_API_KEY"))
        .or_else(|| {
            config
                .agent007_api_key
                .as_ref()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        });
    if let Some(v) = api {
        cmd.env("AGENT007_API_KEY", v);
    }

    let model = env_nonempty("AGENT007_MODEL").or_else(|| {
        config
            .agent007_model
            .as_ref()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
    });
    if let Some(v) = model {
        cmd.env("AGENT007_MODEL", v);
    }

    let base = env_nonempty("AGENT007_BASE_URL").or_else(|| {
        config
            .agent007_base_url
            .as_ref()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
    });
    if let Some(v) = base {
        cmd.env("AGENT007_BASE_URL", v);
    }

    let referer = env_nonempty("AGENT007_OPENROUTER_HTTP_REFERER")
        .or_else(|| env_nonempty("OPENROUTER_HTTP_REFERER"))
        .or_else(|| {
            config
                .agent007_openrouter_http_referer
                .as_ref()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        });
    if let Some(v) = referer {
        cmd.env("AGENT007_OPENROUTER_HTTP_REFERER", v);
    }

    let title = env_nonempty("AGENT007_OPENROUTER_APP_TITLE").or_else(|| {
        config
            .agent007_openrouter_app_title
            .as_ref()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
    });
    if let Some(v) = title {
        cmd.env("AGENT007_OPENROUTER_APP_TITLE", v);
    }
}

#[tauri::command]
pub async fn spawn_distributor(
    app: tauri::AppHandle,
    processes: State<'_, ChildProcesses>,
) -> Result<(), String> {
    // Se já há processo na porta 8000 (ex.: iniciado pelo script run-dev), não spawnar de novo
    if check_health().await.unwrap_or(false) {
        return Ok(());
    }

    let config = read_config(app.clone()).await?;

    let resources = get_resources_dir(&app)?;
    let dist_dir = resources.join("resources");
    let dist_exe = dist_dir.join("distributor.exe");

    if !dist_exe.exists() {
        return Err(format!(
            "distributor.exe não encontrado em {}",
            dist_exe.display()
        ));
    }

    let dist_stderr_path = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("{e}"))
        .and_then(|dir| {
            std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
            Ok(dir.join("distributor_stderr.log"))
        })
        .ok();

    let dist_stderr = if let Some(ref p) = dist_stderr_path {
        match std::fs::File::create(p) {
            Ok(f) => Stdio::from(f),
            Err(_) => Stdio::null(),
        }
    } else {
        Stdio::null()
    };

    let mut dist_guard = processes.distributor.lock().map_err(|e| e.to_string())?;
    if dist_guard.is_some() {
        return Err("Distributor já está em execução".to_string());
    }

    let mut cmd = Command::new(&dist_exe);
    cmd.current_dir(&dist_dir)
        .stdout(Stdio::null())
        .stderr(dist_stderr);
    apply_agent007_env(&mut cmd, &config);

    command_no_console(&mut cmd);
    let child = cmd.spawn().map_err(|e| e.to_string())?;

    *dist_guard = Some(child);
    Ok(())
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ProfitDiagnostic {
    pub credentials_configured: bool,
    pub engine_log_path: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub engine_stderr_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub app_data_dir: Option<String>,
    pub offer_book_count: u32,
    pub trade_count: u32,
    pub daily_count: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subscribe_ticker_ret: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subscribe_offer_book_ret: Option<i32>,
    pub message: String,
}

#[tauri::command]
pub async fn get_profit_diagnostic(app: tauri::AppHandle) -> Result<ProfitDiagnostic, String> {
    let config = read_config(app.clone()).await?;
    let credentials_configured = config.profit_activation_key.as_ref().map(|s| !s.trim().is_empty()).unwrap_or(false)
        && config.profit_user.as_ref().map(|s| !s.trim().is_empty()).unwrap_or(false)
        && config.profit_password.as_ref().map(|s| !s.is_empty()).unwrap_or(false);

    let (engine_log_path, engine_stderr_path, app_data_dir) = match app.path().app_data_dir() {
        Ok(dir) => {
            let _ = std::fs::create_dir_all(&dir);
            let log_path = dir.join("profit_engine.log").to_string_lossy().to_string();
            let stderr_path = dir.join("engine_stderr.log").to_string_lossy().to_string();
            let dir_path = dir.to_string_lossy().to_string();
            (log_path, Some(stderr_path), Some(dir_path))
        }
        Err(_) => ("profit_engine.log".to_string(), None, None),
    };

    let mut offer_book_count = 0u32;
    let mut trade_count = 0u32;
    let mut daily_count = 0u32;
    let mut subscribe_ticker_ret: Option<i32> = None;
    let mut subscribe_offer_book_ret: Option<i32> = None;

    if let Ok(contents) = std::fs::read_to_string(&engine_log_path) {
        for line in contents.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(line) {
                if let Some(msg) = v.get("message").and_then(|m| m.as_str()) {
                    if msg == "engine_started" {
                        if let Some(data) = v.get("data") {
                            subscribe_ticker_ret = data.get("subscribe_ticker_ret").and_then(|n| n.as_i64()).map(|n| n as i32);
                            subscribe_offer_book_ret = data.get("subscribe_offer_book_ret").and_then(|n| n.as_i64()).map(|n| n as i32);
                        }
                    }
                }
                if let Some(data) = v.get("data") {
                    let n = data.get("n").and_then(|n| n.as_u64()).unwrap_or(0) as u32;
                    if let Some(cb) = data.get("callback").and_then(|c| c.as_str()) {
                        match cb {
                            "offer_book" => offer_book_count = offer_book_count.max(n),
                            "trade" => trade_count = trade_count.max(n),
                            "daily" => daily_count = daily_count.max(n),
                            _ => {}
                        }
                    }
                }
            }
        }
    }

    let message = if !credentials_configured {
        "Configure usuário, senha e chave de ativação em Configurações.".to_string()
    } else if subscribe_ticker_ret.is_none() && subscribe_offer_book_ret.is_none() {
        "Engine ainda não escreveu no log (reinicie os serviços e aguarde). Se o engine não estiver na pasta do app, copie o engine.exe novo para a pasta resources.".to_string()
    } else if let (Some(st), Some(sb)) = (subscribe_ticker_ret, subscribe_offer_book_ret) {
        if st != 0 || sb != 0 {
            format!(
                "Subscribe retornou códigos de erro: Ticker={}, OfferBook={}. 0=OK; -2147483647=NL_INTERNAL_ERROR; -2147483646=NL_NOT_INITIALIZED (Market não pronto).",
                st, sb
            )
        } else if offer_book_count == 0 && trade_count == 0 && daily_count == 0 {
            "Subscribe OK (0). Nenhum callback da DLL ainda (livro/trades). Pregão aberto? Ativo WINJ25 com liquidez?".to_string()
        } else {
            format!(
                "DLL retornando dados: {} livro, {} trades, {} daily.",
                offer_book_count, trade_count, daily_count
            )
        }
    } else if offer_book_count == 0 && trade_count == 0 && daily_count == 0 {
        "Credenciais OK. Nenhum dado da DLL ainda. Verifique: 1) Pregão aberto? 2) WINJ25 com liquidez? 3) Terminal do engine mostra [Profit] Market: 4?".to_string()
    } else {
        format!(
            "DLL retornando dados: {} eventos livro, {} trades, {} daily.",
            offer_book_count, trade_count, daily_count
        )
    };

    Ok(ProfitDiagnostic {
        credentials_configured,
        engine_log_path: engine_log_path.clone(),
        engine_stderr_path,
        app_data_dir,
        offer_book_count,
        trade_count,
        daily_count,
        subscribe_ticker_ret,
        subscribe_offer_book_ret,
        message,
    })
}

/// Bolsa enviada ao engine/DLL.
fn exchange_to_bolsa_dll(exchange: &str) -> &str {
    match exchange.to_uppercase().as_str() {
        "BMF" => "F",
        "BOVESPA" => "B",
        "SIM" => "SIM",
        _ => "F",
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SetActiveAssetResult {
    pub success: bool,
    pub message: String,
}

#[tauri::command]
pub async fn set_active_asset(
    app: tauri::AppHandle,
    ticker: String,
    exchange: String,
) -> Result<SetActiveAssetResult, String> {
    let ticker = ticker.trim().to_uppercase();
    let bolsa_dll = exchange_to_bolsa_dll(&exchange).to_string();

    let mut config = read_config(app.clone()).await?;
    config.selected_ticker = Some(ticker.clone());
    config.selected_exchange = Some(exchange.trim().to_uppercase());
    write_config(app.clone(), config).await?;

    let cmd = format!("SWITCH\t{}\t{}\n", ticker, bolsa_dll);
    let addr = format!("127.0.0.1:{}", ENGINE_CONTROL_PORT)
        .parse()
        .map_err(|e: std::net::AddrParseError| e.to_string())?;
    match TcpStream::connect_timeout(&addr, Duration::from_secs(2)) {
        Ok(mut stream) => {
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .map_err(|e| e.to_string())?;
            stream
                .set_write_timeout(Some(Duration::from_secs(2)))
                .map_err(|e| e.to_string())?;
            stream.write_all(cmd.as_bytes()).map_err(|e| e.to_string())?;
            stream.flush().map_err(|e| e.to_string())?;

            let mut buf = [0u8; 256];
            let n = stream.read(&mut buf).unwrap_or(0);
            let response = String::from_utf8_lossy(&buf[..n]).trim().to_string();

            let success = response.starts_with("OK");
            Ok(SetActiveAssetResult {
                success,
                message: if success {
                    format!("Ativo alterado para {} {}", ticker, bolsa_dll)
                } else {
                    response
                },
            })
        }
        Err(e) => Ok(SetActiveAssetResult {
            success: false,
            message: format!(
                "Engine não está escutando na porta {}. Reinicie o engine para habilitar troca de ativo. ({})",
                ENGINE_CONTROL_PORT, e
            ),
        }),
    }
}

#[tauri::command]
pub async fn create_widget_window(app: tauri::AppHandle, widget_id: String) -> Result<(), String> {
    if !VALID_WIDGET_IDS.contains(&widget_id.as_str()) {
        return Err(format!(
            "Widget id inválido: '{}'. Válidos: {}",
            widget_id,
            VALID_WIDGET_IDS.join(", ")
        ));
    }
    let label = format!("widget-{}", widget_id);
    if let Some(win) = app.get_webview_window(&label) {
        let _ = win.set_focus();
        return Ok(());
    }

    let url = if cfg!(debug_assertions) {
        let u = url::Url::parse("http://localhost:5173").map_err(|e| e.to_string())?;
        WebviewUrl::External(u)
    } else {
        WebviewUrl::App(PathBuf::from("index.html"))
    };

    let title = widget_title(&widget_id);
    let mut config = read_config(app.clone()).await?;
    let state = config
        .widget_windows
        .get_or_insert_with(HashMap::new)
        .get(&widget_id)
        .cloned();

    let default_width = 400.0;
    let default_height = 300.0;
    let (x, y, width, height) = state
        .map(|s| (s.x, s.y, s.width, s.height))
        .unwrap_or((100.0, 100.0, default_width, default_height));

    let builder = WebviewWindowBuilder::new(&app, &label, url)
        .title(&title)
        .always_on_top(true)
        .decorations(false)
        .inner_size(width, height)
        .position(x, y)
        .visible(true);

    let window = builder.build().map_err(|e| e.to_string())?;

    let app_handle = app.clone();
    let widget_id_clone = widget_id.clone();
    let save_widget_state = move |app: &tauri::AppHandle, id: &str| {
        let label = format!("widget-{}", id);
        if let Some(w) = app.get_webview_window(&label) {
            let pos = w.inner_position().ok();
            let size = w.inner_size().ok();
            if let (Some(pos), Some(size)) = (pos, size) {
                let app = app.clone();
                let id = id.to_string();
                tauri::async_runtime::block_on(async move {
                    if let Ok(mut cfg) = read_config(app.clone()).await {
                        let map = cfg.widget_windows.get_or_insert_with(HashMap::new);
                        map.insert(
                            id,
                            WidgetWindowState {
                                x: pos.x as f64,
                                y: pos.y as f64,
                                width: size.width as f64,
                                height: size.height as f64,
                                visible: true,
                            },
                        );
                        let _ = write_config(app, cfg).await;
                    }
                });
            }
        }
    };

    window.on_window_event(move |event| {
        match event {
            tauri::WindowEvent::Moved(_) | tauri::WindowEvent::Resized(_) => {
                let app = app_handle.clone();
                let id = widget_id_clone.clone();
                let label = format!("widget-{}", id);
                if let Some(w) = app.get_webview_window(&label) {
                    let pos = w.inner_position().ok();
                    let size = w.inner_size().ok();
                    if let (Some(pos), Some(size)) = (pos, size) {
                        tauri::async_runtime::spawn(async move {
                            tokio::time::sleep(Duration::from_millis(250)).await;
                            if let Ok(mut cfg) = read_config(app.clone()).await {
                                let map = cfg.widget_windows.get_or_insert_with(HashMap::new);
                                map.insert(
                                    id,
                                    WidgetWindowState {
                                        x: pos.x as f64,
                                        y: pos.y as f64,
                                        width: size.width as f64,
                                        height: size.height as f64,
                                        visible: true,
                                    },
                                );
                                let _ = write_config(app, cfg).await;
                            }
                        });
                    }
                }
            }
            tauri::WindowEvent::CloseRequested { .. } => {
                save_widget_state(&app_handle, &widget_id_clone);
            }
            _ => {}
        }
    });

    Ok(())
}

/// Persiste posição e tamanho de todas as janelas de widget abertas (ex.: ao fechar o app).
pub async fn persist_widget_windows(app: tauri::AppHandle) -> Result<(), String> {
    let mut cfg = read_config(app.clone()).await?;
    let map = cfg.widget_windows.get_or_insert_with(HashMap::new);
    let mut changed = false;
    for id in VALID_WIDGET_IDS {
        let label = format!("widget-{}", id);
        if let Some(w) = app.get_webview_window(&label) {
            if let (Ok(pos), Ok(size)) = (w.inner_position(), w.inner_size()) {
                map.insert(
                    (*id).to_string(),
                    WidgetWindowState {
                        x: pos.x as f64,
                        y: pos.y as f64,
                        width: size.width as f64,
                        height: size.height as f64,
                        visible: true,
                    },
                );
                changed = true;
            }
        }
    }
    if changed {
        write_config(app, cfg).await?;
    }
    Ok(())
}

fn widget_title(widget_id: &str) -> String {
    match widget_id {
        "alert-feed" => "Alert Feed",
        "macd" => "MACD 30min",
        "flow-secagem" => "Flow & Secagem",
        "buy-vs-sell" => "Buy vs Sell",
        "top-brokers" => "Top Brokers",
        "aggression-chart" => "Aggression Chart",
        "ifr-9" => "IFR 9",
        "ifr-30min" => "IFR 30min",
        "ifr-18" => "IFR 18",
        "ubs-line" => "UBS Line",
        "vwap" => "VWAP",
        _ => widget_id,
    }
    .to_string()
}

#[tauri::command]
pub async fn open_log_folder(app: tauri::AppHandle) -> Result<(), String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("{e}"))?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("explorer")
            .arg(dir.as_os_str())
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = dir;
        return Err("Abrir pasta de logs só é suportado no Windows.".to_string());
    }
    Ok(())
}

#[tauri::command]
pub async fn kill_services(processes: State<'_, ChildProcesses>) -> Result<(), String> {
    {
        let mut engine_guard = processes.engine.lock().map_err(|e| e.to_string())?;
        if let Some(mut child) = engine_guard.take() {
            let _ = child.kill();
        }
    }
    {
        let mut dist_guard = processes.distributor.lock().map_err(|e| e.to_string())?;
        if let Some(mut child) = dist_guard.take() {
            let _ = child.kill();
        }
    }
    {
        let mut ocr_guard = processes.profit_ocr.lock().map_err(|e| e.to_string())?;
        if let Some(mut child) = ocr_guard.take() {
            let _ = child.kill();
        }
    }
    Ok(())
}
