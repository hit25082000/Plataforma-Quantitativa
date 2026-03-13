use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;
use tauri::Manager;
use tauri::State;

const HEALTH_URL: &str = "http://127.0.0.1:8000/health";
const HEALTH_TIMEOUT_SECS: u64 = 30;
const POLL_INTERVAL_MS: u64 = 500;

#[derive(Default)]
pub struct ChildProcesses {
    pub engine: Mutex<Option<Child>>,
    pub distributor: Mutex<Option<Child>>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AppConfig {
    pub profit_activation_key: Option<String>,
    pub profit_user: Option<String>,
    pub profit_password: Option<String>,
    pub notifications_enabled: Option<bool>,
    pub sounds_enabled: Option<bool>,
    pub volume: Option<u8>,
    pub minimize_to_tray: Option<bool>,
    pub start_with_windows: Option<bool>,
    pub selected_ticker: Option<String>,
    pub selected_exchange: Option<String>,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            profit_activation_key: None,
            profit_user: None,
            profit_password: None,
            notifications_enabled: Some(true),
            sounds_enabled: Some(true),
            volume: Some(80),
            minimize_to_tray: Some(true),
            start_with_windows: Some(false),
            selected_ticker: Some("WINFUT".to_string()),
            selected_exchange: Some("BMF".to_string()),
        }
    }
}

const ENGINE_CONTROL_PORT: u16 = 5556;

fn get_resources_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .resource_dir()
        .map_err(|e| format!("{e}"))
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
    Ok(config_dir.join("config.json").to_string_lossy().to_string())
}

#[tauri::command]
pub async fn read_config(app: tauri::AppHandle) -> Result<AppConfig, String> {
    let path_str = get_config_path(app).await?;
    let path = PathBuf::from(&path_str);
    if !path.exists() {
        return Ok(AppConfig::default());
    }
    let contents = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    let config: AppConfig = serde_json::from_str(&contents).unwrap_or_default();
    Ok(config)
}

#[tauri::command]
pub async fn write_config(app: tauri::AppHandle, config: AppConfig) -> Result<(), String> {
    let path_str = get_config_path(app).await?;
    let path = PathBuf::from(&path_str);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let contents = serde_json::to_string_pretty(&config).map_err(|e| e.to_string())?;
    std::fs::write(&path, contents).map_err(|e| e.to_string())?;
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

#[cfg(target_os = "windows")]
fn kill_stale_processes() {
    let _ = Command::new("taskkill")
        .args(["/F", "/IM", "engine.exe"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
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

    let config: AppConfig = read_config(app.clone()).await.unwrap_or_default();

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
    if engine_guard.is_some() {
        return Err("Engine já está em execução".to_string());
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

    let mut cmd = Command::new(&engine_exe);
    cmd.current_dir(&engine_dir)
        .stdout(Stdio::null())
        .stderr(stderr_cfg)
        .env("DEBUG_LOG_PATH", &engine_log_path);

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

    let child = cmd.spawn().map_err(|e| e.to_string())?;
    *engine_guard = Some(child);
    Ok(())
}

#[tauri::command]
pub async fn spawn_distributor(
    app: tauri::AppHandle,
    processes: State<'_, ChildProcesses>,
) -> Result<(), String> {
    let mut dist_guard = processes.distributor.lock().map_err(|e| e.to_string())?;
    if dist_guard.is_some() {
        return Err("Distributor já está em execução".to_string());
    }

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

    let child = Command::new(&dist_exe)
        .current_dir(&dist_dir)
        .stdout(Stdio::null())
        .stderr(dist_stderr)
        .spawn()
        .map_err(|e| e.to_string())?;

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
    let config: AppConfig = read_config(app.clone()).await.unwrap_or_default();
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
                "Subscribe retornou códigos de erro: Ticker={}, OfferBook={}. 0=OK; -2147483646=NL_NOT_INITIALIZED (Market não pronto).",
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

/// Maps display exchange name to Profit DLL bolsa code (UI/config).
fn exchange_to_bolsa(exchange: &str) -> &str {
    match exchange.to_uppercase().as_str() {
        "BMF" => "F",
        "BOVESPA" => "B",
        "SIM" => "SIM", // Mock asset
        _ => "F",
    }
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

    let mut config: AppConfig = read_config(app.clone()).await.unwrap_or_default();
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
    Ok(())
}
