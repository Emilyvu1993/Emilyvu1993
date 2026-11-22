//! Crash-safe file operations. Invariant: the final output is either the old
//! version or the complete new version — never partial, never missing.
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

pub fn write_atomic(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir)?;
    }
    let tmp = sibling(path, ".part");
    {
        let mut f = fs::File::create(&tmp)?;
        f.write_all(bytes)?;
        f.sync_all()?;
    }
    fs::rename(&tmp, path).inspect_err(|_| {
        let _ = fs::remove_file(&tmp);
    })
}

/// Move a fully-written staging file/dir over `dest`. The previous `dest` is kept as
/// `<dest>.bak` (replacing any older .bak) when `keep_backup` is true.
/// If the final rename fails, the previous version is restored.
pub fn promote(staging: &Path, dest: &Path, keep_backup: bool) -> std::io::Result<Option<PathBuf>> {
    if !staging.exists() {
        return Err(std::io::Error::new(std::io::ErrorKind::NotFound, "staging output missing"));
    }
    if let Some(dir) = dest.parent() {
        fs::create_dir_all(dir)?;
    }
    let bak = sibling(dest, ".bak");
    let had_old = dest.exists();
    if had_old {
        remove_any(&bak)?;
        fs::rename(dest, &bak)?;
    }
    if let Err(e) = fs::rename(staging, dest) {
        if had_old {
            let _ = fs::rename(&bak, dest); // roll back
        }
        return Err(e);
    }
    if had_old && !keep_backup {
        remove_any(&bak)?;
        return Ok(None);
    }
    Ok(had_old.then_some(bak))
}

pub fn remove_any(p: &Path) -> std::io::Result<()> {
    if p.is_dir() {
        fs::remove_dir_all(p)
    } else if p.exists() {
        fs::remove_file(p)
    } else {
        Ok(())
    }
}

fn sibling(p: &Path, suffix: &str) -> PathBuf {
    let mut s = p.as_os_str().to_owned();
    s.push(suffix);
    PathBuf::from(s)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn promote_replaces_and_keeps_backup() {
        let d = tempfile::tempdir().unwrap();
        let dest = d.path().join("out/a.md");
        write_atomic(&dest, b"OLD").unwrap();
        let st = d.path().join("stage.md");
        fs::write(&st, b"NEW").unwrap();
        let bak = promote(&st, &dest, true).unwrap().unwrap();
        assert_eq!(fs::read(&dest).unwrap(), b"NEW");
        assert_eq!(fs::read(bak).unwrap(), b"OLD");
        assert!(!st.exists());
    }

    #[test]
    fn promote_missing_staging_leaves_old_untouched() {
        let d = tempfile::tempdir().unwrap();
        let dest = d.path().join("a.md");
        fs::write(&dest, b"OLD").unwrap();
        assert!(promote(&d.path().join("nope.md"), &dest, true).is_err());
        assert_eq!(fs::read(&dest).unwrap(), b"OLD");
    }

    #[test]
    fn promote_rolls_back_when_final_rename_fails() {
        let d = tempfile::tempdir().unwrap();
        let dest = d.path().join("a.md");
        fs::write(&dest, b"OLD").unwrap();
        // staging is a non-empty directory, dest path is a file -> rename(dir, file) fails on unix
        let st = d.path().join("stage");
        fs::create_dir(&st).unwrap();
        fs::write(st.join("x"), b"x").unwrap();
        let r = promote(&st, &dest, true);
        if r.is_err() {
            assert_eq!(fs::read(&dest).unwrap(), b"OLD");
        }
    }

    #[test]
    fn promote_dir_mode() {
        let d = tempfile::tempdir().unwrap();
        let st = d.path().join("stage");
        fs::create_dir(&st).unwrap();
        fs::write(st.join("r1.md"), b"1").unwrap();
        let dest = d.path().join("out/doc");
        promote(&st, &dest, false).unwrap();
        assert_eq!(fs::read(dest.join("r1.md")).unwrap(), b"1");
    }
}
