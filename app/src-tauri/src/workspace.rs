//! Workspace store: workspace.json + pdfs/ + output/ + .tmp/ under one root folder.
use std::fs;
use std::path::{Path, PathBuf};

use chrono::Utc;
use sha2::{Digest, Sha256};

use crate::error::{codes, AppError, AppResult};
use crate::fs_atomic::write_atomic;
use crate::model::*;

/// Hard upload limit (2 MiB). Checked via metadata BEFORE reading the file.
pub const MAX_PDF_BYTES: u64 = 2 * 1024 * 1024;

pub struct WorkspaceStore {
    pub root: PathBuf,
    pub ws: Workspace,
}

#[derive(Debug, serde::Serialize)]
pub struct AddReport {
    pub added: Vec<String>,
    pub skipped_duplicates: Vec<String>,
    pub rejected: Vec<AppError>,
}

impl WorkspaceStore {
    pub fn open(root: &Path) -> AppResult<Self> {
        for d in ["pdfs", "configs", "output", ".tmp"] {
            fs::create_dir_all(root.join(d))?;
        }
        // staging from a previous session is never trusted
        clear_dir(&root.join(".tmp"))?;
        let meta = root.join("workspace.json");
        let mut ws = if meta.exists() {
            serde_json::from_slice::<Workspace>(&fs::read(&meta)?)?
        } else {
            Workspace {
                schema_version: WORKSPACE_SCHEMA_VERSION,
                id: uuid::Uuid::new_v4().to_string(),
                name: root.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_else(|| "Workspace".into()),
                root_path: String::new(),
                files: vec![],
                active_file_id: None,
            }
        };
        ws.root_path = root.to_string_lossy().into_owned();
        let s = Self { root: root.to_path_buf(), ws };
        s.persist()?;
        Ok(s)
    }

    pub fn persist(&self) -> AppResult<()> {
        write_atomic(&self.root.join("workspace.json"), &serde_json::to_vec_pretty(&self.ws)?)?;
        Ok(())
    }

    pub fn file(&self, id: &str) -> AppResult<&WorkspaceFile> {
        self.ws.files.iter().find(|f| f.id == id).ok_or_else(|| not_found(id))
    }
    pub fn file_mut(&mut self, id: &str) -> AppResult<&mut WorkspaceFile> {
        self.ws.files.iter_mut().find(|f| f.id == id).ok_or_else(|| not_found(id))
    }
    pub fn abs(&self, rel: &str) -> PathBuf {
        self.root.join(rel)
    }

    pub fn add_files(&mut self, paths: &[String]) -> AppResult<AddReport> {
        let mut rep = AddReport { added: vec![], skipped_duplicates: vec![], rejected: vec![] };
        for p in paths {
            let src = Path::new(p);
            match self.add_one(src) {
                Ok(Some(id)) => rep.added.push(id),
                Ok(None) => rep.skipped_duplicates.push(p.clone()),
                Err(e) => rep.rejected.push(e.with_detail(serde_json::json!({ "path": p }))),
            }
        }
        if self.ws.active_file_id.is_none() {
            self.ws.active_file_id = rep.added.first().cloned();
        }
        self.persist()?;
        Ok(rep)
    }

    fn add_one(&mut self, src: &Path) -> AppResult<Option<String>> {
        let shown = src.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_else(|| src.display().to_string());
        // 1) format by extension (cheap, before touching the file)
        if !src.extension().is_some_and(|e| e.eq_ignore_ascii_case("pdf")) {
            return Err(AppError::new(codes::NOT_A_PDF, format!("{shown}: only .pdf files are accepted")));
        }
        // 2) size gate from metadata: oversized files are never read into memory
        let meta = fs::metadata(src)?;
        if !meta.is_file() {
            return Err(AppError::new(codes::NOT_A_PDF, format!("{shown}: not a file")));
        }
        if meta.len() > MAX_PDF_BYTES {
            return Err(AppError::new(
                codes::FILE_TOO_LARGE,
                format!("{shown}: {:.2} MB exceeds the 2 MB limit", meta.len() as f64 / 1_048_576.0),
            )
            .with_detail(serde_json::json!({ "size_bytes": meta.len(), "max_bytes": MAX_PDF_BYTES })));
        }
        let bytes = fs::read(src)?;
        // 3) content must really be a PDF (a renamed .pdf is rejected)
        if !bytes.starts_with(b"%PDF-") {
            return Err(AppError::new(codes::NOT_A_PDF, format!("{shown}: content is not a PDF")));
        }
        let sha = hex::encode(Sha256::digest(&bytes));
        if self.ws.files.iter().any(|f| f.sha256 == sha) {
            return Ok(None);
        }
        let id = uuid::Uuid::new_v4().to_string();
        let rel = format!("pdfs/{id}.pdf");
        write_atomic(&self.abs(&rel), &bytes)?;
        self.ws.files.push(WorkspaceFile {
            id: id.clone(),
            name: src.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_else(|| id.clone()),
            pdf_path: rel,
            sha256: sha,
            size_bytes: bytes.len() as u64,
            added_at: Utc::now(),
            status: FileStatus::New,
            last_output_path: None,
            last_error: None,
            bound_config_id: None,
            draft_config: None,
        });
        Ok(Some(id))
    }

    pub fn remove_file(&mut self, id: &str) -> AppResult<()> {
        let f = self.file(id)?.clone();
        let _ = fs::remove_file(self.abs(&f.pdf_path));
        self.ws.files.retain(|x| x.id != id);
        if self.ws.active_file_id.as_deref() == Some(id) {
            self.ws.active_file_id = self.ws.files.first().map(|f| f.id.clone());
        }
        self.persist()
    }

    pub fn set_active(&mut self, id: &str) -> AppResult<()> {
        self.file(id)?;
        self.ws.active_file_id = Some(id.to_string());
        self.persist()
    }

    /// Output name derived from the original filename, made unique per file id.
    pub fn output_rel_path(&self, f: &WorkspaceFile, per_record: bool) -> String {
        let stem = Path::new(&f.name).file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
        let safe: String = stem.chars().map(|c| if c.is_alphanumeric() || "-_ .".contains(c) { c } else { '_' }).collect();
        let short = &f.id[..8];
        if per_record {
            format!("output/{safe}-{short}")
        } else {
            format!("output/{safe}-{short}.md")
        }
    }
}

fn not_found(id: &str) -> AppError {
    AppError::new(codes::FILE_NOT_IN_WORKSPACE, format!("File {id} is not in this workspace"))
}

fn clear_dir(d: &Path) -> std::io::Result<()> {
    for e in fs::read_dir(d)? {
        crate::fs_atomic::remove_any(&e?.path())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn pdf(dir: &Path, name: &str, body: &str) -> String {
        let p = dir.join(name);
        fs::write(&p, format!("%PDF-1.7\n{body}")).unwrap();
        p.to_string_lossy().into_owned()
    }

    #[test]
    fn add_dedupe_active_remove_roundtrip() {
        let src = tempfile::tempdir().unwrap();
        let root = tempfile::tempdir().unwrap();
        let a = pdf(src.path(), "a.pdf", "a");
        let b = pdf(src.path(), "b.pdf", "b");
        let dup = pdf(src.path(), "a-copy.pdf", "a");
        let txt = src.path().join("x.txt");
        fs::write(&txt, "hello").unwrap();

        let mut s = WorkspaceStore::open(root.path()).unwrap();
        let r = s.add_files(&[a, b, dup.clone(), txt.to_string_lossy().into()]).unwrap();
        assert_eq!(r.added.len(), 2);
        assert_eq!(r.skipped_duplicates, vec![dup]);
        assert_eq!(r.rejected[0].code, codes::NOT_A_PDF);
        assert!(r.rejected[0].message.contains("only .pdf"));
        assert_eq!(s.ws.active_file_id.as_deref(), Some(r.added[0].as_str()));

        s.set_active(&r.added[1]).unwrap();
        drop(s);
        let mut s = WorkspaceStore::open(root.path()).unwrap();
        assert_eq!(s.ws.files.len(), 2);
        assert_eq!(s.ws.active_file_id.as_deref(), Some(r.added[1].as_str()));

        s.remove_file(&r.added[1]).unwrap();
        assert_eq!(s.ws.active_file_id.as_deref(), Some(r.added[0].as_str()));
        assert!(s.set_active("missing").is_err());
    }

    #[test]
    fn rejects_wrong_extension_fake_pdf_and_oversize_but_keeps_valid() {
        let src = tempfile::tempdir().unwrap();
        let root = tempfile::tempdir().unwrap();
        let ok = pdf(src.path(), "ok.pdf", "ok");
        // exactly at the limit is accepted
        let at_limit = src.path().join("limit.PDF");
        let mut body = b"%PDF-1.7\n".to_vec();
        body.resize(MAX_PDF_BYTES as usize, b'x');
        fs::write(&at_limit, &body).unwrap();
        // one byte over is rejected
        let big = src.path().join("big.pdf");
        body.push(b'x');
        fs::write(&big, &body).unwrap();
        let docx = src.path().join("a.docx");
        fs::write(&docx, "%PDF-1.7 but wrong extension").unwrap();
        let fake = src.path().join("fake.pdf");
        fs::write(&fake, "just text").unwrap();
        let dir = src.path().join("folder.pdf");
        fs::create_dir(&dir).unwrap();
        let s = |p: &Path| p.to_string_lossy().into_owned();

        let mut st = WorkspaceStore::open(root.path()).unwrap();
        let r = st.add_files(&[ok, s(&at_limit), s(&big), s(&docx), s(&fake), s(&dir)]).unwrap();
        assert_eq!(r.added.len(), 2, "valid files in the same batch still added");
        let codes_: Vec<_> = r.rejected.iter().map(|e| e.code.as_str()).collect();
        assert_eq!(codes_, vec![codes::FILE_TOO_LARGE, codes::NOT_A_PDF, codes::NOT_A_PDF, codes::NOT_A_PDF]);
        assert!(r.rejected[0].message.contains("exceeds the 2 MB limit"));
        // rejected files leave nothing behind
        assert_eq!(fs::read_dir(root.path().join("pdfs")).unwrap().count(), 2);
        assert_eq!(st.ws.files.len(), 2);
    }

    #[test]
    fn open_clears_stale_staging() {
        let root = tempfile::tempdir().unwrap();
        fs::create_dir_all(root.path().join(".tmp")).unwrap();
        fs::write(root.path().join(".tmp/old.md"), "x").unwrap();
        WorkspaceStore::open(root.path()).unwrap();
        assert_eq!(fs::read_dir(root.path().join(".tmp")).unwrap().count(), 0);
    }
}
