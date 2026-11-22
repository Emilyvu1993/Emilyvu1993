//! Saved output configs: configs/<id>.json, reusable across files in the workspace.
use std::fs;
use std::path::{Path, PathBuf};

use chrono::Utc;
use serde_json::Value;

use crate::error::{codes, AppError, AppResult};
use crate::fs_atomic::write_atomic;
use crate::model::OutputConfig;

pub struct ConfigStore {
    dir: PathBuf,
}

impl ConfigStore {
    pub fn new(root: &Path) -> Self {
        Self { dir: root.join("configs") }
    }

    fn path(&self, id: &str) -> AppResult<PathBuf> {
        if id.is_empty() || !id.chars().all(|c| c.is_ascii_alphanumeric() || c == '-') {
            return Err(AppError::new(codes::CONFIG_NOT_FOUND, format!("Invalid config id '{id}'")));
        }
        Ok(self.dir.join(format!("{id}.json")))
    }

    pub fn list(&self) -> AppResult<Vec<OutputConfig>> {
        let mut out = vec![];
        for e in fs::read_dir(&self.dir)? {
            let p = e?.path();
            if p.extension().is_some_and(|x| x == "json") {
                // a corrupt config must not hide the others
                if let Ok(c) = serde_json::from_slice::<OutputConfig>(&fs::read(&p)?) {
                    out.push(c);
                }
            }
        }
        out.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));
        Ok(out)
    }

    pub fn get(&self, id: &str) -> AppResult<OutputConfig> {
        let p = self.path(id)?;
        if !p.exists() {
            return Err(AppError::new(codes::CONFIG_NOT_FOUND, format!("Config {id} not found")));
        }
        Ok(serde_json::from_slice(&fs::read(p)?)?)
    }

    /// Upsert. `id` absent -> create (as-new also used for "duplicate").
    pub fn save(&self, mut v: Value) -> AppResult<OutputConfig> {
        let now = Utc::now();
        let existing = v.get("id").and_then(|x| x.as_str()).and_then(|id| self.get(id).ok());
        let obj = v.as_object_mut().ok_or_else(|| AppError::new(codes::IO_ERROR, "config must be an object"))?;
        match &existing {
            Some(old) => {
                obj.insert("created_at".into(), serde_json::to_value(old.created_at)?);
                obj.insert("version".into(), (old.version + 1).into());
            }
            None => {
                obj.insert("id".into(), uuid::Uuid::new_v4().to_string().into());
                obj.insert("created_at".into(), serde_json::to_value(now)?);
                obj.insert("version".into(), 1.into());
            }
        }
        obj.insert("updated_at".into(), serde_json::to_value(now)?);
        obj.entry("name").or_insert_with(|| "Untitled config".into());
        let cfg: OutputConfig = serde_json::from_value(v)?;
        write_atomic(&self.path(&cfg.id)?, &serde_json::to_vec_pretty(&cfg)?)?;
        Ok(cfg)
    }

    pub fn delete(&self, id: &str) -> AppResult<()> {
        let p = self.path(id)?;
        if p.exists() {
            fs::remove_file(p)?;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn save_get_update_list_delete() {
        let d = tempfile::tempdir().unwrap();
        fs::create_dir_all(d.path().join("configs")).unwrap();
        let s = ConfigStore::new(d.path());
        let c = s.save(json!({"name":"Bank","extraction":{"type":"table"},"template":{"record":"x"}})).unwrap();
        assert_eq!(c.version, 1);
        let mut v = serde_json::to_value(&c).unwrap();
        v["template"] = json!({"record":"y"});
        let c2 = s.save(v).unwrap();
        assert_eq!((c2.id.clone(), c2.version, c2.created_at), (c.id.clone(), 2, c.created_at));
        fs::write(d.path().join("configs/broken.json"), "{").unwrap();
        assert_eq!(s.list().unwrap().len(), 1);
        assert!(s.get("../etc/passwd").is_err());
        s.delete(&c.id).unwrap();
        assert_eq!(s.get(&c.id).unwrap_err().code, codes::CONFIG_NOT_FOUND);
    }
}
