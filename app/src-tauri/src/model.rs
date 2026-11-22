//! Persisted domain model. Mirrors app/src/types/domain.ts.
//! Extraction/fields/template/output are kept as JSON values: the sidecar owns
//! their validation (single source of truth for the rule schema).
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const WORKSPACE_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum FileStatus {
    New,
    Converted,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LastError {
    pub code: String,
    pub message: String,
    pub at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkspaceFile {
    pub id: String,
    pub name: String,
    /// Relative to workspace root (pdfs/<id>.pdf)
    pub pdf_path: String,
    pub sha256: String,
    pub size_bytes: u64,
    pub added_at: DateTime<Utc>,
    pub status: FileStatus,
    #[serde(default)]
    pub last_output_path: Option<String>,
    #[serde(default)]
    pub last_error: Option<LastError>,
    #[serde(default)]
    pub bound_config_id: Option<String>,
    /// Unsaved editor state; survives failures, file switches and restarts.
    #[serde(default)]
    pub draft_config: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Workspace {
    pub schema_version: u32,
    pub id: String,
    pub name: String,
    #[serde(skip)]
    pub root_path: String,
    pub files: Vec<WorkspaceFile>,
    #[serde(default)]
    pub active_file_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutputConfig {
    pub id: String,
    pub name: String,
    #[serde(default = "one")]
    pub version: u32,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub extraction: Value,
    #[serde(default)]
    pub fields: Value,
    pub template: Value,
    #[serde(default)]
    pub output: Value,
}

fn one() -> u32 {
    1
}

/// The part of a config that affects conversion output (used for the stale-preview hash).
pub fn conversion_payload(c: &Value) -> Value {
    serde_json::json!({
        "extraction": c.get("extraction").cloned().unwrap_or(Value::Null),
        "fields": c.get("fields").cloned().unwrap_or(Value::Null),
        "template": c.get("template").cloned().unwrap_or(Value::Null),
        "output": c.get("output").cloned().unwrap_or(Value::Null),
    })
}

/// Canonical hash: serde_json::Map is a BTreeMap (sorted keys) without `preserve_order`.
pub fn config_hash(c: &Value) -> String {
    use sha2::{Digest, Sha256};
    let bytes = serde_json::to_vec(&conversion_payload(c)).expect("serialize");
    hex::encode(Sha256::digest(bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn hash_ignores_metadata_and_key_order() {
        let a = json!({"name":"A","extraction":{"type":"table","header_row":0},"template":{"record":"x"}});
        let b = json!({"template":{"record":"x"},"extraction":{"header_row":0,"type":"table"},"name":"B","id":"z"});
        assert_eq!(config_hash(&a), config_hash(&b));
        let c = json!({"extraction":{"type":"table","header_row":1},"template":{"record":"x"}});
        assert_ne!(config_hash(&a), config_hash(&c));
    }
}
