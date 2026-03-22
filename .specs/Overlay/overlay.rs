// app/src-tauri/src/commands/overlay.rs
//
// Comandos Tauri para criar/destruir a janela de overlay transparente.
// A janela é:
//   - Transparente (background RGBA)
//   - Sempre no topo (always_on_top)
//   - Sem decorações (sem barra de título)
//   - Click-through (ignore_cursor_events)
//   - Tela cheia

use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};

/// Abre (ou torna visível) a janela de overlay do gráfico de profit.
#[tauri::command]
pub async fn open_profit_overlay(app: AppHandle) -> Result<(), String> {
    // Se a janela já existe, apenas exibe
    if let Some(win) = app.get_webview_window("profit-overlay") {
        win.show().map_err(|e| e.to_string())?;
        win.set_always_on_top(true).map_err(|e| e.to_string())?;
        return Ok(());
    }

    // Obtém dimensões do monitor principal
    let (screen_w, screen_h) = {
        let monitor = app
            .primary_monitor()
            .map_err(|e| e.to_string())?
            .ok_or("Monitor principal não encontrado")?;
        let size = monitor.size();
        (size.width as f64, size.height as f64)
    };

    let window = WebviewWindowBuilder::new(
        &app,
        "profit-overlay",
        WebviewUrl::App("overlay".into()), // rota /#/overlay no frontend
    )
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

    // Click-through: eventos de mouse passam para a janela abaixo
    window
        .set_ignore_cursor_events(true)
        .map_err(|e| e.to_string())?;

    Ok(())
}

/// Fecha (oculta) a janela de overlay.
#[tauri::command]
pub async fn close_profit_overlay(app: AppHandle) -> Result<(), String> {
    if let Some(win) = app.get_webview_window("profit-overlay") {
        win.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Atualiza as posições alvo (repassa para o serviço OCR via HTTP).
/// Alternativa ao WS direto do frontend — útil para chamada via menu.
#[tauri::command]
pub async fn set_overlay_positions(positions: Vec<f64>) -> Result<(), String> {
    let client = reqwest::Client::new();
    let body = serde_json::json!({ "positions": positions });
    client
        .post("http://127.0.0.1:5558/positions")
        .json(&body)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    Ok(())
}
