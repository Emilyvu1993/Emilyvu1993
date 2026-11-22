import { create } from "zustand";
import { api, pickPdfs, pickWorkspaceDir, toAppError } from "./lib/api";
import { conversionKey } from "./lib/configUtils";
import {
  DEFAULT_CONFIG, type AppError, type ConvertOutcome, type InspectResult, type OutputConfig,
  type OutputConfigDraft, type Workspace, type WorkspaceFile,
} from "./types/domain";

export interface Preview { outcome: ConvertOutcome; key: string }
export interface Notice { kind: "success" | "info" | "warn"; text: string }

interface State {
  workspace: Workspace | null;
  configs: OutputConfig[];
  drafts: Record<string, OutputConfigDraft>;
  inspect: Record<string, InspectResult | AppError | undefined>;
  previews: Record<string, Preview | undefined>;
  errors: Record<string, AppError | undefined>;
  busy: null | "convert" | "save" | "files";
  notice: Notice | null;

  init(): Promise<void>;
  openWorkspace(path?: string): Promise<void>;
  addFiles(): Promise<void>;
  removeFile(id: string): Promise<void>;
  selectFile(id: string): Promise<void>;
  updateDraft(fileId: string, fn: (d: OutputConfigDraft) => OutputConfigDraft): void;
  loadConfig(fileId: string, configId: string): void;
  newConfig(fileId: string): void;
  saveConfig(fileId: string, asNew: boolean): Promise<void>;
  deleteConfig(fileId: string, configId: string): Promise<void>;
  runInspect(fileId: string): Promise<void>;
  convert(fileId: string): Promise<void>;
  saveOutput(fileId: string): Promise<void>;
  discardPreview(fileId: string): Promise<void>;
  dismissError(fileId: string): void;
  setNotice(n: Notice | null): void;
}

const draftTimers = new Map<string, ReturnType<typeof setTimeout>>();
const clone = <T,>(v: T): T => structuredClone(v);

function stripMeta(c: OutputConfig): OutputConfigDraft {
  return clone(c);
}

function initialDraft(f: WorkspaceFile, configs: OutputConfig[]): OutputConfigDraft {
  if (f.draft_config) return { ...clone(DEFAULT_CONFIG), ...clone(f.draft_config) };
  const bound = configs.find((c) => c.id === f.bound_config_id);
  return bound ? stripMeta(bound) : clone(DEFAULT_CONFIG);
}

export const useStore = create<State>((set, get) => {
  const fail = (e: unknown, fileId?: string) => {
    const ae = toAppError(e);
    if (fileId) set((s) => ({ errors: { ...s.errors, [fileId]: ae } }));
    else set({ notice: { kind: "warn", text: `${ae.code}: ${ae.message}` } });
    return ae;
  };

  const hydrate = (ws: Workspace) => {
    const { configs, drafts } = get();
    const next = { ...drafts };
    for (const f of ws.files) next[f.id] ??= initialDraft(f, configs);
    for (const id of Object.keys(next)) if (!ws.files.some((f) => f.id === id)) delete next[id];
    set({ workspace: ws, drafts: next });
    const a = ws.active_file_id;
    if (a && !get().inspect[a]) void get().runInspect(a);
  };

  return {
    workspace: null, configs: [], drafts: {}, inspect: {}, previews: {}, errors: {}, busy: null, notice: null,

    async init() {
      try {
        const last = await api.lastWorkspacePath();
        if (last) await get().openWorkspace(last);
      } catch { /* first run: stay on welcome screen */ }
    },

    async openWorkspace(path) {
      const p = path ?? (await pickWorkspaceDir());
      if (!p) return;
      try {
        const ws = await api.openWorkspace(p);
        const configs = await api.listConfigs();
        set({ configs, drafts: {}, inspect: {}, previews: {}, errors: {} });
        hydrate(ws);
      } catch (e) { fail(e); }
    },

    async addFiles() {
      const paths = await pickPdfs();
      if (!paths.length) return;
      set({ busy: "files" });
      try {
        const { report, workspace } = await api.addFiles(paths);
        hydrate(workspace);
        const parts = [`${report.added.length} added`];
        if (report.skipped_duplicates.length) parts.push(`${report.skipped_duplicates.length} duplicate skipped`);
        if (report.rejected.length) parts.push(`${report.rejected.length} rejected (${report.rejected.map((r) => r.message).join("; ")})`);
        set({ notice: { kind: report.rejected.length ? "warn" : "success", text: parts.join(" · ") } });
      } catch (e) { fail(e); } finally { set({ busy: null }); }
    },

    async removeFile(id) {
      try { hydrate(await api.removeFile(id)); } catch (e) { fail(e); }
    },

    async selectFile(id) {
      if (get().busy === "convert") {
        set({ notice: { kind: "warn", text: "Wait for the running conversion to finish before switching files." } });
        return;
      }
      try { hydrate(await api.setActiveFile(id)); } catch (e) { fail(e); }
    },

    updateDraft(fileId, fn) {
      const cur = get().drafts[fileId];
      if (!cur) return;
      const next = fn(clone(cur));
      set((s) => ({ drafts: { ...s.drafts, [fileId]: next } }));
      clearTimeout(draftTimers.get(fileId));
      draftTimers.set(fileId, setTimeout(() => void api.saveDraft(fileId, next).catch(() => {}), 500));
    },

    loadConfig(fileId, configId) {
      const c = get().configs.find((x) => x.id === configId);
      if (!c) return;
      get().updateDraft(fileId, () => stripMeta(c));
      void api.bindConfig(fileId, configId).catch(() => {});
    },

    newConfig(fileId) {
      get().updateDraft(fileId, () => clone(DEFAULT_CONFIG));
      void api.bindConfig(fileId, null).catch(() => {});
    },

    async saveConfig(fileId, asNew) {
      const d = get().drafts[fileId];
      if (!d) return;
      try {
        const toSave = asNew ? { ...d, id: undefined, name: d.id ? `${d.name} (copy)` : d.name } : d;
        const saved = await api.saveConfig(toSave);
        const configs = await api.listConfigs();
        set({ configs, notice: { kind: "success", text: `Config “${saved.name}” saved (v${saved.version})` } });
        get().updateDraft(fileId, () => stripMeta(saved));
        await api.bindConfig(fileId, saved.id);
      } catch (e) { fail(e); }
    },

    async deleteConfig(fileId, configId) {
      try {
        await api.deleteConfig(configId);
        set({ configs: await api.listConfigs() });
        get().updateDraft(fileId, (d) => (d.id === configId ? { ...d, id: undefined, version: undefined } : d));
      } catch (e) { fail(e); }
    },

    async runInspect(fileId) {
      try {
        const r = await api.inspectFile(fileId);
        set((s) => ({ inspect: { ...s.inspect, [fileId]: r } }));
      } catch (e) {
        set((s) => ({ inspect: { ...s.inspect, [fileId]: toAppError(e) } }));
      }
    },

    async convert(fileId) {
      const d = get().drafts[fileId];
      if (!d || get().busy) return;
      set((s) => ({ busy: "convert", errors: { ...s.errors, [fileId]: undefined } }));
      try {
        const outcome = await api.convert(fileId, d);
        set((s) => ({ previews: { ...s.previews, [fileId]: { outcome, key: conversionKey(d) } } }));
      } catch (e) {
        // failure: keep draft untouched, drop any stale preview, show the error
        set((s) => ({ previews: { ...s.previews, [fileId]: undefined } }));
        fail(e, fileId);
      } finally {
        set({ busy: null });
        try { hydrate(await api.getWorkspace()); } catch { /* ignore */ }
      }
    },

    async saveOutput(fileId) {
      const p = get().previews[fileId];
      const d = get().drafts[fileId];
      if (!p || !d) return;
      set({ busy: "save" });
      try {
        const r = await api.saveOutput(p.outcome.job_id, d);
        set((s) => ({
          previews: { ...s.previews, [fileId]: undefined },
          notice: { kind: "success", text: `Saved ${p.outcome.result.record_count} records → ${r.output_path}${r.backup_path ? " (previous kept as .bak)" : ""}` },
        }));
        hydrate(await api.getWorkspace());
      } catch (e) {
        set((s) => ({ previews: { ...s.previews, [fileId]: undefined } }));
        fail(e, fileId);
      } finally { set({ busy: null }); }
    },

    async discardPreview(fileId) {
      const p = get().previews[fileId];
      set((s) => ({ previews: { ...s.previews, [fileId]: undefined } }));
      if (p) await api.discardPreview(p.outcome.job_id).catch(() => {});
    },

    dismissError(fileId) { set((s) => ({ errors: { ...s.errors, [fileId]: undefined } })); },
    setNotice(n) { set({ notice: n }); },
  };
});

export const useActiveFile = () =>
  useStore((s) => s.workspace?.files.find((f) => f.id === s.workspace?.active_file_id) ?? null);
