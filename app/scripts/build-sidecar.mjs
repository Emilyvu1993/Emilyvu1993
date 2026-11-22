// Freeze the Python sidecar with PyInstaller and place it where Tauri's externalBin expects it
// (binaries/pdf2md-<target-triple>[.exe]). Run on each target OS: PyInstaller does not cross-compile.
import { execSync } from "node:child_process";
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const win = process.platform === "win32";
const venvPy = join(root, win ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const py = process.env.PYTHON ?? (existsSync(venvPy) ? venvPy : win ? "python" : "python3");
const triple = execSync("rustc -vV").toString().match(/host: (\S+)/)[1];

// The entry is run_pdf2md.py (absolute import); pdf2md/__main__.py cannot be a frozen entry point.
const flags = [
  "--onefile", "--clean", "--name pdf2md", "--paths sidecar",
  "--collect-data pdfminer",                 // CMap/encoding tables used for non-Latin fonts
  "--distpath sidecar/dist", "--workpath sidecar/build", "--specpath sidecar/build",
].join(" ");
execSync(`"${py}" -m PyInstaller ${flags} sidecar/run_pdf2md.py`, { cwd: root, stdio: "inherit" });

const out = join(root, "app/src-tauri/binaries");
mkdirSync(out, { recursive: true });
const ext = win ? ".exe" : "";
copyFileSync(join(root, `sidecar/dist/pdf2md${ext}`), join(out, `pdf2md-${triple}${ext}`));
console.log(`sidecar -> binaries/pdf2md-${triple}${ext}`);
