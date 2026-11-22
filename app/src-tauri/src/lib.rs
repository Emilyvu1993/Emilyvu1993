pub mod commands;
pub mod config_store;
pub mod error;
pub mod fs_atomic;
pub mod model;
pub mod service;
pub mod sidecar;
pub mod workspace;

use service::AppCore;
use sidecar::{Sidecar, SidecarSpec};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(AppCore::new(Sidecar::new(SidecarSpec::resolve())))
        .invoke_handler(tauri::generate_handler![
            commands::last_workspace_path,
            commands::open_workspace,
            commands::get_workspace,
            commands::add_files,
            commands::remove_file,
            commands::set_active_file,
            commands::save_draft,
            commands::bind_config,
            commands::list_configs,
            commands::save_config,
            commands::delete_config,
            commands::inspect_file,
            commands::match_pattern,
            commands::validate_config,
            commands::convert,
            commands::save_output,
            commands::discard_preview,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
