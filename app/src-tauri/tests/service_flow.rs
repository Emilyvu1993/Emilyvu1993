//! End-to-end flow through AppCore + real Python sidecar (no GUI).
//! Covers: upload many / one active, success -> preview top 3 -> save,
//! failure keeps old output + config, stale-preview guard, busy guard.
use std::path::Path;
use std::process::Command;
use std::time::Duration;

use app_lib::service::AppCore;
use app_lib::sidecar::{Sidecar, SidecarSpec};
use serde_json::{json, Value};

const T: Duration = Duration::from_secs(60);

fn make_pdf(path: &Path, rows: usize) {
    let py = SidecarSpec::dev().program;
    let code = format!(
        r#"
from reportlab.platypus import SimpleDocTemplate, Table
data=[["Date","Description","Amount"]]+[[f"0{{i}}/01/2026",f"Item {{i}}",f"{{i*100:,}}.00"] for i in range(1,{rows}+1)]
SimpleDocTemplate(r"{p}").build([Table(data)])
"#,
        p = path.display()
    );
    let ok = Command::new(py).arg("-c").arg(code).status().expect("python").success();
    assert!(ok, "fixture generation failed (pip install -r sidecar/requirements-dev.txt)");
}

fn cfg() -> Value {
    json!({
        "name": "Ledger",
        "extraction": {"type": "table", "header_row": 0},
        "fields": [
            {"source": "Description", "target": "desc"},
            {"source": "Amount", "target": "amount", "transform": "number"}
        ],
        "template": {"record": "- {{ desc }}: {{ amount }}"},
        "output": {"mode": "single_file"}
    })
}

#[tokio::test]
async fn full_flow() {
    let src = tempfile::tempdir().unwrap();
    let root = tempfile::tempdir().unwrap();
    let a = src.path().join("ledger-a.pdf");
    let b = src.path().join("ledger-b.pdf");
    make_pdf(&a, 5);
    make_pdf(&b, 2);

    let core = AppCore::new(Sidecar::new(SidecarSpec::dev()));
    core.open_workspace(root.path()).unwrap();
    let (rep, ws) = core
        .add_files(&[a.to_string_lossy().into(), b.to_string_lossy().into()])
        .unwrap();
    assert_eq!(rep.added.len(), 2);
    let fa = rep.added[0].clone();
    assert_eq!(ws.active_file_id.as_deref(), Some(fa.as_str()));

    // inspect drives the editor
    let ins = core.inspect(&fa).await.unwrap();
    assert_eq!(ins["tables"][0]["columns"], json!(["Date", "Description", "Amount"]));

    // --- success: preview top 3, nothing in output/ yet
    let saved_cfg = core.save_config(cfg()).unwrap();
    let cfgv = serde_json::to_value(&saved_cfg).unwrap();
    let out = core.convert(&fa, cfgv.clone(), T).await.unwrap();
    assert_eq!(out.result["record_count"], 5);
    assert_eq!(out.result["preview"].as_array().unwrap().len(), 3);
    assert_eq!(std::fs::read_dir(root.path().join("output")).unwrap().count(), 0);

    // --- stale guard: config edited after preview
    let mut edited = cfgv.clone();
    edited["template"]["record"] = json!("* {{ desc }}");
    assert_eq!(core.save_output(&out.job_id, &edited).unwrap_err().code, "STALE_PREVIEW");

    // --- convert again and save
    let out = core.convert(&fa, cfgv.clone(), T).await.unwrap();
    let s = core.save_output(&out.job_id, &cfgv).unwrap();
    let v1 = std::fs::read_to_string(&s.output_path).unwrap();
    assert_eq!(v1.lines().count(), 5);
    assert_eq!(s.file.bound_config_id.as_deref(), Some(saved_cfg.id.as_str()));

    // --- failure: broken template -> error, old output byte-identical, config kept as draft
    let mut broken = cfgv.clone();
    broken["template"]["record"] = json!("{{ desc }} {{ nope }}");
    let e = core.convert(&fa, broken.clone(), T).await.unwrap_err();
    assert_eq!(e.code, "TEMPLATE_RENDER");
    assert_eq!(std::fs::read_to_string(&s.output_path).unwrap(), v1);
    let ws = core.workspace().unwrap();
    let f = ws.files.iter().find(|f| f.id == fa).unwrap();
    assert_eq!(f.draft_config.as_ref().unwrap()["template"]["record"], broken["template"]["record"]);
    assert_eq!(f.last_error.as_ref().unwrap().code, "TEMPLATE_RENDER");
    assert_eq!(f.last_output_path.as_deref().map(|p| root.path().join(p)), Some(s.output_path.clone().into()));
    assert_eq!(std::fs::read_dir(root.path().join(".tmp")).unwrap().count(), 0);

    // --- second save keeps a .bak of the previous output
    let mut v2cfg = cfgv.clone();
    v2cfg["template"]["record"] = json!("* {{ desc }}");
    let out = core.convert(&fa, v2cfg.clone(), T).await.unwrap();
    let s2 = core.save_output(&out.job_id, &v2cfg).unwrap();
    assert_eq!(std::fs::read_to_string(s2.backup_path.unwrap()).unwrap(), v1);

    // --- switching file works when idle; config survives reopen
    core.set_active_file(&rep.added[1]).unwrap();
    let core2 = AppCore::new(Sidecar::new(SidecarSpec::dev()));
    let ws = core2.open_workspace(root.path()).unwrap();
    assert_eq!(ws.active_file_id.as_deref(), Some(rep.added[1].as_str()));
    assert_eq!(core2.list_configs().unwrap().len(), 1);
}

#[tokio::test]
async fn busy_blocks_switch_and_second_convert() {
    let src = tempfile::tempdir().unwrap();
    let root = tempfile::tempdir().unwrap();
    let a = src.path().join("a.pdf");
    std::fs::write(&a, b"%PDF-1.7 fake").unwrap();
    // sidecar that never answers -> conversion stays in flight
    let core = std::sync::Arc::new(AppCore::new(Sidecar::new(SidecarSpec {
        program: "sleep".into(),
        args: vec!["30".into()],
        env: vec![],
    })));
    core.open_workspace(root.path()).unwrap();
    let (rep, _) = core.add_files(&[a.to_string_lossy().into()]).unwrap();
    let id = rep.added[0].clone();

    let c2 = core.clone();
    let id2 = id.clone();
    let h = tokio::spawn(async move { c2.convert(&id2, cfg(), Duration::from_millis(800)).await });
    tokio::time::sleep(Duration::from_millis(200)).await;
    assert!(core.is_busy());
    assert_eq!(core.set_active_file(&id).unwrap_err().code, "BUSY");
    assert_eq!(core.convert(&id, cfg(), T).await.unwrap_err().code, "BUSY");
    assert_eq!(h.await.unwrap().unwrap_err().code, "TIMEOUT");
    assert!(!core.is_busy());
    // draft was persisted before the sidecar ran
    let ws = core.workspace().unwrap();
    assert_eq!(ws.files[0].draft_config.as_ref().unwrap()["name"], "Ledger");
}

fn make_text_pdf(path: &Path) {
    let py = SidecarSpec::dev().program;
    let code = format!(
        r#"
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, PageBreak
h=ParagraphStyle("h",fontName="Helvetica-Bold",fontSize=16,leading=20,spaceBefore=8,spaceAfter=6)
p=ParagraphStyle("p",fontName="Helvetica",fontSize=10,leading=13,spaceAfter=8)
def page(c,d): c.setFont("Helvetica",8); c.drawString(50,810,"Running header"); c.drawCentredString(298,25,f"Page {{d.page}}")
body="Plain prose about the topic. "*8
story=[Paragraph("1. Overview",h),Paragraph(body,p),Paragraph("2. Details",h),Paragraph(body,p),PageBreak(),
       Paragraph("3. Findings",h),Paragraph(body,p),Paragraph("4. Summary",h),Paragraph(body,p)]
SimpleDocTemplate(r"{p}",pagesize=A4,topMargin=70,bottomMargin=60).build(story,onFirstPage=page,onLaterPages=page)
"#,
        p = path.display()
    );
    assert!(Command::new(py).arg("-c").arg(code).status().unwrap().success());
}

#[tokio::test]
async fn text_document_sections_flow() {
    let src = tempfile::tempdir().unwrap();
    let root = tempfile::tempdir().unwrap();
    let pdf = src.path().join("notes.pdf");
    make_text_pdf(&pdf);

    let core = AppCore::new(Sidecar::new(SidecarSpec::dev()));
    core.open_workspace(root.path()).unwrap();
    let (rep, _) = core.add_files(&[pdf.to_string_lossy().into()]).unwrap();
    let id = rep.added[0].clone();

    // no tables in a prose PDF -> table rule fails cleanly, sections works
    let rule = json!({"type": "sections", "heading_mode": "font"});
    let o = core.outline(&id, rule.clone()).await.unwrap();
    assert_eq!(o["total"], 4);
    assert_eq!(o["headings"][0]["title"], "1. Overview");

    let cfg = json!({"name": "Prose", "extraction": rule, "fields": [],
                     "template": {"record": "{{ markdown }}\n"}, "output": {"mode": "single_file"}});
    let out = core.convert(&id, cfg.clone(), T).await.unwrap();
    assert_eq!(out.result["record_count"], 4);
    let prev = out.result["preview"].as_array().unwrap();
    assert_eq!(prev.len(), 3);
    assert_eq!(prev[2]["title"], "3. Findings");
    let s = core.save_output(&out.job_id, &cfg).unwrap();
    let md = std::fs::read_to_string(&s.output_path).unwrap();
    assert!(md.starts_with("# 1. Overview\n\nPlain prose"));
    assert!(!md.contains("Running header") && !md.contains("Page 2"));

    // heading detection that matches nothing: actionable error, saved file untouched
    let mut bad = cfg.clone();
    bad["extraction"] = json!({"type": "sections", "bold_headings": false, "size_ratio": 3.0});
    let e = core.convert(&id, bad, T).await.unwrap_err();
    assert_eq!(e.code, "NO_RECORDS_FOUND");
    assert_eq!(e.detail.as_ref().unwrap()["body_font_size"], 10.0);
    assert_eq!(std::fs::read_to_string(&s.output_path).unwrap(), md);
}
