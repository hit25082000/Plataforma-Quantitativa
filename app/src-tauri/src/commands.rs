use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::HashMap;
use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU16, Ordering};
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
use tauri::webview::WebviewWindowBuilder;
use tauri::Emitter;
use tauri::Manager;
use tauri::WebviewWindow;
use tauri::State;
use tauri::WebviewUrl;

const CONFIG_FILENAME: &str = "config.json";
const CONFIG_BACKUP_FILENAME: &str = "config.json.bak";
const CONFIG_TMP_FILENAME: &str = "config.json.tmp";
const CONFIG_CORRUPT_MSG: &str =
    "Arquivo de configuração corrompido. Não foi possível ler; alterações não foram salvas.";

/// Health do distributor. Ver docs/PORTS.md
const HEALTH_URL: &str = "http://127.0.0.1:8000/health";
const DISTRIBUTOR_API_BASE: &str = "http://127.0.0.1:8000";
const AGENT007_CHAT_URL: &str = "http://127.0.0.1:8000/api/agent007/chat";
const DISTRIBUTOR_IPC_STATE_URL: &str = "http://127.0.0.1:8000/ipc-state";
const EVENT_OCR_RECALIBRATING: &str = "pq:ocr-recalibrating";
const EVENT_OCR_OVERLAY_STATUS: &str = "pq:ocr-overlay-status";
const BOUNDS_WATCHDOG_INTERVAL_MS: u64 = 750;
const BOUNDS_RECALIBRATE_COOLDOWN_MS: u64 = 1200;

/// Defaults alinhados a `engine` / `distributor` e `scripts/run-dev2.ps1`.
fn apply_default_shm_writer_env(cmd: &mut Command) {
    cmd.env(
        "SHM_ENABLED",
        env_nonempty("SHM_ENABLED").unwrap_or_else(|| "1".into()),
    );
    cmd.env(
        "SHM_MAPPING_NAME",
        env_nonempty("SHM_MAPPING_NAME").unwrap_or_else(|| r"Local\PQMarketDataV1".into()),
    );
    cmd.env(
        "SHM_SIZE_MB",
        env_nonempty("SHM_SIZE_MB").unwrap_or_else(|| "64".into()),
    );
}

fn apply_default_shm_distributor_env(cmd: &mut Command) {
    cmd.env(
        "IPC_MODE",
        env_nonempty("IPC_MODE").unwrap_or_else(|| "shm".into()),
    );
    cmd.env(
        "SHM_MAPPING_NAME",
        env_nonempty("SHM_MAPPING_NAME").unwrap_or_else(|| r"Local\PQMarketDataV1".into()),
    );
    cmd.env(
        "SHM_SIZE_MB",
        env_nonempty("SHM_SIZE_MB").unwrap_or_else(|| "64".into()),
    );
    cmd.env(
        "SHM_FALLBACK_PROBE_TIMEOUT_MS",
        env_nonempty("SHM_FALLBACK_PROBE_TIMEOUT_MS").unwrap_or_else(|| "90000".into()),
    );
}

#[cfg(target_os = "windows")]
fn kill_listeners_on_port_8000() {
    let ps = r#"Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { if ($_ -and $_ -gt 0) { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } }"#;
    let _ = Command::new("powershell.exe")
        .args(["-NoProfile", "-NonInteractive", "-Command", ps])
        .status();
}

#[cfg(not(target_os = "windows"))]
fn kill_listeners_on_port_8000() {}

async fn fetch_health_ipc_mode() -> Option<String> {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
    {
        Ok(c) => c,
        Err(_) => return None,
    };
    let Ok(res) = client.get(HEALTH_URL).send().await else {
        return None;
    };
    if !res.status().is_success() {
        return None;
    }
    let Ok(v) = res.json::<serde_json::Value>().await else {
        return None;
    };
    v.get("ipc_mode")
        .and_then(|x| x.as_str())
        .map(|s| s.trim().to_lowercase())
}

async fn distributor_has_required_market_routes() -> Option<bool> {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
    {
        Ok(c) => c,
        Err(_) => return None,
    };
    let Ok(res) = client
        .get(format!("{DISTRIBUTOR_API_BASE}/openapi.json"))
        .send()
        .await
    else {
        return None;
    };
    if !res.status().is_success() {
        return None;
    }
    let Ok(v) = res.json::<serde_json::Value>().await else {
        return None;
    };
    let Some(paths) = v.get("paths").and_then(|p| p.as_object()) else {
        return Some(false);
    };
    let required = [
        "/api/volume-profile/debug",
        "/api/vp-overlay/debug",
        "/api/warm-macd",
    ];
    Some(required.iter().all(|route| paths.contains_key(*route)))
}

/// Reinicia o distributor se estiver em ZMQ (ex.: `run-dev.ps1` subiu antes do SHM).
async fn maybe_resync_distributor_if_zmq(
    app: &tauri::AppHandle,
    processes: &State<'_, ChildProcesses>,
) {
    if fetch_health_ipc_mode().await.as_deref() != Some("zmq") {
        return;
    }
    append_runtime_bootstrap_log(
        app,
        "distributor",
        "resync_shm",
        "attempt",
        json!({"reason": "health_ipc_mode_zmq"}),
    );
    {
        let mut dist_guard = match processes.distributor.lock() {
            Ok(g) => g,
            Err(_) => return,
        };
        if let Some(mut child) = dist_guard.take() {
            let _ = child.kill();
        }
    }
    kill_listeners_on_port_8000();
    tokio::time::sleep(Duration::from_millis(900)).await;
    for _ in 0u8..8 {
        if !check_health().await.unwrap_or(false) {
            break;
        }
        kill_listeners_on_port_8000();
        tokio::time::sleep(Duration::from_millis(400)).await;
    }
    if let Err(e) = start_distributor_child(app.clone(), processes).await {
        append_runtime_bootstrap_log(
            app,
            "distributor",
            "resync_shm",
            "error",
            json!({"reason": e}),
        );
    } else {
        append_runtime_bootstrap_log(app, "distributor", "resync_shm", "ok", json!({}));
    }
}

async fn start_distributor_child(
    app: tauri::AppHandle,
    processes: &State<'_, ChildProcesses>,
) -> Result<(), String> {
    let config = read_config(app.clone()).await?;

    let resources = get_resources_dir(&app)?;
    let dist_dir = resources.join("resources");
    let dist_exe = dist_dir.join("distributor.exe");
    let dist_main_py = find_dev_distributor_main(&dist_dir);

    if dist_main_py.is_none() && !dist_exe.exists() {
        let err = format!(
            "distributor indisponível: main.py não encontrado e distributor.exe não encontrado em {}",
            dist_exe.display()
        );
        append_runtime_bootstrap_log(
            &app,
            "distributor",
            "spawn_distributor",
            "error",
            json!({"reason": err.clone()}),
        );
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

    {
        let dist_guard = processes.distributor.lock().map_err(|e| e.to_string())?;
        if dist_guard.is_some() {
            let err = "Distributor já está em execução".to_string();
            append_runtime_bootstrap_log(
                &app,
                "distributor",
                "spawn_distributor",
                "error",
                json!({"reason": err.clone()}),
            );
            return Err(err);
        }
    }

    let mut cmd = if let Some(main_py) = dist_main_py {
        let mut c = Command::new("python");
        if let Some(main_dir) = main_py.parent() {
            c.current_dir(main_dir);
        }
        c.arg("-u").arg("main.py");
        append_runtime_bootstrap_log(
            &app,
            "distributor",
            "spawn_distributor",
            "dev_source",
            json!({"main_py": main_py.to_string_lossy().to_string()}),
        );
        c
    } else {
        let mut c = Command::new(&dist_exe);
        c.current_dir(&dist_dir);
        c
    };
    cmd.stdout(dist_stdout).stderr(dist_stderr);
    apply_default_shm_distributor_env(&mut cmd);
    apply_agent007_env(&mut cmd, &config);
    apply_voice_env(&mut cmd, &config);

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

    {
        let mut dist_guard = processes.distributor.lock().map_err(|e| e.to_string())?;
        *dist_guard = Some(child);
    }
    let _ = emit_distributor_ipc_state_events(&app).await;
    Ok(())
}

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

/// Preferências do overlay VP Sato (`docs/contracts/vp-overlay-v1` → `display`).
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct VpOverlayPrefs {
    #[serde(default)]
    pub enabled: Option<bool>,
    #[serde(default)]
    pub poc_visible: Option<bool>,
    #[serde(default)]
    pub val_vah_visible: Option<bool>,
    #[serde(default)]
    pub labels_visible: Option<bool>,
    #[serde(default)]
    pub histogram_visible: Option<bool>,
    #[serde(default)]
    pub top_avg_visible: Option<bool>,
    #[serde(default)]
    pub stretch_lines: Option<bool>,
    #[serde(default)]
    pub max_avg_lines: Option<u32>,
    #[serde(default)]
    pub max_visible_histogram_levels: Option<u32>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AppConfig {
    pub profit_activation_key: Option<String>,
    pub profit_user: Option<String>,
    pub profit_password: Option<String>, // allow-secret
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
    /// Gemini Live / Copiloto de voz.
    #[serde(default)]
    pub google_api_key: Option<String>,
    #[serde(default)]
    pub voice_functions_enabled: Option<bool>,
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
    /// Periodo do Volume Profile: day | week | manual.
    #[serde(default)]
    pub vp_period: Option<String>,
    #[serde(default)]
    pub show_volume_profile_overlay: Option<bool>,
    #[serde(default)]
    pub show_tape_intelligence_overlay: Option<bool>,
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
    #[serde(default)]
    pub vp_fallback_mode: Option<String>,
    #[serde(default)]
    pub vp_fallback_price_top: Option<f64>,
    #[serde(default)]
    pub vp_fallback_price_bot: Option<f64>,
    #[serde(default)]
    pub vp_overlay: Option<VpOverlayPrefs>,
    /// Só no patch de `write_config`; não persiste no config.json.
    #[serde(default, skip_serializing)]
    pub vp_fallback_price_top_clear: Option<bool>,
    #[serde(default, skip_serializing)]
    pub vp_fallback_price_bot_clear: Option<bool>,
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
            google_api_key: None,
            voice_functions_enabled: None,
            notifications_enabled: Some(true),
            sounds_enabled: Some(true),
            volume: Some(80),
            minimize_to_tray: Some(true),
            start_with_windows: Some(false),
            selected_ticker: Some("WINFUT".to_string()),
            selected_exchange: Some("BMF".to_string()),
            renko_brick_points: None,
            ifr_series: None,
            vp_period: Some("day".to_string()),
            show_volume_profile_overlay: Some(true),
            show_tape_intelligence_overlay: Some(true),
            widget_windows: None,
            overlay_right_margin_px: None,
            overlay_toolbar_h_px: None,
            overlay_axis_bottom_crop_px: None,
            ocr_analysis_roi: None,
            vp_fallback_mode: None,
            vp_fallback_price_top: None,
            vp_fallback_price_bot: None,
            vp_overlay: None,
            vp_fallback_price_top_clear: None,
            vp_fallback_price_bot_clear: None,
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
const ENGINE_CONTROL_CONNECT_TIMEOUT_MS: u64 = 5000;
const ENGINE_CONTROL_IO_TIMEOUT_MS: u64 = 90000;
const ENGINE_VP_PERIOD_IO_TIMEOUT_MS: u64 = 5000;

fn engine_control_port_listening() -> bool {
    let Ok(addr) = format!("127.0.0.1:{}", ENGINE_CONTROL_PORT).parse() else {
        return false;
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(350)).is_ok()
}

#[cfg(target_os = "windows")]
fn engine_process_exists() -> bool {
    let mut c = Command::new("tasklist");
    c.args(["/FI", "IMAGENAME eq engine.exe", "/FO", "CSV", "/NH"]);
    command_no_console(&mut c);
    let Ok(out) = c.output() else {
        return false;
    };
    let s = String::from_utf8_lossy(&out.stdout).to_ascii_lowercase();
    s.contains("\"engine.exe\"")
}

#[cfg(not(target_os = "windows"))]
fn engine_process_exists() -> bool {
    false
}

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

fn ocr_recalibrate_url() -> String {
    format!("http://127.0.0.1:{}/api/ocr-overlay/recalibrate", ocr_port())
}

fn ocr_freeze_url() -> String {
    format!("http://127.0.0.1:{}/api/ocr-overlay/freeze", ocr_port())
}

fn ocr_unfreeze_url() -> String {
    format!("http://127.0.0.1:{}/api/ocr-overlay/unfreeze", ocr_port())
}

fn ocr_manual_calibration_url() -> String {
    format!("http://127.0.0.1:{}/api/ocr-overlay/manual-calibration", ocr_port())
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
    if lower.contains("address already in use")
        || lower.contains("only one usage of each socket address")
    {
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
    app.path().resource_dir().map_err(|e| format!("{e}"))
}

fn find_dev_distributor_main(resources_dir: &Path) -> Option<PathBuf> {
    if !cfg!(debug_assertions) {
        return None;
    }
    for ancestor in resources_dir.ancestors() {
        let candidate = ancestor.join("distributor").join("main.py");
        if candidate.exists() {
            return Some(candidate);
        }
    }
    None
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

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
struct WindowPhysicalSnapshot {
    window_label: &'static str,
    pos_x: i32,
    pos_y: i32,
    width: u32,
    height: u32,
    minimized: bool,
    monitor_pos_x: i32,
    monitor_pos_y: i32,
    monitor_width: u32,
    monitor_height: u32,
    monitor_scale_permille: u32,
}

#[derive(Default)]
struct OverlayBoundsWatchdog {
    running: AtomicBool,
    stop_requested: AtomicBool,
}

fn overlay_bounds_watchdog() -> &'static OverlayBoundsWatchdog {
    static WD: OnceLock<OverlayBoundsWatchdog> = OnceLock::new();
    WD.get_or_init(OverlayBoundsWatchdog::default)
}

fn monitor_scale_permille(scale: f64) -> u32 {
    if !scale.is_finite() || scale <= 0.0 {
        return 1000;
    }
    (scale * 1000.0).round() as u32
}

fn capture_window_physical_snapshot(
    app: &tauri::AppHandle,
    label: &'static str,
) -> Option<WindowPhysicalSnapshot> {
    let win = app.get_webview_window(label)?;
    let visible = win.is_visible().ok()?;
    if !visible {
        return None;
    }
    let pos = win.outer_position().ok()?;
    let size = win.outer_size().ok()?;
    let minimized = win.is_minimized().ok().unwrap_or(false);
    let monitor = win.current_monitor().ok().flatten()?;
    let mon_pos = monitor.position();
    let mon_size = monitor.size();
    let mon_scale = monitor_scale_permille(monitor.scale_factor());
    Some(WindowPhysicalSnapshot {
        window_label: label,
        pos_x: pos.x,
        pos_y: pos.y,
        width: size.width,
        height: size.height,
        minimized,
        monitor_pos_x: mon_pos.x,
        monitor_pos_y: mon_pos.y,
        monitor_width: mon_size.width,
        monitor_height: mon_size.height,
        monitor_scale_permille: mon_scale,
    })
}

fn collect_relevant_window_snapshots(app: &tauri::AppHandle) -> Vec<WindowPhysicalSnapshot> {
    let mut out = Vec::new();
    if let Some(s) = capture_window_physical_snapshot(app, "profit-overlay") {
        out.push(s);
    }
    if let Some(s) = capture_window_physical_snapshot(app, "ocr-roi-picker") {
        out.push(s);
    }
    out
}

fn start_overlay_bounds_watchdog(app: tauri::AppHandle) {
    let watchdog = overlay_bounds_watchdog();
    watchdog.stop_requested.store(false, Ordering::SeqCst);
    if watchdog.running.swap(true, Ordering::SeqCst) {
        return;
    }
    tauri::async_runtime::spawn(async move {
        let mut last_snapshots: Vec<WindowPhysicalSnapshot> = Vec::new();
        let mut last_recalibrate_at = std::time::Instant::now()
            .checked_sub(Duration::from_millis(BOUNDS_RECALIBRATE_COOLDOWN_MS))
            .unwrap_or_else(std::time::Instant::now);
        loop {
            if overlay_bounds_watchdog()
                .stop_requested
                .load(Ordering::SeqCst)
            {
                break;
            }
            let current_snapshots = collect_relevant_window_snapshots(&app);
            if !current_snapshots.is_empty() && current_snapshots != last_snapshots {
                let now = std::time::Instant::now();
                if now.duration_since(last_recalibrate_at).as_millis() as u64
                    >= BOUNDS_RECALIBRATE_COOLDOWN_MS
                {
                    let payload = json!({
                        "reason": "physical_bounds_changed",
                        "windows": current_snapshots,
                    });
                    let _ = app.emit(EVENT_OCR_RECALIBRATING, payload.clone());
                    append_runtime_bootstrap_log(
                        &app,
                        "overlay",
                        "bounds_watchdog",
                        "recalibrating",
                        payload,
                    );
                    let _ = recalibrate_profit_ocr(app.clone()).await;
                    last_recalibrate_at = now;
                }
            }
            last_snapshots = current_snapshots;
            tokio::time::sleep(Duration::from_millis(BOUNDS_WATCHDOG_INTERVAL_MS)).await;
        }
        overlay_bounds_watchdog()
            .running
            .store(false, Ordering::SeqCst);
    });
}

fn stop_overlay_bounds_watchdog() {
    overlay_bounds_watchdog()
        .stop_requested
        .store(true, Ordering::SeqCst);
}

fn emit_ocr_overlay_status(
    app: &tauri::AppHandle,
    action: &str,
    status: &str,
    details: serde_json::Value,
) {
    let payload = json!({
        "action": action,
        "status": status,
        "details": details,
        "ts_ms": unix_ts_ms(),
    });
    let _ = app.emit(EVENT_OCR_OVERLAY_STATUS, payload.clone());
    if action == "recalibrate" && status == "start" {
        // Compatibilidade com listeners legados durante transição.
        let _ = app.emit(EVENT_OCR_RECALIBRATING, payload);
    }
}

fn resolve_target_monitor(
    app: &tauri::AppHandle,
    preferred_window: Option<&WebviewWindow>,
) -> Result<tauri::Monitor, String> {
    if let Some(win) = preferred_window {
        if let Some(monitor) = win.current_monitor().map_err(|e| e.to_string())? {
            return Ok(monitor);
        }
    }
    if let Some(main) = app.get_webview_window("main") {
        if let Some(monitor) = main.current_monitor().map_err(|e| e.to_string())? {
            return Ok(monitor);
        }
    }
    app.primary_monitor()
        .map_err(|e| e.to_string())?
        .ok_or("Monitor principal não encontrado".to_string())
}

fn logical_to_physical_rect_for_window(
    win: &WebviewWindow,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(i32, i32, i32, i32), String> {
    let origin = win.outer_position().map_err(|e| e.to_string())?;
    let scale = match win.current_monitor().map_err(|e| e.to_string())? {
        Some(mon) => mon.scale_factor(),
        None => win.scale_factor().map_err(|e| e.to_string())?,
    };
    let left = (origin.x as f64 + x * scale).round() as i32;
    let top = (origin.y as f64 + y * scale).round() as i32;
    let w = (width * scale).round() as i32;
    let h = (height * scale).round() as i32;
    Ok((left, top, w, h))
}

#[tauri::command]
pub async fn get_ocr_runtime_port() -> Result<u16, String> {
    Ok(ocr_port())
}

/// Limpa EMA do eixo e suavização de Y no `profit_ocr_service` (pós-zoom / re-alinhar).
#[tauri::command]
pub async fn recalibrate_profit_ocr(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    emit_ocr_overlay_status(
        &app,
        "recalibrate",
        "start",
        json!({"source": "command"}),
    );
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(4))
        .build()
        .map_err(|e| e.to_string())?;
    let res = client
        .post(ocr_recalibrate_url())
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !res.status().is_success() {
        emit_ocr_overlay_status(
            &app,
            "recalibrate",
            "error",
            json!({"source": "command", "http_status": res.status().as_u16()}),
        );
        return Err(format!("OCR recalibrate HTTP {}", res.status()));
    }
    let payload: serde_json::Value = res.json().await.map_err(|e| e.to_string())?;
    emit_ocr_overlay_status(
        &app,
        "recalibrate",
        "ok",
        json!({"source": "command", "response": payload}),
    );
    Ok(payload)
}

#[tauri::command]
pub async fn freeze_profit_ocr(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    emit_ocr_overlay_status(&app, "freeze", "start", json!({}));
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(4))
        .build()
        .map_err(|e| e.to_string())?;
    let res = client
        .post(ocr_freeze_url())
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !res.status().is_success() {
        emit_ocr_overlay_status(
            &app,
            "freeze",
            "error",
            json!({"http_status": res.status().as_u16()}),
        );
        return Err(format!("OCR freeze HTTP {}", res.status()));
    }
    let payload: serde_json::Value = res.json().await.map_err(|e| e.to_string())?;
    emit_ocr_overlay_status(&app, "freeze", "ok", json!({"response": payload}));
    Ok(payload)
}

#[tauri::command]
pub async fn unfreeze_profit_ocr(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    emit_ocr_overlay_status(&app, "freeze", "released", json!({}));
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(4))
        .build()
        .map_err(|e| e.to_string())?;
    let res = client
        .post(ocr_unfreeze_url())
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !res.status().is_success() {
        emit_ocr_overlay_status(
            &app,
            "freeze",
            "error",
            json!({"http_status": res.status().as_u16(), "phase": "unfreeze"}),
        );
        return Err(format!("OCR unfreeze HTTP {}", res.status()));
    }
    let payload: serde_json::Value = res.json().await.map_err(|e| e.to_string())?;
    emit_ocr_overlay_status(&app, "freeze", "ok", json!({"phase": "unfreeze", "response": payload}));
    Ok(payload)
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ManualCalibrationPoint {
    value: f64,
    y_screen: f64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ManualCalibrationRequest {
    points: Vec<ManualCalibrationPoint>,
}

#[tauri::command]
pub async fn manual_calibrate_profit_ocr(
    body: ManualCalibrationRequest,
) -> Result<serde_json::Value, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(4))
        .build()
        .map_err(|e| e.to_string())?;
    let res = client
        .post(ocr_manual_calibration_url())
        .json(&body)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !res.status().is_success() {
        return Err(format!("OCR manual calibration HTTP {}", res.status()));
    }
    res.json().await.map_err(|e| e.to_string())
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
        append_runtime_bootstrap_log(
            &app,
            "ocr",
            "ensure_running",
            "error",
            json!({"reason": err.clone()}),
        );
        return Err(err);
    }

    if !has_tesseract_on_system() {
        let err = tesseract_missing_message();
        append_runtime_bootstrap_log(
            &app,
            "ocr",
            "ensure_running",
            "error",
            json!({"reason": err.clone()}),
        );
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
        append_runtime_bootstrap_log(
            &app,
            "ocr",
            "ensure_running",
            "error",
            json!({"reason": err.clone()}),
        );
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
                        return Err(format!(
                            "Falha ao iniciar OCR via script Python (py: {e_py}, python: {e_py2})"
                        ));
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
    append_runtime_bootstrap_log(
        &app,
        "ocr",
        "ensure_running",
        "error",
        json!({"reason": err.clone()}),
    );
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

    let main_window = app.get_webview_window("main");
    let target_monitor = resolve_target_monitor(&app, main_window.as_ref())?;
    let target_monitor_pos = target_monitor.position();
    let target_monitor_size = target_monitor.size();

    if let Some(win) = app.get_webview_window("profit-overlay") {
        win.show().map_err(|e| e.to_string())?;
        win.set_always_on_top(true).map_err(|e| e.to_string())?;
        win.set_ignore_cursor_events(true)
            .map_err(|e| e.to_string())?;
        let _ = win.set_size(tauri::Size::Physical(tauri::PhysicalSize {
            width: target_monitor_size.width,
            height: target_monitor_size.height,
        }));
        let _ = win.set_position(tauri::Position::Physical(tauri::PhysicalPosition {
            x: target_monitor_pos.x,
            y: target_monitor_pos.y,
        }));
    } else {
        let screen_w = target_monitor_size.width as f64;
        let screen_h = target_monitor_size.height as f64;

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
            .position(target_monitor_pos.x as f64, target_monitor_pos.y as f64)
            .build()
            .map_err(|e| e.to_string())?;

        window
            .set_ignore_cursor_events(true)
            .map_err(|e| e.to_string())?;
    }

    let screen_w = target_monitor_size.width as f64;

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
        let ctrl_x = target_monitor_pos.x as f64 + (screen_w - ctrl_w - 16.0).max(0.0);
        let ctrl_y = target_monitor_pos.y as f64 + 16.0;
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
    start_overlay_bounds_watchdog(app.clone());

    Ok(())
}

#[tauri::command]
pub async fn close_profit_overlay(app: tauri::AppHandle) -> Result<(), String> {
    stop_overlay_bounds_watchdog();
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
    let main_window = app.get_webview_window("main");
    let monitor = resolve_target_monitor(&app, main_window.as_ref())?;
    let monitor_pos = monitor.position();
    let monitor_size = monitor.size();
    let screen_w = monitor_size.width as f64;
    let screen_h = monitor_size.height as f64;

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
        .position(monitor_pos.x as f64, monitor_pos.y as f64)
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
    let (left, top, w, h) = logical_to_physical_rect_for_window(&win, x, y, width, height)?;
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
    let config_dir = app.path().app_config_dir().map_err(|e| format!("{e}"))?;
    std::fs::create_dir_all(&config_dir).map_err(|e| e.to_string())?;
    Ok(config_dir
        .join(CONFIG_FILENAME)
        .to_string_lossy()
        .to_string())
}

fn parse_config_contents(contents: &str) -> Result<AppConfig, String> {
    let trimmed = contents.strip_prefix('\u{feff}').unwrap_or(contents).trim();
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
                AppConfig::deserialize(&mut de)
                    .map_err(|e2| format!("config.json inválido ou corrompido: {e2}"))
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
        merged.profit_password = config.profit_password; // allow-secret
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
    if config.vp_period.is_some() {
        merged.vp_period = config.vp_period;
    }
    if config.show_volume_profile_overlay.is_some() {
        merged.show_volume_profile_overlay = config.show_volume_profile_overlay;
    }
    if config.show_tape_intelligence_overlay.is_some() {
        merged.show_tape_intelligence_overlay = config.show_tape_intelligence_overlay;
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

    if let Some(ref v) = config.vp_fallback_mode {
        merged.vp_fallback_mode = if v.trim().is_empty() {
            None
        } else {
            Some(v.trim().to_string())
        };
    }
    if config.vp_fallback_price_top_clear == Some(true) {
        merged.vp_fallback_price_top = None;
    } else if let Some(v) = config.vp_fallback_price_top {
        merged.vp_fallback_price_top = Some(v);
    }
    if config.vp_fallback_price_bot_clear == Some(true) {
        merged.vp_fallback_price_bot = None;
    } else     if let Some(v) = config.vp_fallback_price_bot {
        merged.vp_fallback_price_bot = Some(v);
    }

    if let Some(patch) = &config.vp_overlay {
        let mut base = merged.vp_overlay.clone().unwrap_or_default();
        if patch.enabled.is_some() {
            base.enabled = patch.enabled;
        }
        if patch.poc_visible.is_some() {
            base.poc_visible = patch.poc_visible;
        }
        if patch.val_vah_visible.is_some() {
            base.val_vah_visible = patch.val_vah_visible;
        }
        if patch.labels_visible.is_some() {
            base.labels_visible = patch.labels_visible;
        }
        if patch.histogram_visible.is_some() {
            base.histogram_visible = patch.histogram_visible;
        }
        if patch.top_avg_visible.is_some() {
            base.top_avg_visible = patch.top_avg_visible;
        }
        if patch.stretch_lines.is_some() {
            base.stretch_lines = patch.stretch_lines;
        }
        if patch.max_avg_lines.is_some() {
            base.max_avg_lines = patch.max_avg_lines;
        }
        if patch.max_visible_histogram_levels.is_some() {
            base.max_visible_histogram_levels = patch.max_visible_histogram_levels;
        }
        merged.vp_overlay = Some(base);
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

    if let Some(v) = config.google_api_key {
        merged.google_api_key = if v.trim().is_empty() {
            None
        } else {
            Some(v.trim().to_string())
        };
    }
    if let Some(v) = config.voice_functions_enabled {
        merged.voice_functions_enabled = Some(v);
    }

    write_config_to_disk(&path, &merged)?;
    let _ = app.emit("pq:config-saved", json!({}));
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

#[tauri::command]
pub async fn get_distributor_health() -> Result<serde_json::Value, String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;
    let res = client
        .get(HEALTH_URL)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !res.status().is_success() {
        return Err(format!("HTTP {}", res.status()));
    }
    res.json().await.map_err(|e| e.to_string())
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
    let mut val: Agent007ChatApiResult = serde_json::from_str(&text)
        .map_err(|e| format!("Resposta inválida do distributor: {e}"))?;
    if !status.is_success() && val.error.is_none() {
        val.ok = false;
        val.error = Some(format!("HTTP {status}"));
    }
    Ok(val)
}

#[tauri::command]
pub async fn spawn_engine(
    app: tauri::AppHandle,
    processes: State<'_, ChildProcesses>,
) -> Result<(), String> {
    append_runtime_bootstrap_log(&app, "engine", "spawn_engine", "attempt", json!({}));

    if engine_control_port_listening() {
        append_runtime_bootstrap_log(
            &app,
            "engine",
            "spawn_engine",
            "already_running",
            json!({"reason": "engine_control_port_listening"}),
        );
        maybe_resync_distributor_if_zmq(&app, &processes).await;
        return Ok(());
    }

    let resources = get_resources_dir(&app)?;
    let engine_dir = resources.join("resources");
    let engine_exe = engine_dir.join("engine.exe");

    if !engine_exe.exists() {
        let err = format!("engine.exe não encontrado em {}", engine_exe.display());
        append_runtime_bootstrap_log(
            &app,
            "engine",
            "spawn_engine",
            "error",
            json!({"reason": err.clone()}),
        );
        return Err(err);
    }

    let config = read_config(app.clone()).await?;

    let (resolved_key, resolved_user, resolved_pass) = resolve_engine_credentials(&config);
    if resolved_key.is_none() || resolved_user.is_none() || resolved_pass.is_none() {
        let err = "Preencha as credenciais Profit em Configurações (ou via env PROFIT_*/PROFIT_DLL_*) antes de iniciar o engine.".to_string();
        append_runtime_bootstrap_log(
            &app,
            "engine",
            "spawn_engine",
            "error",
            json!({"reason": err.clone()}),
        );
        return Err(err);
    }

    let tracked_child_running = {
        let mut engine_guard = processes.engine.lock().map_err(|e| e.to_string())?;
        if let Some(ref mut child) = *engine_guard {
            if child.try_wait().ok().flatten().is_some() {
                *engine_guard = None;
                false
            } else {
                append_runtime_bootstrap_log(
                    &app,
                    "engine",
                    "spawn_engine",
                    "already_running",
                    json!({"reason": "tracked_child_running"}),
                );
                true
            }
        } else {
            false
        }
    };
    if tracked_child_running {
        maybe_resync_distributor_if_zmq(&app, &processes).await;
        return Ok(());
    }

    if engine_process_exists() {
        append_runtime_bootstrap_log(
            &app,
            "engine",
            "spawn_engine",
            "already_running",
            json!({"reason": "engine_process_exists_without_tracked_child"}),
        );
        maybe_resync_distributor_if_zmq(&app, &processes).await;
        return Ok(());
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

    let mut cmd = Command::new(&engine_exe);
    cmd.current_dir(&engine_dir)
        .stdout(Stdio::null())
        .stderr(stderr_cfg)
        .env("DEBUG_LOG_PATH", &engine_log_path);

    if let Some(ms) = env_nonempty("DOM_SNAPSHOT_PUBLISH_MIN_MS") {
        cmd.env("DOM_SNAPSHOT_PUBLISH_MIN_MS", ms);
    }

    cmd.env(
        "PROFIT_ACTIVATION_KEY",
        resolved_key.clone().unwrap_or_default(),
    );
    cmd.env(
        "PROFIT_DLL_ACTIVATION_KEY",
        resolved_key.clone().unwrap_or_default(),
    );
    cmd.env("PROFIT_USER", resolved_user.clone().unwrap_or_default());
    cmd.env("PROFIT_PASSWORD", resolved_pass.clone().unwrap_or_default());
    cmd.env("PROFIT_DLL_USER", resolved_user.clone().unwrap_or_default());
    cmd.env(
        "PROFIT_DLL_PASSWORD",
        resolved_pass.clone().unwrap_or_default(),
    );
    let raw_ticker = config
        .selected_ticker
        .as_deref()
        .unwrap_or("WINFUT")
        .trim()
        .to_uppercase();
    let raw_exchange = config
        .selected_exchange
        .as_deref()
        .unwrap_or("BMF")
        .trim()
        .to_uppercase();

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
    let spawn_marker = format!("spawn-{}-{}", std::process::id(), unix_ts_ms());
    append_engine_spawn_marker(&engine_log_path, &spawn_marker);

    apply_default_shm_writer_env(&mut cmd);
    command_no_console(&mut cmd);
    let mut child = cmd.spawn().map_err(|e| e.to_string())?;
    let pid = child.id();

    let mut subscribe_status: Option<(i32, i32)> = None;
    let startup_deadline = std::time::Instant::now() + Duration::from_secs(30);
    while std::time::Instant::now() < startup_deadline {
        if let Ok(Some(status)) = child.try_wait() {
            let err = format!("Engine encerrou durante startup (status: {status}).");
            append_runtime_bootstrap_log(
                &app,
                "engine",
                "spawn_engine",
                "error",
                json!({"reason": err}),
            );
            return Err(err);
        }
        if let Ok(Some((st, sb))) =
            read_engine_started_after_marker(&engine_log_path, &spawn_marker)
        {
            subscribe_status = Some((st, sb));
            break;
        }
        std::thread::sleep(Duration::from_millis(250));
    }

    if let Some((st, sb)) = subscribe_status {
        if st != 0 || sb != 0 {
            let _ = child.kill();
            let err = format!(
                "Engine iniciou sem conexão de mercado (Ticker={}, OfferBook={}). Reinicie os serviços.",
                st, sb
            );
            append_runtime_bootstrap_log(
                &app,
                "engine",
                "spawn_engine",
                "error",
                json!({"reason": err, "subscribe_ticker_ret": st, "subscribe_offer_book_ret": sb}),
            );
            return Err(err);
        }
    } else {
        let child_running = child.try_wait().ok().flatten().is_none();
        let control_port_ready = engine_control_port_listening();
        if !child_running && !control_port_ready {
            let err =
                "Engine encerrou antes de confirmar startup (sem engine_started e sem porta 5556)."
                    .to_string();
            append_runtime_bootstrap_log(
                &app,
                "engine",
                "spawn_engine",
                "error",
                json!({"reason": err, "subscribe_status": "missing"}),
            );
            return Err(err);
        }
    }

    let control_port_deadline = std::time::Instant::now() + Duration::from_secs(120);
    while !engine_control_port_listening() {
        if let Ok(Some(status)) = child.try_wait() {
            let err = format!("Engine encerrou antes de abrir porta 5556 (status: {status}).");
            append_runtime_bootstrap_log(
                &app,
                "engine",
                "spawn_engine",
                "error",
                json!({"reason": err}),
            );
            return Err(err);
        }
        if std::time::Instant::now() >= control_port_deadline {
            let err = "Engine não abriu porta de controle 5556 em até 120s.".to_string();
            append_runtime_bootstrap_log(
                &app,
                "engine",
                "spawn_engine",
                "error",
                json!({"reason": err}),
            );
            return Err(err);
        }
        std::thread::sleep(Duration::from_millis(250));
    }

    append_runtime_bootstrap_log(
        &app,
        "engine",
        "spawn_engine",
        "ok",
        json!({
            "pid": pid,
            "engine_log": engine_log_path,
            "subscribe_status": subscribe_status.map(|(st, sb)| json!({"subscribe_ticker_ret": st, "subscribe_offer_book_ret": sb})),
            "engine_stderr_log": engine_stderr_path.map(|p| p.to_string_lossy().to_string())
        }),
    );
    {
        let mut engine_guard = processes.engine.lock().map_err(|e| e.to_string())?;
        *engine_guard = Some(child);
    }
    maybe_resync_distributor_if_zmq(&app, &processes).await;
    Ok(())
}

/// Env do processo Tauri tem prioridade sobre `config.json` (útil em dev/CI).
fn env_nonempty(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

fn cfg_nonempty(value: &Option<String>) -> Option<String> {
    value
        .as_ref()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

fn resolve_engine_credentials(
    config: &AppConfig,
) -> (Option<String>, Option<String>, Option<String>) {
    let key = env_nonempty("PROFIT_ACTIVATION_KEY")
        .or_else(|| env_nonempty("PROFIT_DLL_ACTIVATION_KEY"))
        .or_else(|| cfg_nonempty(&config.profit_activation_key));

    let user = env_nonempty("PROFIT_USER")
        .or_else(|| env_nonempty("PROFIT_DLL_USER"))
        .or_else(|| cfg_nonempty(&config.profit_user));

    let pass = env_nonempty("PROFIT_PASSWORD")
        .or_else(|| env_nonempty("PROFIT_DLL_PASSWORD"))
        .or_else(|| cfg_nonempty(&config.profit_password));

    (key, user, pass)
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

fn apply_voice_env(cmd: &mut Command, config: &AppConfig) {
    let enabled = env_nonempty("VOICE_FUNCTIONS_ENABLED").or_else(|| {
        config
            .voice_functions_enabled
            .map(|v| if v { "1".to_string() } else { "0".to_string() })
    });
    if let Some(v) = enabled {
        cmd.env("VOICE_FUNCTIONS_ENABLED", v);
    }

    let api = env_nonempty("GOOGLE_API_KEY")
        .or_else(|| env_nonempty("GEMINI_API_KEY"))
        .or_else(|| {
            config
                .google_api_key
                .as_ref()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        });
    if let Some(v) = api {
        cmd.env("GOOGLE_API_KEY", v);
    }
}

#[tauri::command]
pub async fn spawn_distributor(
    app: tauri::AppHandle,
    processes: State<'_, ChildProcesses>,
) -> Result<(), String> {
    append_runtime_bootstrap_log(
        &app,
        "distributor",
        "spawn_distributor",
        "attempt",
        json!({}),
    );
    if check_health().await.unwrap_or(false) {
        let mode = fetch_health_ipc_mode().await;
        let has_required_routes = distributor_has_required_market_routes().await;
        if has_required_routes != Some(true) {
            append_runtime_bootstrap_log(
                &app,
                "distributor",
                "spawn_distributor",
                "healthy_missing_required_routes",
                json!({"ipc_mode": mode, "routes_ok": has_required_routes}),
            );
            {
                let mut dist_guard = processes.distributor.lock().map_err(|e| e.to_string())?;
                if let Some(mut child) = dist_guard.take() {
                    let _ = child.kill();
                }
            }
            kill_listeners_on_port_8000();
            tokio::time::sleep(Duration::from_millis(900)).await;
            for _ in 0u8..8 {
                if !check_health().await.unwrap_or(false) {
                    break;
                }
                kill_listeners_on_port_8000();
                tokio::time::sleep(Duration::from_millis(400)).await;
            }
            return start_distributor_child(app, &processes).await;
        }
        if mode.as_deref() == Some("shm") {
            append_runtime_bootstrap_log(
                &app,
                "distributor",
                "spawn_distributor",
                "already_healthy",
                json!({"ipc_mode": "shm"}),
            );
            return Ok(());
        }
        if mode.as_deref() == Some("zmq") {
            append_runtime_bootstrap_log(
                &app,
                "distributor",
                "spawn_distributor",
                "healthy_zmq_resync",
                json!({}),
            );
            maybe_resync_distributor_if_zmq(&app, &processes).await;
            return Ok(());
        }
        append_runtime_bootstrap_log(
            &app,
            "distributor",
            "spawn_distributor",
            "already_healthy",
            json!({"ipc_mode": mode}),
        );
        return Ok(());
    }

    start_distributor_child(app, &processes).await
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct DistributorIpcState {
    ipc_mode: Option<String>,
    ipc_fallback: Option<serde_json::Value>,
}

async fn emit_distributor_ipc_state_events(app: &tauri::AppHandle) -> Result<(), String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| e.to_string())?;
    let response = client
        .get(DISTRIBUTOR_IPC_STATE_URL)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let body: DistributorIpcState = response.json().await.map_err(|e| e.to_string())?;

    if let Some(mode) = body.ipc_mode {
        let _ = app.emit(
            "pq:ipc-transport",
            json!({"mode": mode, "reason": "distributor_state"}),
        );
    }
    if let Some(fallback) = body.ipc_fallback {
        let _ = app.emit("pq:ipc-fallback", fallback);
    }
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
    let (diag_key, diag_user, diag_pass) = resolve_engine_credentials(&config);
    let credentials_configured = diag_key.is_some() && diag_user.is_some() && diag_pass.is_some();

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
                            subscribe_ticker_ret = data
                                .get("subscribe_ticker_ret")
                                .and_then(|n| n.as_i64())
                                .map(|n| n as i32);
                            subscribe_offer_book_ret = data
                                .get("subscribe_offer_book_ret")
                                .and_then(|n| n.as_i64())
                                .map(|n| n as i32);
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

fn append_engine_spawn_marker(engine_log_path: &str, marker: &str) {
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(engine_log_path)
    {
        let _ = writeln!(
            f,
            "{{\"message\":\"tauri_spawn_marker\",\"data\":{{\"marker\":\"{}\",\"ts_ms\":{}}}}}",
            marker,
            unix_ts_ms()
        );
    }
}

fn read_engine_started_after_marker(
    engine_log_path: &str,
    marker: &str,
) -> Result<Option<(i32, i32)>, String> {
    let contents = std::fs::read_to_string(engine_log_path).map_err(|e| e.to_string())?;
    let mut marker_seen = false;
    for line in contents.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let Ok(v) = serde_json::from_str::<serde_json::Value>(line) else {
            continue;
        };
        if !marker_seen {
            let is_marker = v
                .get("message")
                .and_then(|m| m.as_str())
                .map(|m| m == "tauri_spawn_marker")
                .unwrap_or(false);
            let marker_match = v
                .get("data")
                .and_then(|d| d.get("marker"))
                .and_then(|m| m.as_str())
                .map(|m| m == marker)
                .unwrap_or(false);
            if is_marker && marker_match {
                marker_seen = true;
            }
            continue;
        }

        let is_engine_started = v
            .get("message")
            .and_then(|m| m.as_str())
            .map(|m| m == "engine_started")
            .unwrap_or(false);
        if !is_engine_started {
            continue;
        }
        let st = v
            .get("data")
            .and_then(|d| d.get("subscribe_ticker_ret"))
            .and_then(|n| n.as_i64())
            .map(|n| n as i32)
            .unwrap_or(-999999);
        let sb = v
            .get("data")
            .and_then(|d| d.get("subscribe_offer_book_ret"))
            .and_then(|n| n.as_i64())
            .map(|n| n as i32)
            .unwrap_or(-999999);
        return Ok(Some((st, sb)));
    }
    Ok(None)
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
    let exchange_upper = exchange.trim().to_uppercase();
    let normalized_exchange = if ticker == "TESTE" {
        "SIM".to_string()
    } else if exchange_upper.is_empty() || exchange_upper == "SIM" {
        "BMF".to_string()
    } else {
        exchange_upper
    };
    let bolsa_dll = exchange_to_bolsa_dll(&normalized_exchange).to_string();

    let mut config = read_config(app.clone()).await?;
    config.selected_ticker = Some(ticker.clone());
    config.selected_exchange = Some(normalized_exchange);
    write_config(app.clone(), config).await?;

    let cmd = format!("SWITCH\t{}\t{}\n", ticker, bolsa_dll);
    let addr = format!("127.0.0.1:{}", ENGINE_CONTROL_PORT)
        .parse()
        .map_err(|e: std::net::AddrParseError| e.to_string())?;
    match TcpStream::connect_timeout(
        &addr,
        Duration::from_millis(ENGINE_CONTROL_CONNECT_TIMEOUT_MS),
    ) {
        Ok(mut stream) => {
            stream
                .set_read_timeout(Some(Duration::from_millis(ENGINE_CONTROL_IO_TIMEOUT_MS)))
                .map_err(|e| e.to_string())?;
            stream
                .set_write_timeout(Some(Duration::from_millis(ENGINE_CONTROL_IO_TIMEOUT_MS)))
                .map_err(|e| e.to_string())?;
            stream.write_all(cmd.as_bytes()).map_err(|e| e.to_string())?;
            stream.flush().map_err(|e| e.to_string())?;

            let mut buf = [0u8; 256];
            let n = match stream.read(&mut buf) {
                Ok(n) => n,
                Err(e)
                    if e.kind() == std::io::ErrorKind::TimedOut
                        || e.kind() == std::io::ErrorKind::WouldBlock =>
                {
                    return Ok(SetActiveAssetResult {
                        success: false,
                        message: format!(
                            "Engine demorou para confirmar a troca de ativo (timeout {}s). Tente novamente em alguns segundos.",
                            ENGINE_CONTROL_IO_TIMEOUT_MS / 1000
                        ),
                    });
                }
                Err(e) => {
                    return Ok(SetActiveAssetResult {
                        success: false,
                        message: format!("Falha ao ler resposta do engine: {e}"),
                    });
                }
            };
            let response = String::from_utf8_lossy(&buf[..n]).trim().to_string();
            if response.is_empty() {
                return Ok(SetActiveAssetResult {
                    success: false,
                    message: "Engine encerrou a conexão sem resposta ao SWITCH. Tente novamente.".to_string(),
                });
            }

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

fn normalize_vp_period(period: &str) -> Result<String, String> {
    let s = period.trim().to_lowercase();
    match s.as_str() {
        "day" | "week" | "manual" => Ok(s),
        _ => Err(format!(
            "Periodo VP invalido: {period}. Use day, week ou manual."
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
pub async fn sync_ifr_series_to_distributor(
    series: String,
) -> Result<SetActiveAssetResult, String> {
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

/// Envia `VP_PERIOD\t<day|week|manual>\n` ao engine (porta 5556). Não grava config.
fn push_vp_period_to_engine(period: &str) -> Result<SetActiveAssetResult, String> {
    let cmd = format!("VP_PERIOD\t{period}\n");
    let addr = format!("127.0.0.1:{}", ENGINE_CONTROL_PORT)
        .parse()
        .map_err(|e: std::net::AddrParseError| e.to_string())?;
    match TcpStream::connect_timeout(
        &addr,
        Duration::from_millis(ENGINE_CONTROL_CONNECT_TIMEOUT_MS),
    ) {
        Ok(mut stream) => {
            stream
                .set_read_timeout(Some(Duration::from_millis(ENGINE_VP_PERIOD_IO_TIMEOUT_MS)))
                .map_err(|e| e.to_string())?;
            stream
                .set_write_timeout(Some(Duration::from_millis(ENGINE_VP_PERIOD_IO_TIMEOUT_MS)))
                .map_err(|e| e.to_string())?;
            stream.write_all(cmd.as_bytes()).map_err(|e| e.to_string())?;
            stream.flush().map_err(|e| e.to_string())?;
            let mut buf = [0u8; 256];
            let n = match stream.read(&mut buf) {
                Ok(n) => n,
                Err(e) => {
                    return Ok(SetActiveAssetResult {
                        success: true,
                        message: format!(
                            "Periodo VP {period} salvo; nao lemos resposta do engine ({e})."
                        ),
                    });
                }
            };
            let response = String::from_utf8_lossy(&buf[..n]).trim().to_string();
            if response.starts_with("OK") {
                Ok(SetActiveAssetResult {
                    success: true,
                    message: format!("Periodo VP {period} aplicado no engine."),
                })
            } else if response.is_empty() {
                Ok(SetActiveAssetResult {
                    success: true,
                    message: format!("Periodo VP {period} salvo; resposta vazia do engine."),
                })
            } else {
                Ok(SetActiveAssetResult {
                    success: true,
                    message: format!("Periodo VP {period} salvo; engine: {response}"),
                })
            }
        }
        Err(e) => Ok(SetActiveAssetResult {
            success: true,
            message: format!(
                "Periodo VP {period} salvo; engine nao aplicou ({}). Reinicie servicos se estiver a correr.",
                e
            ),
        }),
    }
}

#[tauri::command]
pub async fn set_vp_period(
    app: tauri::AppHandle,
    period: String,
) -> Result<SetActiveAssetResult, String> {
    let norm = normalize_vp_period(&period)?;
    let mut cfg = read_config(app.clone()).await?;
    cfg.vp_period = Some(norm.clone());
    write_config(app, cfg).await?;
    push_vp_period_to_engine(&norm)
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
    let (x, y, width, height) = state.map(|s| (s.x, s.y, s.width, s.height)).unwrap_or((
        100.0,
        100.0,
        default_width,
        default_height,
    ));

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

    window.on_window_event(move |event| match event {
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn normalize_ifr_series_accepts_aliases() {
        assert_eq!(normalize_ifr_series("42").unwrap(), "42r");
        assert_eq!(normalize_ifr_series("16R").unwrap(), "16r");
        assert_eq!(normalize_ifr_series(" 30 Min ").unwrap(), "30m");
    }

    #[test]
    fn normalize_ifr_series_rejects_invalid_value() {
        let err = normalize_ifr_series("15r").unwrap_err();
        assert!(err.contains("Série IFR inválida"));
    }

    #[test]
    fn normalize_vp_period_accepts_canonical_values() {
        assert_eq!(normalize_vp_period(" day ").unwrap(), "day");
        assert_eq!(normalize_vp_period("WEEK").unwrap(), "week");
        assert_eq!(normalize_vp_period("manual").unwrap(), "manual");
    }

    #[test]
    fn normalize_vp_period_rejects_invalid_value() {
        let err = normalize_vp_period("month").unwrap_err();
        assert!(err.contains("Periodo VP invalido"));
    }

    #[test]
    fn overlay_env_u32_filters_non_positive_values() {
        assert_eq!(overlay_env_u32(None), None);
        assert_eq!(overlay_env_u32(Some(0)), None);
        assert_eq!(overlay_env_u32(Some(12)), Some("12".to_string()));
    }

    #[test]
    fn monitor_scale_permille_handles_invalid_inputs() {
        assert_eq!(monitor_scale_permille(1.0), 1000);
        assert_eq!(monitor_scale_permille(1.25), 1250);
        assert_eq!(monitor_scale_permille(0.0), 1000);
        assert_eq!(monitor_scale_permille(f64::NAN), 1000);
    }

    #[test]
    fn exchange_to_bolsa_dll_normalizes_supported_values() {
        assert_eq!(exchange_to_bolsa_dll("bmf"), "F");
        assert_eq!(exchange_to_bolsa_dll("BOVESPA"), "B");
        assert_eq!(exchange_to_bolsa_dll("sim"), "SIM");
        assert_eq!(exchange_to_bolsa_dll("desconhecida"), "F");
    }

    #[test]
    fn widget_title_maps_known_ids() {
        assert_eq!(widget_title("macd"), "MACD 30min");
        assert_eq!(widget_title("ifr-30min"), "IFR 30min");
        assert_eq!(widget_title("custom-widget"), "custom-widget");
    }

    #[test]
    fn parse_config_contents_supports_bom_and_empty() {
        let cfg = parse_config_contents("\u{feff}  ").unwrap();
        assert_eq!(cfg.selected_ticker.as_deref(), Some("WINFUT"));
    }

    #[test]
    fn parse_config_contents_recovers_first_json_when_trailing_characters() {
        let cfg = parse_config_contents(r#"{"selected_ticker":"WDO"}{"selected_ticker":"WIN"}"#).unwrap();
        assert_eq!(cfg.selected_ticker.as_deref(), Some("WDO"));
    }

    #[test]
    fn parse_config_contents_reports_invalid_json() {
        let err = parse_config_contents(r#"{"selected_ticker":"WDO""#).unwrap_err();
        assert!(err.contains("config.json inválido ou corrompido"));
    }

    #[test]
    fn set_active_asset_result_serializes_expected_payload() {
        let payload = SetActiveAssetResult {
            success: true,
            message: "ok".to_string(),
        };
        let value = serde_json::to_value(payload).unwrap();
        assert_eq!(value["success"], true);
        assert_eq!(value["message"], "ok");
    }

    #[test]
    fn distributor_ipc_state_deserializes_event_payload() {
        let body = r#"{"ipc_mode":"zmq","ipc_fallback":{"reason":"timeout","active":true}}"#;
        let parsed: DistributorIpcState = serde_json::from_str(body).unwrap();
        assert_eq!(parsed.ipc_mode.as_deref(), Some("zmq"));
        assert_eq!(parsed.ipc_fallback.unwrap()["reason"], "timeout");
    }

    #[test]
    fn maybe_map_ocr_stderr_maps_known_error_signatures() {
        let unique = format!(
            "pq-ocr-test-{}-{}.log",
            std::process::id(),
            unix_ts_ms()
        );
        let path = std::env::temp_dir().join(unique);
        std::fs::write(&path, "TesseractNotFoundError: missing binary").unwrap();
        let mapped = maybe_map_ocr_stderr(&Some(PathBuf::from(&path)));
        let _ = std::fs::remove_file(&path);
        assert_eq!(mapped, Some(tesseract_missing_message()));
    }
}
