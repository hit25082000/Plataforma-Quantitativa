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
            }
        });
}
