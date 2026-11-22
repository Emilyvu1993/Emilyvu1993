//! Thin Tauri IPC layer over AppCore. All errors serialize as AppError {code,message,detail}.
use std::path::PathBuf;

use serde_json::Value;
use tauri::{AppHandle, Manager, State};

use crate::error::{AppError, AppResult};
use crate::model::{OutputConfig, Workspace, WorkspaceFile};
use crate::service::{AppCore, ConvertOutcome, SaveOutcome, CONVERT_TIMEOUT};
use crate::workspace::AddReport;

type Core<'a> = State<'a, AppCore>;

fn settings_path(app: &AppHandle) -> Option<PathBuf> {
    app.path().app_config_dir().ok().map(|d| d.join("settings.json"))
}

#[tauri::command]
pub fn last_workspace_path(app: AppHandle) -> Option<String> {
    let p = settings_path(&app)?;
    let v: Value = serde_json::from_slice(&std::fs::read(p).ok()?).ok()?;
    v.get("last_workspace").and_then(Value::as_str).map(String::from)
}

#[tauri::command]
pub fn open_workspace(app: AppHandle, core: Core, path: String) -> AppResult<Workspace> {
    let ws = core.open_workspace(&PathBuf::from(&path))?;
    if let Some(p) = settings_path(&app) {
        let _ = crate::fs_atomic::write_atomic(&p, serde_json::json!({ "last_workspace": path }).to_string().as_bytes());
    }
    Ok(ws)
}

#[tauri::command]
pub fn get_workspace(core: Core) -> AppResult<Workspace> {
    core.workspace()
}

#[derive(serde::Serialize)]
pub struct AddFilesResponse {
    report: AddReport,
    workspace: Workspace,
}

#[tauri::command]
pub fn add_files(core: Core, paths: Vec<String>) -> AppResult<AddFilesResponse> {
    let (report, workspace) = core.add_files(&paths)?;
    Ok(AddFilesResponse { report, workspace })
}

#[tauri::command]
pub fn remove_file(core: Core, file_id: String) -> AppResult<Workspace> {
    core.remove_file(&file_id)
}

#[tauri::command]
pub fn set_active_file(core: Core, file_id: String) -> AppResult<Workspace> {
    core.set_active_file(&file_id)
}

#[tauri::command]
pub fn save_draft(core: Core, file_id: String, draft: Value) -> AppResult<()> {
    core.save_draft(&file_id, draft)
}

#[tauri::command]
pub fn bind_config(core: Core, file_id: String, config_id: Option<String>) -> AppResult<WorkspaceFile> {
    core.bind_config(&file_id, config_id)
}

#[tauri::command]
pub fn list_configs(core: Core) -> AppResult<Vec<OutputConfig>> {
    core.list_configs()
}

#[tauri::command]
pub fn save_config(core: Core, config: Value) -> AppResult<OutputConfig> {
    core.save_config(config)
}

#[tauri::command]
pub fn delete_config(core: Core, config_id: String) -> AppResult<()> {
    core.delete_config(&config_id)
}

#[tauri::command]
pub async fn inspect_file(core: Core<'_>, file_id: String) -> AppResult<Value> {
    core.inspect(&file_id).await
}

#[tauri::command]
pub async fn match_pattern(core: Core<'_>, file_id: String, pattern: String, pages: Option<String>) -> AppResult<Value> {
    core.match_pattern(&file_id, &pattern, pages).await
}

#[tauri::command]
pub async fn validate_config(core: Core<'_>, config: Value) -> AppResult<Value> {
    core.validate_config(config).await
}

#[tauri::command]
pub async fn convert(core: Core<'_>, file_id: String, config: Value) -> AppResult<ConvertOutcome> {
    core.convert(&file_id, config, CONVERT_TIMEOUT).await
}

#[tauri::command]
pub fn save_output(core: Core, job_id: String, config: Value) -> AppResult<SaveOutcome> {
    core.save_output(&job_id, &config)
}

#[tauri::command]
pub fn discard_preview(core: Core, job_id: String) {
    core.discard_preview(&job_id)
}

#[allow(dead_code)]
fn _assert_error_serializable(e: AppError) -> Value {
    serde_json::to_value(e).unwrap()
}
