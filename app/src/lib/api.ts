// Typed IPC wrappers. Outside Tauri (browser dev / UI tests) a mock backend is used.
import type {
  AddReport, AppError, ConvertOutcome, InspectResult, MatchResult, OutlineResult, OutputConfig,
  ExtractionRule, OutputConfigDraft, SaveOutcome, Workspace, WorkspaceFile,
} from "../types/domain";

type Invoke = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

export const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let invokeImpl: Invoke | null = null;
async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!invokeImpl) {
    if (inTauri) {
      const core = await import("@tauri-apps/api/core");
      invokeImpl = core.invoke as Invoke;
    } else {
      const { mockInvoke } = await import("./mockBackend");
      invokeImpl = mockInvoke as Invoke;
    }
  }
  try {
    return await invokeImpl<T>(cmd, args);
  } catch (e) {
    throw toAppError(e);
  }
}

export function toAppError(e: unknown): AppError {
  if (e && typeof e === "object" && "code" in e && "message" in e) return e as AppError;
  return { code: "INTERNAL", message: e instanceof Error ? e.message : String(e) };
}

export const api = {
  lastWorkspacePath: () => invoke<string | null>("last_workspace_path"),
  openWorkspace: (path: string) => invoke<Workspace>("open_workspace", { path }),
  getWorkspace: () => invoke<Workspace>("get_workspace"),
  addFiles: (paths: string[]) => invoke<{ report: AddReport; workspace: Workspace }>("add_files", { paths }),
  removeFile: (fileId: string) => invoke<Workspace>("remove_file", { fileId }),
  setActiveFile: (fileId: string) => invoke<Workspace>("set_active_file", { fileId }),
  saveDraft: (fileId: string, draft: OutputConfigDraft) => invoke<void>("save_draft", { fileId, draft }),
  bindConfig: (fileId: string, configId: string | null) => invoke<WorkspaceFile>("bind_config", { fileId, configId }),
  listConfigs: () => invoke<OutputConfig[]>("list_configs"),
  saveConfig: (config: OutputConfigDraft) => invoke<OutputConfig>("save_config", { config }),
  deleteConfig: (configId: string) => invoke<void>("delete_config", { configId }),
  inspectFile: (fileId: string) => invoke<InspectResult>("inspect_file", { fileId }),
  matchPattern: (fileId: string, pattern: string, pages?: string) =>
    invoke<MatchResult>("match_pattern", { fileId, pattern, pages: pages || null }),
  outline: (fileId: string, rule: ExtractionRule) => invoke<OutlineResult>("outline_file", { fileId, rule }),
  validateConfig: (config: OutputConfigDraft) => invoke<{ valid: true }>("validate_config", { config }),
  convert: (fileId: string, config: OutputConfigDraft) => invoke<ConvertOutcome>("convert", { fileId, config }),
  saveOutput: (jobId: string, config: OutputConfigDraft) => invoke<SaveOutcome>("save_output", { jobId, config }),
  discardPreview: (jobId: string) => invoke<void>("discard_preview", { jobId }),
};

/** Native pickers (Tauri) — in the browser mock they return canned paths. */
export async function pickWorkspaceDir(): Promise<string | null> {
  if (!inTauri) return "/mock/workspace";
  const { open } = await import("@tauri-apps/plugin-dialog");
  const r = await open({ directory: true, multiple: false, title: "Choose workspace folder" });
  return typeof r === "string" ? r : null;
}

export async function pickPdfs(): Promise<string[]> {
  if (!inTauri) return ["/mock/bank-statement-oct.pdf", "/mock/invoices-q3.pdf", "/mock/scanned-receipt.pdf", "/mock/annual-report.pdf"];
  const { open } = await import("@tauri-apps/plugin-dialog");
  const r = await open({ multiple: true, title: "Add PDF files", filters: [{ name: "PDF", extensions: ["pdf"] }] });
  return Array.isArray(r) ? r : r ? [r] : [];
}
