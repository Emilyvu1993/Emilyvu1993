//! AppError: the single error shape crossing the IPC boundary.
//! `code` values are stable and shared with the Python sidecar (pdf2md/errors.py).
use serde::Serialize;
use serde_json::Value;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct AppError {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<Value>,
}

impl AppError {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self { code: code.into(), message: message.into(), detail: None }
    }
    pub fn with_detail(mut self, detail: Value) -> Self {
        self.detail = Some(detail);
        self
    }
}

impl std::fmt::Display for AppError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}
impl std::error::Error for AppError {}

impl From<std::io::Error> for AppError {
    fn from(e: std::io::Error) -> Self {
        AppError::new(codes::IO_ERROR, e.to_string())
    }
}
impl From<serde_json::Error> for AppError {
    fn from(e: serde_json::Error) -> Self {
        AppError::new(codes::IO_ERROR, format!("JSON: {e}"))
    }
}

pub type AppResult<T> = Result<T, AppError>;

pub mod codes {
    // Rust-side codes (sidecar codes pass through unchanged)
    pub const IO_ERROR: &str = "IO_ERROR";
    pub const NO_WORKSPACE: &str = "NO_WORKSPACE";
    pub const FILE_NOT_IN_WORKSPACE: &str = "FILE_NOT_IN_WORKSPACE";
    pub const NOT_A_PDF: &str = "NOT_A_PDF";
    pub const FILE_TOO_LARGE: &str = "FILE_TOO_LARGE";
    pub const CONFIG_NOT_FOUND: &str = "CONFIG_NOT_FOUND";
    pub const BUSY: &str = "BUSY";
    pub const JOB_NOT_FOUND: &str = "JOB_NOT_FOUND";
    pub const STALE_PREVIEW: &str = "STALE_PREVIEW";
    pub const TIMEOUT: &str = "TIMEOUT";
    pub const SIDECAR_CRASH: &str = "SIDECAR_CRASH";
    pub const SIDECAR_UNAVAILABLE: &str = "SIDECAR_UNAVAILABLE";
}
