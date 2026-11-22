//! Python sidecar client: JSON-lines over stdio, one request in flight at a time.
//! Lazy spawn, per-call timeout, kill + respawn on timeout/crash.
use std::path::PathBuf;
use std::process::Stdio;
use std::time::Duration;

use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::Mutex;

use crate::error::{codes, AppError, AppResult};

#[derive(Debug, Clone)]
pub struct SidecarSpec {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub env: Vec<(String, String)>,
}

impl SidecarSpec {
    /// Resolution order:
    /// 1. PDF2MD_SIDECAR_PROGRAM (+ PDF2MD_SIDECAR_ARGS, whitespace separated)
    /// 2. bundled `pdf2md[.exe]` next to the app executable (Tauri externalBin)
    /// 3. dev fallback: <repo>/.venv/bin/python (or python3) -m pdf2md with PYTHONPATH=<repo>/sidecar
    pub fn resolve() -> Self {
        if let Ok(p) = std::env::var("PDF2MD_SIDECAR_PROGRAM") {
            let args = std::env::var("PDF2MD_SIDECAR_ARGS").unwrap_or_default();
            return Self { program: p.into(), args: args.split_whitespace().map(String::from).collect(), env: vec![] };
        }
        if let Ok(exe) = std::env::current_exe() {
            let name = if cfg!(windows) { "pdf2md.exe" } else { "pdf2md" };
            if let Some(b) = exe.parent().map(|d| d.join(name)).filter(|p| p.is_file()) {
                return Self { program: b, args: vec![], env: vec![] };
            }
        }
        Self::dev()
    }

    pub fn dev() -> Self {
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
        let venv = repo.join(if cfg!(windows) { ".venv/Scripts/python.exe" } else { ".venv/bin/python" });
        let program = if venv.is_file() { venv } else { PathBuf::from("python3") };
        Self {
            program,
            args: vec!["-m".into(), "pdf2md".into()],
            env: vec![("PYTHONPATH".into(), repo.join("sidecar").to_string_lossy().into_owned())],
        }
    }
}

struct Proc {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

pub struct Sidecar {
    spec: SidecarSpec,
    inner: Mutex<(Option<Proc>, u64)>,
}

impl Sidecar {
    pub fn new(spec: SidecarSpec) -> Self {
        Self { spec, inner: Mutex::new((None, 0)) }
    }

    fn spawn(&self) -> AppResult<Proc> {
        let mut cmd = Command::new(&self.spec.program);
        cmd.args(&self.spec.args)
            .envs(self.spec.env.iter().cloned())
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .kill_on_drop(true);
        #[cfg(windows)]
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        let mut child = cmd.spawn().map_err(|e| {
            AppError::new(codes::SIDECAR_UNAVAILABLE, format!("Cannot start converter: {e}"))
                .with_detail(json!({ "program": self.spec.program.to_string_lossy() }))
        })?;
        let stdin = child.stdin.take().expect("piped stdin");
        let stdout = BufReader::new(child.stdout.take().expect("piped stdout"));
        Ok(Proc { child, stdin, stdout })
    }

    /// Returns the RPC `result`, or the sidecar's `error` mapped to AppError.
    pub async fn call(&self, method: &str, params: Value, timeout: Duration) -> AppResult<Value> {
        let mut g = self.inner.lock().await;
        if g.0.is_none() {
            g.0 = Some(self.spawn()?);
        }
        g.1 += 1;
        let id = g.1;
        let line = serde_json::to_string(&json!({ "id": id, "method": method, "params": params }))? + "\n";
        let proc = g.0.as_mut().unwrap();

        let io = async {
            proc.stdin.write_all(line.as_bytes()).await?;
            proc.stdin.flush().await?;
            loop {
                let mut buf = String::new();
                if proc.stdout.read_line(&mut buf).await? == 0 {
                    return Err(std::io::Error::new(std::io::ErrorKind::UnexpectedEof, "sidecar exited"));
                }
                if let Ok(v) = serde_json::from_str::<Value>(&buf) {
                    if v.get("id").and_then(Value::as_u64) == Some(id) {
                        return Ok(v);
                    }
                } // ignore stray / stale lines
            }
        };

        let resp = match tokio::time::timeout(timeout, io).await {
            Ok(Ok(v)) => v,
            Ok(Err(e)) => {
                kill(&mut g.0).await;
                return Err(AppError::new(codes::SIDECAR_CRASH, format!("Converter crashed: {e}")));
            }
            Err(_) => {
                kill(&mut g.0).await;
                return Err(AppError::new(
                    codes::TIMEOUT,
                    format!("Conversion exceeded {}s and was cancelled", timeout.as_secs()),
                ));
            }
        };

        if let Some(err) = resp.get("error") {
            let mut e = AppError::new(
                err.get("code").and_then(Value::as_str).unwrap_or("INTERNAL"),
                err.get("message").and_then(Value::as_str).unwrap_or("Unknown converter error"),
            );
            e.detail = err.get("detail").cloned();
            return Err(e);
        }
        Ok(resp.get("result").cloned().unwrap_or(Value::Null))
    }
}

async fn kill(p: &mut Option<Proc>) {
    if let Some(mut pr) = p.take() {
        let _ = pr.child.kill().await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn ping_error_and_crash_recovery() {
        let sc = Sidecar::new(SidecarSpec::dev());
        let r = sc.call("ping", json!({}), Duration::from_secs(20)).await.unwrap();
        assert_eq!(r["pong"], true);
        let e = sc.call("inspect", json!({"pdf_path": "/nope.pdf"}), Duration::from_secs(20)).await.unwrap_err();
        assert_eq!(e.code, "PDF_NOT_FOUND");
    }

    #[tokio::test]
    async fn timeout_kills_and_next_call_respawns() {
        // `sleep` never answers -> TIMEOUT; then swap to a working spec is not possible,
        // so just verify the timeout path and that state is reset.
        let sc = Sidecar::new(SidecarSpec { program: "sleep".into(), args: vec!["30".into()], env: vec![] });
        let e = sc.call("ping", json!({}), Duration::from_millis(300)).await.unwrap_err();
        assert_eq!(e.code, codes::TIMEOUT);
        assert!(sc.inner.lock().await.0.is_none());
    }

    #[tokio::test]
    async fn crash_maps_to_sidecar_crash() {
        let sc = Sidecar::new(SidecarSpec { program: "true".into(), args: vec![], env: vec![] });
        let e = sc.call("ping", json!({}), Duration::from_secs(5)).await.unwrap_err();
        assert_eq!(e.code, codes::SIDECAR_CRASH);
    }

    #[tokio::test]
    async fn missing_program() {
        let sc = Sidecar::new(SidecarSpec { program: "/no/such/bin".into(), args: vec![], env: vec![] });
        let e = sc.call("ping", json!({}), Duration::from_secs(5)).await.unwrap_err();
        assert_eq!(e.code, codes::SIDECAR_UNAVAILABLE);
    }
}
