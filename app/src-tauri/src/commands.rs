use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU16, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

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
const DISTRIBUTOR_API_BASE: &str = "http://127.0.0.1:8000";
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

/// Região OCR de análise (pixels físicos de ecrã); persistida em config.json.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrAnalysisRoiConfig {
    pub left: i32,
    pub top: i32,
    pub width: i32,
    pub height: i32,
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
    /// Tijolo Renko em pontos para IFR (16 ou 42), alinhado ao Profit.
    #[serde(default)]
    pub renko_brick_points: Option<u32>,
    /// Série do IFR: "42r" | "16r" | "30m" (tem prioridade sobre renko_brick_points ao ler no frontend).
    #[serde(default)]
    pub ifr_series: Option<String>,
    #[serde(default)]
    pub widget_windows: Option<HashMap<String, WidgetWindowState>>,
    #[serde(default)]
    pub overlay_right_margin_px: Option<u32>,
    #[serde(default)]
    pub overlay_toolbar_h_px: Option<u32>,
    #[serde(default)]
    pub overlay_axis_bottom_crop_px: Option<u32>,
    /// ROI opcional para OCR de análise (não afeta linhas do overlay).
    #[serde(default)]
    pub ocr_analysis_roi: Option<OcrAnalysisRoiConfig>,
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
            renko_brick_points: None,
            ifr_series: None,
            widget_windows: None,
            overlay_right_margin_px: None,
            overlay_toolbar_h_px: None,
            overlay_axis_bottom_crop_px: None,
            ocr_analysis_roi: None,
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
    static OCR_RUNTIME_PORT: OnceLock<AtomicU16> = OnceLock::new();
    OCR_RUNTIME_PORT
        .get_or_init(|| AtomicU16::new(configured_ocr_port()))
        .load(Ordering::Relaxed)
}

fn configured_ocr_port() -> u16 {
    std::env::var("PQ_OCR_PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(5558)
}

fn set_runtime_ocr_port(port: u16) {
    static OCR_RUNTIME_PORT: OnceLock<AtomicU16> = OnceLock::new();
    OCR_RUNTIME_PORT
        .get_or_init(|| AtomicU16::new(configured_ocr_port()))
        .store(port, Ordering::Relaxed);
}

const OCR_FALLBACK_PORT_STEPS: u16 = 12;

fn ocr_status_url() -> String {
    format!("http://127.0.0.1:{}/status", ocr_port())
}

fn ocr_positions_url() -> String {
    format!("http://127.0.0.1:{}/positions", ocr_port())
}

fn ocr_analysis_roi_url() -> String {
    format!("http://127.0.0.1:{}/analysis_roi", ocr_port())
}

fn ocr_incompatible_analysis_roi_message() -> String {
    format!(
        "OCR em 127.0.0.1:{} está em versão antiga (sem endpoint /analysis_roi). Feche processos antigos de OCR e reinicie o Overlay para subir a versão nova.",
        ocr_port()
    )
}

fn write_config_to_disk(path: &Path, merged: &AppConfig) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let contents = serde_json::to_string_pretty(merged).map_err(|e| e.to_string())?;
    let tmp_path = path
        .parent()
        .map(|p| p.join(CONFIG_TMP_FILENAME))
        .unwrap_or_else(|| PathBuf::from(CONFIG_TMP_FILENAME));
    std::fs::write(&tmp_path, &contents).map_err(|e| e.to_string())?;
    if let Ok(f) = std::fs::File::open(&tmp_path) {
        let _ = f.sync_all();
    }
    std::fs::rename(&tmp_path, path).map_err(|e| {
        let _ = std::fs::remove_file(&tmp_path);
        e.to_string()
    })?;
    if let Some(parent) = path.parent() {
        let backup_path = parent.join(CONFIG_BACKUP_FILENAME);
        let _ = std::fs::copy(path, &backup_path);
    }
    Ok(())
}

/// Reaplica ROI de análise guardada no config após o serviço OCR estar acessível.
async fn push_saved_ocr_analysis_roi_to_http(app: &tauri::AppHandle) {
    let cfg = match read_config(app.clone()).await {
        Ok(c) => c,
        Err(_) => return,
    };
    let roi = match &cfg.ocr_analysis_roi {
        Some(r) if r.width >= 4 && r.height >= 4 => r,
        _ => return,
    };
    let Ok(client) = reqwest::Client::builder()
        .timeout(Duration::from_secs(4))
        .build()
    else {
        return;
    };
    let _ = client
        .post(ocr_analysis_roi_url())
        .json(&json!({
            "rect": {
                "left": roi.left,
                "top": roi.top,
                "width": roi.width,
                "height": roi.height,
            }
        }))
        .send()
        .await;
}

/// Primeira execução do `profit_ocr_service.exe` (PyInstaller) pode demorar ao extrair; antivírus também atrasa o bind.
/// PCs lentos: definir `PQ_OCR_STARTUP_TIMEOUT_MS` (ex.: 180000).
fn ocr_startup_timeout_ms() -> u64 {
    std::env::var("PQ_OCR_STARTUP_TIMEOUT_MS")
        .ok()
        .and_then(|s| s.parse().ok())
        .filter(|&ms| ms >= 15_000 && ms <= 600_000)
        .unwrap_or(120_000)
}

const OCR_POLL_INTERVAL_MS: u64 = 100;
/// Healthcheck local: 400ms falhava em máquinas lentas ou sob carga no primeiro request.
const OCR_HTTP_HEALTH_TIMEOUT_MS: u64 = 5000;
/// Tentativas quando TCP na porta OCR aceita ligação mas HTTP ainda não responde (arranque lento).
const OCR_PORT_BUSY_RETRY_ATTEMPTS: u32 = 10;
const OCR_PORT_BUSY_RETRY_SLEEP_MS: u64 = 400;

fn ocr_startup_attempts() -> u64 {
    (ocr_startup_timeout_ms() / OCR_POLL_INTERVAL_MS).max(1)
}

fn ocr_startup_timeout_secs() -> u64 {
    ocr_startup_timeout_ms() / 1000
}

fn ocr_port_in_use_message() -> String {
    format!(
        "A porta do OCR ({}) já está em uso por outro processo. Feche o processo que ocupa a porta ou altere PQ_OCR_PORT/VITE_PQ_OCR_PORT.",
        ocr_port()
    )
}

fn tesseract_missing_message() -> String {
    "Tesseract OCR não encontrado. Instale em https://github.com/UB-Mannheim/tesseract/wiki e confirme o executável em C:\\Program Files\\Tesseract-OCR\\tesseract.exe.".to_string()
}

fn has_tesseract_on_system() -> bool {
    let env_cmd = std::env::var("TESSERACT_CMD").ok();
    if let Some(cmd) = env_cmd.as_deref() {
        let p = Path::new(cmd.trim());
        if p.is_file() {
            return true;
        }
    }

    let default_candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ];
    if default_candidates.iter().any(|p| Path::new(p).is_file()) {
        return true;
    }

    let mut cmd = Command::new("tesseract");
    cmd.arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command_no_console(&mut cmd);
    cmd.status().map(|s| s.success()).unwrap_or(false)
}

fn maybe_map_ocr_stderr(stderr_path: &Option<PathBuf>) -> Option<String> {
    let path = stderr_path.as_ref()?;
    let contents = std::fs::read_to_string(path).ok()?;
    let lower = contents.to_lowercase();
    if lower.contains("tesseractnotfounderror")
        || lower.contains("tesseract is not installed")
        || lower.contains("no such file or directory: 'tesseract'")
    {
        return Some(tesseract_missing_message());
    }
    if lower.contains("address already in use") || lower.contains("only one usage of each socket address") {
        return Some(ocr_port_in_use_message());
    }
    if lower.contains("modulenotfounderror")
        || lower.contains("importerror")
        || lower.contains("no module named")
        || lower.contains("dependência ausente")
        || lower.contains("dependencia ausente")
    {
        return Some(
            "OCR falhou por dependências Python ausentes/corrompidas no pacote. Reinstale a aplicação (instalador mais recente)."
                .to_string(),
        );
    }
    if lower.contains("winerror 193") || lower.contains("%1 is not a valid win32 application") {
        return Some(
            "OCR incompatível com a arquitetura do Windows (32/64 bits). Reinstale a versão correta da aplicação."
                .to_string(),
        );
    }
    if lower.contains("permission denied") || lower.contains("acesso negado") {
        return Some(
            "OCR sem permissão para iniciar ou escrever logs. Tente executar a aplicação com permissões elevadas e verifique antivírus/controle de pasta."
                .to_string(),
        );
    }
    None
}

fn ocr_startup_failure_message(stderr_path: &Option<PathBuf>, base: &str) -> String {
    if let Some(mapped) = maybe_map_ocr_stderr(stderr_path) {
        return mapped;
    }
    if let Some(path) = stderr_path {
        if let Ok(contents) = std::fs::read_to_string(path) {
            let trimmed = contents.trim();
            if !trimmed.is_empty() {
                let tail = if trimmed.len() > 900 {
                    &trimmed[trimmed.len() - 900..]
                } else {
                    trimmed
                };
                return format!("{base}\nDetalhe OCR: {tail}");
            }
        }
    }
    base.to_string()
}

fn overlay_env_u32(v: Option<u32>) -> Option<String> {
    v.filter(|x| *x > 0).map(|x| x.to_string())
}

fn get_resources_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .resource_dir()
        .map_err(|e| format!("{e}"))
}

fn unix_ts_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

fn diagnostics_session_id() -> &'static str {
    static SID: OnceLock<String> = OnceLock::new();
    SID.get_or_init(|| {
        format!(
            "pq-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|d| d.as_secs())
                .unwrap_or(0)
        )
    })
}

fn overlay_open_lock() -> &'static tokio::sync::Mutex<()> {
    static LOCK: OnceLock<tokio::sync::Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| tokio::sync::Mutex::new(()))
}

#[tauri::command]
pub async fn get_ocr_runtime_port() -> Result<u16, String> {
    Ok(ocr_port())
}

fn app_logs_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dirs = all_logs_dirs(app)?;
    dirs.into_iter()
        .next()
        .ok_or_else(|| "Não foi possível resolver pasta de logs".to_string())
}

fn all_logs_dirs(app: &tauri::AppHandle) -> Result<Vec<PathBuf>, String> {
    let mut out = Vec::new();
    #[cfg(target_os = "windows")]
    {
        if let Ok(local) = std::env::var("LOCALAPPDATA") {
            let p = PathBuf::from(local)
                .join("Plataforma Quantitativa")
                .join("logs");
            std::fs::create_dir_all(&p).map_err(|e| e.to_string())?;
            out.push(p);
        }
    }
    let app_data = app.path().app_data_dir().map_err(|e| format!("{e}"))?;
    let app_logs = app_data.join("logs");
    std::fs::create_dir_all(&app_logs).map_err(|e| e.to_string())?;
    if !out.iter().any(|p| p == &app_logs) {
        out.push(app_logs);
    }
    Ok(out)
}

fn append_runtime_bootstrap_log(
    app: &tauri::AppHandle,
    component: &str,
    event: &str,
    status: &str,
    details: serde_json::Value,
) {
    let Ok(log_dirs) = all_logs_dirs(app) else {
        return;
    };
    let payload = json!({
        "ts_ms": unix_ts_ms(),
        "session_id": diagnostics_session_id(),
        "component": component,
        "event": event,
        "status": status,
        "details": details
    });
    for logs in log_dirs {
        let path = logs.join("runtime-bootstrap.log");
        if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(f, "{}", payload);
        }
    }
}

pub fn log_runtime_event(
    app: &tauri::AppHandle,
    component: &str,
    event: &str,
    status: &str,
    details: serde_json::Value,
) {
    append_runtime_bootstrap_log(app, component, event, status, details);
}

async fn profit_ocr_http_reachable() -> bool {
    let Ok(client) = reqwest::Client::builder()
        .timeout(Duration::from_millis(OCR_HTTP_HEALTH_TIMEOUT_MS))
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

/// Igual a `profit_ocr_http_reachable` no tempo de espera — evita falso “porta ocupada” em OCR a aquecer.
async fn profit_ocr_http_compatible_long() -> bool {
    profit_ocr_http_compatible_timeout_ms(OCR_HTTP_HEALTH_TIMEOUT_MS).await
}

async fn profit_ocr_http_compatible_timeout_ms(timeout_ms: u64) -> bool {
    let Ok(client) = reqwest::Client::builder()
        .timeout(Duration::from_millis(timeout_ms))
        .build()
    else {
        return false;
    };

    let status_ok = client
        .get(ocr_status_url())
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false);
    if status_ok {
        return true;
    }

    client
        .post(ocr_positions_url())
        .json(&serde_json::json!({ "targets": Vec::<serde_json::Value>::new() }))
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

async fn profit_ocr_has_analysis_roi_endpoint() -> bool {
    let Ok(client) = reqwest::Client::builder()
        .timeout(Duration::from_millis(1200))
        .build()
    else {
        return false;
    };

    client
        .post(ocr_analysis_roi_url())
        .json(&serde_json::json!({ "rect": serde_json::Value::Null }))
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

async fn ocr_port_occupied_without_healthcheck() -> bool {
    for attempt in 0..OCR_PORT_BUSY_RETRY_ATTEMPTS {
        if profit_ocr_http_reachable().await {
            return false;
        }
        let tcp_busy = tokio::net::TcpStream::connect(("127.0.0.1", ocr_port()))
            .await
            .is_ok();
        if !tcp_busy {
            return false;
        }
        // Porta aceita TCP mas HTTP ainda pode estar a subir (PC lento). Usar timeout longo + retries.
        if profit_ocr_http_compatible_long().await {
            return false;
        }
        if attempt + 1 < OCR_PORT_BUSY_RETRY_ATTEMPTS {
            tokio::time::sleep(Duration::from_millis(OCR_PORT_BUSY_RETRY_SLEEP_MS)).await;
        }
    }
    true
}

#[cfg(target_os = "windows")]
fn kill_stale_ocr_processes() {
    let mut c = Command::new("taskkill");
    c.args(["/F", "/IM", "profit_ocr_service.exe", "/T"])
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command_no_console(&mut c);
    let _ = c.status();
}

#[cfg(not(target_os = "windows"))]
fn kill_stale_ocr_processes() {}

/// Garante processo Python do OCR (porta 5558) ao abrir o overlay — evita espera longa no retry do WebSocket.
async fn ensure_profit_ocr_running(
    app: tauri::AppHandle,
    processes: State<'_, ChildProcesses>,
) -> Result<(), String> {
    let base_ocr_port = configured_ocr_port();
    set_runtime_ocr_port(base_ocr_port);
    append_runtime_bootstrap_log(
        &app,
        "ocr",
        "ensure_running",
        "attempt",
        json!({"port": ocr_port(), "base_port": base_ocr_port}),
    );
    let t0 = std::time::Instant::now();
    append_runtime_bootstrap_log(
        &app,
        "ocr",
        "preflight",
        "attempt",
        json!({
            "port": ocr_port(),
            "startup_timeout_ms": ocr_startup_timeout_ms(),
            "startup_attempts": ocr_startup_attempts(),
            "http_health_timeout_ms": OCR_HTTP_HEALTH_TIMEOUT_MS,
        }),
    );
    if profit_ocr_http_reachable().await {
        if !profit_ocr_has_analysis_roi_endpoint().await {
            let err = ocr_incompatible_analysis_roi_message();
            append_runtime_bootstrap_log(
                &app,
                "ocr",
                "ensure_running",
                "error",
                json!({"reason": err.clone(), "kind": "analysis_roi_missing"}),
            );
            return Err(err);
        }
        append_runtime_bootstrap_log(
            &app,
            "ocr",
            "ensure_running",
            "already_reachable",
            json!({"elapsed_ms": t0.elapsed().as_millis()}),
        );
        eprintln!(
            "[overlay-latency] ensure_profit_ocr_running reachable_immediately elapsed_ms={}",
            t0.elapsed().as_millis()
        );
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
        for _ in 0..ocr_startup_attempts() {
            if profit_ocr_http_reachable().await {
                append_runtime_bootstrap_log(
                    &app,
                    "ocr",
                    "ensure_running",
                    "existing_process_ready",
                    json!({"elapsed_ms": t0.elapsed().as_millis()}),
                );
                eprintln!(
                    "[overlay-latency] ensure_profit_ocr_running existing_process_ready elapsed_ms={}",
                    t0.elapsed().as_millis()
                );
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(OCR_POLL_INTERVAL_MS)).await;
        }
        let err = format!(
            "OCR em inicialização, mas não respondeu ao healthcheck em {}s.",
            ocr_startup_timeout_secs()
        );
        append_runtime_bootstrap_log(&app, "ocr", "ensure_running", "error", json!({"reason": err.clone()}));
        return Err(err);
    }

    if !has_tesseract_on_system() {
        let err = tesseract_missing_message();
        append_runtime_bootstrap_log(&app, "ocr", "ensure_running", "error", json!({"reason": err.clone()}));
        return Err(err);
    }
    let mut selected_port: Option<u16> = None;
    for step in 0..=OCR_FALLBACK_PORT_STEPS {
        let candidate = base_ocr_port.saturating_add(step);
        set_runtime_ocr_port(candidate);
        if !ocr_port_occupied_without_healthcheck().await {
            selected_port = Some(candidate);
            break;
        }
        if step == 0 {
            append_runtime_bootstrap_log(
                &app,
                "ocr",
                "port_conflict_recovery",
                "attempt",
                json!({"strategy": "taskkill_profit_ocr_service", "candidate_port": candidate}),
            );
            kill_stale_ocr_processes();
            tokio::time::sleep(Duration::from_millis(850)).await;
            if !ocr_port_occupied_without_healthcheck().await {
                append_runtime_bootstrap_log(
                    &app,
                    "ocr",
                    "port_conflict_recovery",
                    "ok",
                    json!({"reason": "porta liberada após limpeza de OCR órfão", "candidate_port": candidate}),
                );
                selected_port = Some(candidate);
                break;
            }
        }
        append_runtime_bootstrap_log(
            &app,
            "ocr",
            "port_probe",
            "busy",
            json!({"candidate_port": candidate, "step": step}),
        );
    }
    let Some(chosen_port) = selected_port else {
        set_runtime_ocr_port(base_ocr_port);
        let err = format!(
            "OCR sem porta livre no intervalo {}..{}. Feche processos que usem essas portas ou defina PQ_OCR_PORT.",
            base_ocr_port,
            base_ocr_port.saturating_add(OCR_FALLBACK_PORT_STEPS)
        );
        append_runtime_bootstrap_log(
            &app,
            "ocr",
            "ensure_running",
            "error",
            json!({"reason": err.clone(), "recovery_attempted": true}),
        );
        return Err(err);
    };
    if chosen_port != base_ocr_port {
        append_runtime_bootstrap_log(
            &app,
            "ocr",
            "port_fallback",
            "ok",
            json!({"base_port": base_ocr_port, "selected_port": chosen_port}),
        );
    }

    let resources = get_resources_dir(&app)?;
    let res_sub = resources.join("resources");
    let ocr_exe = res_sub.join("profit_ocr_service.exe");
    let script = res_sub.join("profit_ocr_service.py");
    append_runtime_bootstrap_log(
        &app,
        "ocr",
        "preflight",
        "ok",
        json!({
            "resources_dir": resources.to_string_lossy().to_string(),
            "resources_subdir": res_sub.to_string_lossy().to_string(),
            "ocr_exe_path": ocr_exe.to_string_lossy().to_string(),
            "ocr_script_path": script.to_string_lossy().to_string(),
            "ocr_exe_exists": ocr_exe.exists(),
            "ocr_script_exists": script.exists(),
            "tesseract_detected": true,
        }),
    );
    if !ocr_exe.exists() && !script.exists() {
        let err = format!(
            "OCR não encontrado em {} (esperado: profit_ocr_service.exe ou profit_ocr_service.py)",
            res_sub.to_string_lossy()
        );
        append_runtime_bootstrap_log(&app, "ocr", "ensure_running", "error", json!({"reason": err.clone()}));
        return Err(err);
    }

    let logs_dir = app_logs_dir(&app).ok();
    let stderr_path = logs_dir.as_ref().map(|d| d.join("profit_ocr_stderr.log"));
    let stdout_path = logs_dir.as_ref().map(|d| d.join("ocr_stdout.log"));
    append_runtime_bootstrap_log(
        &app,
        "ocr",
        "log_paths",
        "ok",
        json!({
            "logs_dir": logs_dir.as_ref().map(|p| p.to_string_lossy().to_string()),
            "stderr_path": stderr_path.as_ref().map(|p| p.to_string_lossy().to_string()),
            "stdout_path": stdout_path.as_ref().map(|p| p.to_string_lossy().to_string()),
        }),
    );

    let open_std_file = |p: &Option<PathBuf>| -> Stdio {
        if let Some(path) = p {
            match std::fs::File::create(path) {
                Ok(f) => Stdio::from(f),
                Err(_) => Stdio::null(),
            }
        } else {
            Stdio::null()
        }
    };

    let ocr_port_env = chosen_port.to_string();
    let ocr_cfg = read_config(app.clone()).await.unwrap_or_default();
    let overlay_toolbar_h_env = overlay_env_u32(ocr_cfg.overlay_toolbar_h_px);
    let overlay_axis_bottom_crop_env = overlay_env_u32(ocr_cfg.overlay_axis_bottom_crop_px);
    // Em desenvolvimento, prioriza o script canónico quando disponível para evitar
    // divergência com um .exe antigo deixado em resources/.
    let prefer_script_in_dev = cfg!(debug_assertions) && script.exists();
    append_runtime_bootstrap_log(
        &app,
        "ocr",
        "launch_mode",
        "attempt",
        json!({
            "prefer_script_in_dev": prefer_script_in_dev,
            "will_use_exe": ocr_exe.exists() && !prefer_script_in_dev,
            "pq_ocr_port": ocr_port_env,
            "env_overlay_toolbar_h": overlay_toolbar_h_env,
            "env_overlay_axis_bottom_crop_px": overlay_axis_bottom_crop_env,
        }),
    );
    let child = if ocr_exe.exists() && !prefer_script_in_dev {
        let stderr_io = open_std_file(&stderr_path);
        let stdout_io = open_std_file(&stdout_path);
        let mut exe_cmd = Command::new(&ocr_exe);
        exe_cmd
            .current_dir(&res_sub)
            .env("PQ_OCR_PORT", &ocr_port_env)
            .stdout(stdout_io)
            .stderr(stderr_io);
        if let Some(v) = &overlay_toolbar_h_env {
            exe_cmd.env("PQ_OVERLAY_TOOLBAR_H", v);
        }
        if let Some(v) = &overlay_axis_bottom_crop_env {
            exe_cmd.env("PQ_OVERLAY_AXIS_BOTTOM_CROP_PX", v);
        }
        command_no_console(&mut exe_cmd);
        match exe_cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                append_runtime_bootstrap_log(
                    &app,
                    "ocr",
                    "spawn",
                    "error",
                    json!({
                        "mode": "exe",
                        "path": ocr_exe.to_string_lossy().to_string(),
                        "reason": e.to_string(),
                    }),
                );
                return Err(format!(
                    "Falha ao iniciar OCR empacotado em {}: {e}",
                    ocr_exe.to_string_lossy()
                ));
            }
        }
    } else {
        let script_str = script.to_string_lossy().to_string();
        let stderr_io = open_std_file(&stderr_path);
        let stdout_io = open_std_file(&stdout_path);
        let mut py_cmd = Command::new("py");
        py_cmd
            .args(["-3", &script_str])
            .current_dir(&res_sub)
            .env("PQ_OCR_PORT", &ocr_port_env)
            .stdout(stdout_io)
            .stderr(stderr_io);
        if let Some(v) = &overlay_toolbar_h_env {
            py_cmd.env("PQ_OVERLAY_TOOLBAR_H", v);
        }
        if let Some(v) = &overlay_axis_bottom_crop_env {
            py_cmd.env("PQ_OVERLAY_AXIS_BOTTOM_CROP_PX", v);
        }
        command_no_console(&mut py_cmd);
        match py_cmd.spawn() {
            Ok(c) => c,
            Err(e_py) => {
                let py_missing = e_py.kind() == std::io::ErrorKind::NotFound;
                let stderr_io2 = open_std_file(&stderr_path);
                let stdout_io2 = open_std_file(&stdout_path);
                let mut alt = Command::new("python");
                alt.arg(&script_str)
                    .current_dir(&res_sub)
                    .env("PQ_OCR_PORT", &ocr_port_env)
                    .stdout(stdout_io2)
                    .stderr(stderr_io2);
                if let Some(v) = &overlay_toolbar_h_env {
                    alt.env("PQ_OVERLAY_TOOLBAR_H", v);
                }
                if let Some(v) = &overlay_axis_bottom_crop_env {
                    alt.env("PQ_OVERLAY_AXIS_BOTTOM_CROP_PX", v);
                }
                command_no_console(&mut alt);
                match alt.spawn() {
                    Ok(c2) => c2,
                    Err(e_py2) => {
                        append_runtime_bootstrap_log(
                            &app,
                            "ocr",
                            "spawn",
                            "error",
                            json!({
                                "mode": "python_script",
                                "script": script_str,
                                "py_error": e_py.to_string(),
                                "python_error": e_py2.to_string(),
                            }),
                        );
                        let python_missing = e_py2.kind() == std::io::ErrorKind::NotFound;
                        if py_missing && python_missing {
                            return Err("OCR sem executável empacotado e Python não encontrado no sistema (comandos 'py' e 'python'). Reinstale o app com profit_ocr_service.exe ou instale Python 3.".to_string());
                        }
                        return Err(format!("Falha ao iniciar OCR via script Python (py: {e_py}, python: {e_py2})"));
                    }
                }
            }
        }
    };

    let mut child = child;
    append_runtime_bootstrap_log(
        &app,
        "ocr",
        "spawn",
        "ok",
        json!({
            "pid": child.id(),
            "elapsed_ms": t0.elapsed().as_millis(),
        }),
    );
    for _ in 0..ocr_startup_attempts() {
        if profit_ocr_http_reachable().await {
            let mut ocr_guard = processes.profit_ocr.lock().map_err(|e| e.to_string())?;
            *ocr_guard = Some(child);
            append_runtime_bootstrap_log(
                &app,
                "ocr",
                "ensure_running",
                "spawned_ready",
                json!({"elapsed_ms": t0.elapsed().as_millis()}),
            );
            eprintln!(
                "[overlay-latency] ensure_profit_ocr_running spawned_ready elapsed_ms={}",
                t0.elapsed().as_millis()
            );
            return Ok(());
        }
        if let Ok(Some(status)) = child.try_wait() {
            let base = format!("OCR encerrou durante startup (status: {status}).");
            let err = ocr_startup_failure_message(&stderr_path, &base);
            append_runtime_bootstrap_log(
                &app,
                "ocr",
                "ensure_running",
                "error",
                json!({
                    "reason": err.clone(),
                    "child_exit_status": status.code(),
                    "elapsed_ms": t0.elapsed().as_millis(),
                }),
            );
            return Err(err);
        }
        tokio::time::sleep(Duration::from_millis(OCR_POLL_INTERVAL_MS)).await;
    }
    {
        let mut ocr_guard = processes.profit_ocr.lock().map_err(|e| e.to_string())?;
        *ocr_guard = Some(child);
    }
    let err = ocr_startup_failure_message(
        &stderr_path,
        &format!(
            "OCR iniciou, mas não ficou alcançável no healthcheck em {}s. Possíveis causas: primeira execução (antivírus analisando o executável), máquina lenta, ou porta bloqueada. Veja profit_ocr_stderr.log na pasta de dados do app.",
            ocr_startup_timeout_secs()
        ),
    );
    append_runtime_bootstrap_log(&app, "ocr", "ensure_running", "error", json!({"reason": err.clone()}));
    Err(err)
}

#[tauri::command]
pub async fn open_profit_overlay(
    app: tauri::AppHandle,
    processes: State<'_, ChildProcesses>,
) -> Result<(), String> {
    let _open_guard = overlay_open_lock().lock().await;
    append_runtime_bootstrap_log(&app, "overlay", "open_profit_overlay", "attempt", json!({}));
    let t0 = std::time::Instant::now();

    // OCR antes das janelas: evita overlay visível sem serviço e falha limpa sem UI órfã.
    if let Err(e) = ensure_profit_ocr_running(app.clone(), processes).await {
        append_runtime_bootstrap_log(
            &app,
            "overlay",
            "open_profit_overlay",
            "error",
            json!({"reason": e.clone(), "phase": "ensure_ocr"}),
        );
        return Err(e);
    }
    push_saved_ocr_analysis_roi_to_http(&app).await;

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

    append_runtime_bootstrap_log(
        &app,
        "overlay",
        "open_profit_overlay",
        "ok",
        json!({"elapsed_ms": t0.elapsed().as_millis()}),
    );
    eprintln!(
        "[overlay-latency] open_profit_overlay windows_ready elapsed_ms={}",
        t0.elapsed().as_millis()
    );

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

/// Janela full-screen para desenhar retângulo: OCR de análise (não altera posição das linhas).
#[tauri::command]
pub async fn open_ocr_roi_picker(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("ocr-roi-picker") {
        w.show().map_err(|e| e.to_string())?;
        w.set_always_on_top(true).map_err(|e| e.to_string())?;
        let _ = w.set_focus();
        return Ok(());
    }
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

    let window = WebviewWindowBuilder::new(&app, "ocr-roi-picker", url)
        .title("Região OCR (análise)")
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

    let _ = window.set_focus();
    Ok(())
}

#[tauri::command]
pub async fn close_ocr_roi_picker(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("ocr-roi-picker") {
        w.close().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub async fn submit_ocr_analysis_roi(
    app: tauri::AppHandle,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    if width < 8.0 || height < 8.0 {
        return Err("Selecione uma área maior (arraste um retângulo no ecrã).".to_string());
    }
    let win = app
        .get_webview_window("ocr-roi-picker")
        .ok_or("Janela de seleção não encontrada")?;
    let pos = win.inner_position().map_err(|e| e.to_string())?;
    let scale = win.scale_factor().map_err(|e| e.to_string())?;
    let left = (pos.x as f64 + x * scale).round() as i32;
    let top = (pos.y as f64 + y * scale).round() as i32;
    let w = (width * scale).round() as i32;
    let h = (height * scale).round() as i32;
    if w < 4 || h < 4 {
        return Err("Área inválida após conversão de escala.".to_string());
    }
    let client = reqwest::Client::new();
    let res = client
        .post(ocr_analysis_roi_url())
        .json(&json!({
            "rect": { "left": left, "top": top, "width": w, "height": h }
        }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !res.status().is_success() {
        if res.status() == reqwest::StatusCode::NOT_FOUND {
            return Err(ocr_incompatible_analysis_roi_message());
        }
        return Err(format!("OCR analysis_roi HTTP {}", res.status()));
    }
    let mut merged = read_config(app.clone()).await?;
    merged.ocr_analysis_roi = Some(OcrAnalysisRoiConfig {
        left,
        top,
        width: w,
        height: h,
    });
    let path_str = get_config_path(app.clone()).await?;
    write_config_to_disk(&PathBuf::from(path_str), &merged)?;
    let _ = win.close();
    Ok(())
}

#[tauri::command]
pub async fn clear_ocr_analysis_roi(app: tauri::AppHandle) -> Result<(), String> {
    let client = reqwest::Client::new();
    let res = client
        .post(ocr_analysis_roi_url())
        .json(&json!({ "rect": null }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !res.status().is_success() {
        if res.status() == reqwest::StatusCode::NOT_FOUND {
            return Err(ocr_incompatible_analysis_roi_message());
        }
        return Err(format!("OCR analysis_roi clear HTTP {}", res.status()));
    }
    let mut merged = read_config(app.clone()).await?;
    merged.ocr_analysis_roi = None;
    let path_str = get_config_path(app.clone()).await?;
    write_config_to_disk(&PathBuf::from(path_str), &merged)?;
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
    if config.renko_brick_points.is_some() {
        merged.renko_brick_points = config.renko_brick_points;
    }
    if config.ifr_series.is_some() {
        merged.ifr_series = config.ifr_series.clone();
    }
    if config.widget_windows.is_some() {
        merged.widget_windows = config.widget_windows;
    }
    if config.overlay_right_margin_px.is_some() {
        merged.overlay_right_margin_px = config.overlay_right_margin_px;
    }
    if config.overlay_toolbar_h_px.is_some() {
        merged.overlay_toolbar_h_px = config.overlay_toolbar_h_px;
    }
    if config.overlay_axis_bottom_crop_px.is_some() {
        merged.overlay_axis_bottom_crop_px = config.overlay_axis_bottom_crop_px;
    }
    if let Some(ref roi) = config.ocr_analysis_roi {
        merged.ocr_analysis_roi = Some(roi.clone());
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

    write_config_to_disk(&path, &merged)
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
    append_runtime_bootstrap_log(&app, "engine", "spawn_engine", "attempt", json!({}));
    kill_stale_processes();
    std::thread::sleep(Duration::from_millis(300));

    let resources = get_resources_dir(&app)?;
    let engine_dir = resources.join("resources");
    let engine_exe = engine_dir.join("engine.exe");

    if !engine_exe.exists() {
        let err = format!(
            "engine.exe não encontrado em {}",
            engine_exe.display()
        );
        append_runtime_bootstrap_log(&app, "engine", "spawn_engine", "error", json!({"reason": err.clone()}));
        return Err(err);
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
        let err = "Preencha as credenciais Profit em Configurações antes de iniciar o engine.".to_string();
        append_runtime_bootstrap_log(&app, "engine", "spawn_engine", "error", json!({"reason": err.clone()}));
        return Err(err);
    }

    let mut engine_guard = processes.engine.lock().map_err(|e| e.to_string())?;
    if let Some(ref mut child) = *engine_guard {
        if child.try_wait().ok().flatten().is_some() {
            *engine_guard = None;
        } else {
            let err = "Engine já está em execução".to_string();
            append_runtime_bootstrap_log(&app, "engine", "spawn_engine", "error", json!({"reason": err.clone()}));
            return Err(err);
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

    let engine_stderr_path = app_logs_dir(&app).ok().map(|d| d.join("engine_stderr.log"));

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

    if let Some(ms) = env_nonempty("DOM_SNAPSHOT_PUBLISH_MIN_MS") {
        cmd.env("DOM_SNAPSHOT_PUBLISH_MIN_MS", ms);
    }

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
    let pid = child.id();
    append_runtime_bootstrap_log(
        &app,
        "engine",
        "spawn_engine",
        "ok",
        json!({
            "pid": pid,
            "engine_log": engine_log_path,
            "engine_stderr_log": engine_stderr_path.map(|p| p.to_string_lossy().to_string())
        }),
    );
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
    append_runtime_bootstrap_log(&app, "distributor", "spawn_distributor", "attempt", json!({}));
    // Se já há processo na porta 8000 (ex.: iniciado pelo script run-dev), não spawnar de novo
    if check_health().await.unwrap_or(false) {
        append_runtime_bootstrap_log(&app, "distributor", "spawn_distributor", "already_healthy", json!({}));
        return Ok(());
    }

    let config = read_config(app.clone()).await?;

    let resources = get_resources_dir(&app)?;
    let dist_dir = resources.join("resources");
    let dist_exe = dist_dir.join("distributor.exe");

    if !dist_exe.exists() {
        let err = format!(
            "distributor.exe não encontrado em {}",
            dist_exe.display()
        );
        append_runtime_bootstrap_log(&app, "distributor", "spawn_distributor", "error", json!({"reason": err.clone()}));
        return Err(err);
    }

    let logs_dir = app_logs_dir(&app).ok();
    let dist_stderr_path = logs_dir.as_ref().map(|d| d.join("distributor_stderr.log"));
    let dist_stdout_path = logs_dir.as_ref().map(|d| d.join("distributor_stdout.log"));

    let dist_stderr = if let Some(ref p) = dist_stderr_path {
        match std::fs::File::create(p) {
            Ok(f) => Stdio::from(f),
            Err(_) => Stdio::null(),
        }
    } else {
        Stdio::null()
    };
    let dist_stdout = if let Some(ref p) = dist_stdout_path {
        match std::fs::File::create(p) {
            Ok(f) => Stdio::from(f),
            Err(_) => Stdio::null(),
        }
    } else {
        Stdio::null()
    };

    let mut dist_guard = processes.distributor.lock().map_err(|e| e.to_string())?;
    if dist_guard.is_some() {
        let err = "Distributor já está em execução".to_string();
        append_runtime_bootstrap_log(&app, "distributor", "spawn_distributor", "error", json!({"reason": err.clone()}));
        return Err(err);
    }

    let mut cmd = Command::new(&dist_exe);
    cmd.current_dir(&dist_dir)
        .stdout(dist_stdout)
        .stderr(dist_stderr);
    apply_agent007_env(&mut cmd, &config);

    command_no_console(&mut cmd);
    let child = cmd.spawn().map_err(|e| e.to_string())?;
    let pid = child.id();
    append_runtime_bootstrap_log(
        &app,
        "distributor",
        "spawn_distributor",
        "ok",
        json!({
            "pid": pid,
            "stdout_log": dist_stdout_path.map(|p| p.to_string_lossy().to_string()),
            "stderr_log": dist_stderr_path.map(|p| p.to_string_lossy().to_string())
        }),
    );

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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub logs_dir: Option<String>,
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

    let logs_dir = app_logs_dir(&app)
        .ok()
        .map(|p| p.to_string_lossy().to_string());
    let (engine_log_path, engine_stderr_path, app_data_dir) = match app.path().app_data_dir() {
        Ok(dir) => {
            let _ = std::fs::create_dir_all(&dir);
            let log_path = dir.join("profit_engine.log").to_string_lossy().to_string();
            let stderr_path = dir
                .join("logs")
                .join("engine_stderr.log")
                .to_string_lossy()
                .to_string();
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
        logs_dir,
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

fn normalize_ifr_series(series: &str) -> Result<String, String> {
    let s = series.trim().to_lowercase();
    match s.as_str() {
        "42r" | "42" => Ok("42r".to_string()),
        "16r" | "16" => Ok("16r".to_string()),
        "30m" | "30min" | "30_min" | "30_minutos" | "30 min" | "30minutos" => Ok("30m".to_string()),
        _ => Err(format!(
            "Série IFR inválida: {series}. Use 42r, 16r ou 30m."
        )),
    }
}

async fn post_ifr_series_to_distributor(series: &str) -> Result<SetActiveAssetResult, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|e| e.to_string())?;
    let url = format!("{DISTRIBUTOR_API_BASE}/api/set-renko-brick");
    let res = client
        .post(url)
        .json(&serde_json::json!({ "series": series }))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let ok = res.status().is_success();
    let body = res.text().await.unwrap_or_default();
    Ok(SetActiveAssetResult {
        success: ok,
        message: if ok {
            format!("IFR série {series} sincronizada com o distributor")
        } else {
            body
        },
    })
}

async fn post_renko_brick_to_distributor(points: u32) -> Result<SetActiveAssetResult, String> {
    let series = if points == 16 { "16r" } else { "42r" };
    post_ifr_series_to_distributor(series).await
}

#[tauri::command]
pub async fn sync_ifr_series_to_distributor(series: String) -> Result<SetActiveAssetResult, String> {
    let norm = normalize_ifr_series(&series)?;
    post_ifr_series_to_distributor(&norm).await
}

#[tauri::command]
pub async fn set_ifr_series(
    app: tauri::AppHandle,
    series: String,
) -> Result<SetActiveAssetResult, String> {
    let norm = normalize_ifr_series(&series)?;
    let mut cfg = read_config(app.clone()).await?;
    cfg.ifr_series = Some(norm.clone());
    match norm.as_str() {
        "30m" => {
            cfg.renko_brick_points = None;
        }
        "16r" => {
            cfg.renko_brick_points = Some(16);
        }
        _ => {
            cfg.renko_brick_points = Some(42);
        }
    }
    write_config(app, cfg).await?;
    post_ifr_series_to_distributor(&norm).await
}

#[tauri::command]
pub async fn sync_renko_brick_to_distributor(points: u32) -> Result<SetActiveAssetResult, String> {
    if points != 16 && points != 42 {
        return Ok(SetActiveAssetResult {
            success: false,
            message: "points deve ser 16 ou 42".to_string(),
        });
    }
    post_renko_brick_to_distributor(points).await
}

#[tauri::command]
pub async fn set_renko_brick_points(
    app: tauri::AppHandle,
    points: u32,
) -> Result<SetActiveAssetResult, String> {
    if points != 16 && points != 42 {
        return Ok(SetActiveAssetResult {
            success: false,
            message: "Use 16 ou 42 pontos Renko.".to_string(),
        });
    }
    let series = if points == 16 { "16r" } else { "42r" };
    set_ifr_series(app, series.to_string()).await
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
    let dir = app_logs_dir(&app)?;
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

#[derive(Debug, Serialize, Deserialize)]
pub struct DiagnosticsBundleResult {
    pub folder: String,
    pub files: Vec<String>,
}

#[tauri::command]
pub async fn collect_diagnostics_bundle(
    app: tauri::AppHandle,
) -> Result<DiagnosticsBundleResult, String> {
    let app_data = app.path().app_data_dir().map_err(|e| format!("{e}"))?;
    let logs_dir = app_logs_dir(&app)?;
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let bundle_dir = app_data.join("diagnostics").join(format!("bundle-{}", ts));
    std::fs::create_dir_all(&bundle_dir).map_err(|e| e.to_string())?;

    let candidates = [
        logs_dir.join("runtime-bootstrap.log"),
        logs_dir.join("engine_stderr.log"),
        logs_dir.join("distributor_stderr.log"),
        logs_dir.join("distributor_stdout.log"),
        logs_dir.join("profit_ocr_stderr.log"),
        logs_dir.join("ocr_stdout.log"),
        app_data.join("profit_engine.log"),
    ];
    let mut copied = Vec::new();
    for src in candidates {
        if src.exists() {
            let dst = bundle_dir.join(src.file_name().unwrap_or_default());
            if std::fs::copy(&src, &dst).is_ok() {
                copied.push(dst.to_string_lossy().to_string());
            }
        }
    }

    let meta = json!({
        "ts_ms": unix_ts_ms(),
        "session_id": diagnostics_session_id(),
        "ocr_port": ocr_port(),
        "tesseract_detected": has_tesseract_on_system(),
        "os": std::env::consts::OS,
        "arch": std::env::consts::ARCH,
    });
    let meta_path = bundle_dir.join("metadata.json");
    std::fs::write(
        &meta_path,
        serde_json::to_string_pretty(&meta).unwrap_or_else(|_| "{}".to_string()),
    )
    .map_err(|e| e.to_string())?;
    copied.push(meta_path.to_string_lossy().to_string());
    append_runtime_bootstrap_log(
        &app,
        "diagnostics",
        "collect_bundle",
        "ok",
        json!({"bundle_dir": bundle_dir.to_string_lossy().to_string(), "files": copied}),
    );
    Ok(DiagnosticsBundleResult {
        folder: bundle_dir.to_string_lossy().to_string(),
        files: copied,
    })
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
