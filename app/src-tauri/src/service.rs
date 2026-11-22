//! AppCore: orchestration of workspace, configs, sidecar and staged jobs.
//! Tauri-independent so it can be tested headless.
//!
//! Invariants
//! - A failed conversion never touches output/ and never discards the user's config
//!   (the draft is persisted *before* the sidecar runs).
//! - Save promotes only a staged job whose config hash equals the current config (no stale save).
//! - Only one conversion runs at a time; switching the active file is blocked meanwhile.
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use chrono::Utc;
use serde::Serialize;
use serde_json::{json, Value};

use crate::config_store::ConfigStore;
use crate::error::{codes, AppError, AppResult};
use crate::fs_atomic;
use crate::model::*;
use crate::sidecar::Sidecar;
use crate::workspace::{AddReport, WorkspaceStore};

pub const CONVERT_TIMEOUT: Duration = Duration::from_secs(120);
const INSPECT_TIMEOUT: Duration = Duration::from_secs(60);

struct Job {
    file_id: String,
    config_hash: String,
    staging: PathBuf,
    per_record: bool,
}

#[derive(Debug, Serialize)]
pub struct ConvertOutcome {
    pub job_id: String,
    pub config_hash: String,
    pub result: Value,
}

#[derive(Debug, Serialize)]
pub struct SaveOutcome {
    pub output_path: String,
    pub backup_path: Option<String>,
    pub file: WorkspaceFile,
}

pub struct AppCore {
    ws: Mutex<Option<WorkspaceStore>>,
    jobs: Mutex<HashMap<String, Job>>,
    busy: AtomicBool,
    sidecar: Sidecar,
}

struct BusyGuard<'a>(&'a AtomicBool);
impl Drop for BusyGuard<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::SeqCst);
    }
}

fn no_ws() -> AppError {
    AppError::new(codes::NO_WORKSPACE, "Open or create a workspace first")
}

impl AppCore {
    pub fn new(sidecar: Sidecar) -> Self {
        Self { ws: Mutex::new(None), jobs: Mutex::new(HashMap::new()), busy: AtomicBool::new(false), sidecar }
    }

    fn with_ws<T>(&self, f: impl FnOnce(&mut WorkspaceStore) -> AppResult<T>) -> AppResult<T> {
        let mut g = self.ws.lock().unwrap();
        f(g.as_mut().ok_or_else(no_ws)?)
    }
    fn root(&self) -> AppResult<PathBuf> {
        self.with_ws(|s| Ok(s.root.clone()))
    }
    fn configs(&self) -> AppResult<ConfigStore> {
        Ok(ConfigStore::new(&self.root()?))
    }
    pub fn is_busy(&self) -> bool {
        self.busy.load(Ordering::SeqCst)
    }

    // ---------- workspace ----------
    pub fn open_workspace(&self, path: &Path) -> AppResult<Workspace> {
        if self.is_busy() {
            return Err(AppError::new(codes::BUSY, "A conversion is running"));
        }
        let s = WorkspaceStore::open(path)?;
        let ws = s.ws.clone();
        *self.ws.lock().unwrap() = Some(s);
        self.jobs.lock().unwrap().clear();
        Ok(ws)
    }
    pub fn workspace(&self) -> AppResult<Workspace> {
        self.with_ws(|s| Ok(s.ws.clone()))
    }
    pub fn add_files(&self, paths: &[String]) -> AppResult<(AddReport, Workspace)> {
        self.with_ws(|s| Ok((s.add_files(paths)?, s.ws.clone())))
    }
    pub fn remove_file(&self, id: &str) -> AppResult<Workspace> {
        if self.is_busy() {
            return Err(AppError::new(codes::BUSY, "A conversion is running"));
        }
        self.discard_jobs_for(id);
        self.with_ws(|s| {
            s.remove_file(id)?;
            Ok(s.ws.clone())
        })
    }
    pub fn set_active_file(&self, id: &str) -> AppResult<Workspace> {
        if self.is_busy() {
            return Err(AppError::new(codes::BUSY, "Wait for the running conversion to finish before switching files"));
        }
        self.with_ws(|s| {
            s.set_active(id)?;
            Ok(s.ws.clone())
        })
    }
    pub fn save_draft(&self, file_id: &str, draft: Value) -> AppResult<()> {
        self.with_ws(|s| {
            s.file_mut(file_id)?.draft_config = Some(draft);
            s.persist()
        })
    }
    pub fn bind_config(&self, file_id: &str, config_id: Option<String>) -> AppResult<WorkspaceFile> {
        self.with_ws(|s| {
            let f = s.file_mut(file_id)?;
            f.bound_config_id = config_id;
            let out = f.clone();
            s.persist()?;
            Ok(out)
        })
    }

    // ---------- configs ----------
    pub fn list_configs(&self) -> AppResult<Vec<OutputConfig>> {
        self.configs()?.list()
    }
    pub fn save_config(&self, cfg: Value) -> AppResult<OutputConfig> {
        self.configs()?.save(cfg)
    }
    pub fn delete_config(&self, id: &str) -> AppResult<()> {
        self.configs()?.delete(id)?;
        self.with_ws(|s| {
            for f in s.ws.files.iter_mut().filter(|f| f.bound_config_id.as_deref() == Some(id)) {
                f.bound_config_id = None;
            }
            s.persist()
        })
    }

    // ---------- sidecar-backed ----------
    fn pdf_abs(&self, file_id: &str) -> AppResult<String> {
        self.with_ws(|s| Ok(s.abs(&s.file(file_id)?.pdf_path).to_string_lossy().into_owned()))
    }
    pub async fn inspect(&self, file_id: &str) -> AppResult<Value> {
        let p = self.pdf_abs(file_id)?;
        self.sidecar.call("inspect", json!({ "pdf_path": p }), INSPECT_TIMEOUT).await
    }
    pub async fn match_pattern(&self, file_id: &str, pattern: &str, pages: Option<String>) -> AppResult<Value> {
        let p = self.pdf_abs(file_id)?;
        self.sidecar
            .call("match_pattern", json!({ "pdf_path": p, "pattern": pattern, "pages": pages }), INSPECT_TIMEOUT)
            .await
    }
    pub async fn outline(&self, file_id: &str, rule: Value) -> AppResult<Value> {
        let p = self.pdf_abs(file_id)?;
        self.sidecar.call("outline", json!({ "pdf_path": p, "rule": rule }), INSPECT_TIMEOUT).await
    }
    pub async fn validate_config(&self, cfg: Value) -> AppResult<Value> {
        self.sidecar.call("validate_config", json!({ "config": cfg }), INSPECT_TIMEOUT).await
    }

    pub async fn convert(&self, file_id: &str, config: Value, timeout: Duration) -> AppResult<ConvertOutcome> {
        if self.busy.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst).is_err() {
            return Err(AppError::new(codes::BUSY, "A conversion is already running"));
        }
        let _guard = BusyGuard(&self.busy);

        // 1) persist the user's config first: whatever happens next, it is not lost
        self.save_draft(file_id, config.clone())?;

        let per_record = config.pointer("/output/mode").and_then(Value::as_str) == Some("file_per_record");
        let job_id = uuid::Uuid::new_v4().to_string();
        let root = self.root()?;
        let staging = root.join(".tmp").join(if per_record { job_id.clone() } else { format!("{job_id}.md") });
        let pdf = self.pdf_abs(file_id)?;

        let res = self
            .sidecar
            .call(
                "convert",
                json!({ "pdf_path": pdf, "config": config, "out_tmp_path": staging.to_string_lossy(), "preview_n": 3 }),
                timeout,
            )
            .await;

        match res {
            Ok(result) => {
                let config_hash = config_hash(&config);
                self.discard_jobs_for(file_id); // one staged preview per file
                self.jobs.lock().unwrap().insert(
                    job_id.clone(),
                    Job { file_id: file_id.into(), config_hash: config_hash.clone(), staging, per_record },
                );
                Ok(ConvertOutcome { job_id, config_hash, result })
            }
            Err(e) => {
                let _ = fs_atomic::remove_any(&staging);
                self.with_ws(|s| {
                    let f = s.file_mut(file_id)?;
                    f.status = FileStatus::Failed;
                    f.last_error = Some(LastError { code: e.code.clone(), message: e.message.clone(), at: Utc::now() });
                    s.persist()
                })?;
                Err(e)
            }
        }
    }

    pub fn save_output(&self, job_id: &str, current_config: &Value) -> AppResult<SaveOutcome> {
        let job = self
            .jobs
            .lock()
            .unwrap()
            .remove(job_id)
            .ok_or_else(|| AppError::new(codes::JOB_NOT_FOUND, "Preview expired. Convert again."))?;
        if config_hash(current_config) != job.config_hash {
            let _ = fs_atomic::remove_any(&job.staging);
            return Err(AppError::new(
                codes::STALE_PREVIEW,
                "Config changed after the preview. Convert again before saving.",
            ));
        }
        self.with_ws(|s| {
            let f = s.file(&job.file_id)?.clone();
            let rel = s.output_rel_path(&f, job.per_record);
            let dest = s.abs(&rel);
            let bak = fs_atomic::promote(&job.staging, &dest, true)?;
            let cfg_id = current_config.get("id").and_then(Value::as_str).map(String::from);
            let fm = s.file_mut(&job.file_id)?;
            fm.status = FileStatus::Converted;
            fm.last_output_path = Some(rel);
            fm.last_error = None;
            if cfg_id.is_some() {
                fm.bound_config_id = cfg_id;
            }
            let file = fm.clone();
            s.persist()?;
            Ok(SaveOutcome {
                output_path: dest.to_string_lossy().into_owned(),
                backup_path: bak.map(|b| b.to_string_lossy().into_owned()),
                file,
            })
        })
    }

    pub fn discard_preview(&self, job_id: &str) {
        if let Some(j) = self.jobs.lock().unwrap().remove(job_id) {
            let _ = fs_atomic::remove_any(&j.staging);
        }
    }

    fn discard_jobs_for(&self, file_id: &str) {
        let mut jobs = self.jobs.lock().unwrap();
        let ids: Vec<String> = jobs.iter().filter(|(_, j)| j.file_id == file_id).map(|(k, _)| k.clone()).collect();
        for k in ids {
            if let Some(j) = jobs.remove(&k) {
                let _ = fs_atomic::remove_any(&j.staging);
            }
        }
    }
}
