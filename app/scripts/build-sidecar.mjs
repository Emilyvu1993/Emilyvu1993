// Freeze the Python sidecar with PyInstaller and place it where Tauri's externalBin expects it
// (binaries/pdf2md-<target-triple>[.exe]). Run on each target OS: PyInstaller does not cross-compile.
import { execSync } from "node:child_process";
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const win = process.platform === "win32";
const py = process.env.PYTHON ?? (existsSync(join(root, win ? ".venv/Scripts/python.exe" : ".venv/bin/python"))
  ? join(root, win ? ".venv/Scripts/python.exe" : ".venv/bin/python") : "python3");
const triple = execSync("rustc -vV").toString().match(/host: (\S+)/)[1];

execSync(`"${py}" -m PyInstaller --onefile --clean --name pdf2md --paths sidecar --distpath sidecar/dist --workpath sidecar/build --specpath sidecar/build sidecar/pdf2md/__main__.py`,
  { cwd: root, stdio: "inherit" });

const out = join(root, "app/src-tauri/binaries");
mkdirSync(out, { recursive: true });
const ext = win ? ".exe" : "";
copyFileSync(join(root, `sidecar/dist/pdf2md${ext}`), join(out, `pdf2md-${triple}${ext}`));
console.log(`sidecar -> binaries/pdf2md-${triple}${ext}`);
