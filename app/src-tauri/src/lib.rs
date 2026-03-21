#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;

mod commands;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .manage(commands::ChildProcesses::default())
        .invoke_handler(tauri::generate_handler![
            commands::spawn_engine,
            commands::spawn_distributor,
            commands::kill_services,
            commands::check_health,
            commands::get_config_path,
            commands::read_config,
            commands::write_config,
            commands::get_resource_path,
            commands::get_profit_diagnostic,
            commands::set_active_asset,
            commands::open_log_folder,
            commands::create_widget_window,
            commands::open_profit_overlay,
            commands::close_profit_overlay,
            commands::set_overlay_positions,
        ])
        .setup(|app| {
            #[cfg(debug_assertions)]
            {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.open_devtools();
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                // Persistir posição/tamanho dos widgets antes de fechar
                let handle = app_handle.clone();
                tauri::async_runtime::block_on(async move {
                    let _ = commands::persist_widget_windows(handle).await;
                });
                // Kill engine
                if let Ok(mut engine) = app_handle.state::<commands::ChildProcesses>().engine.lock() {
                    if let Some(mut child) = engine.take() {
                        let _ = child.kill();
                    }
                }
                // Kill distributor
                if let Ok(mut dist) = app_handle.state::<commands::ChildProcesses>().distributor.lock() {
                    if let Some(mut child) = dist.take() {
                        let _ = child.kill();
                    }
                }
                if let Ok(mut ocr) = app_handle.state::<commands::ChildProcesses>().profit_ocr.lock() {
                    if let Some(mut child) = ocr.take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
