// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

export interface BuilderPort { name: string; data_type: string; schema: string | null; required: boolean }
export interface BuilderParameter { name: string; kind: string; value: string; min: string; max: string }
export interface PluginDraft {
  slug: string; name: string; version: string; description: string; template: string;
  inputs: BuilderPort[]; outputs: BuilderPort[]; params: BuilderParameter[];
  sample: string; source: string; dirty: boolean;
}
export const DRAFT_KEY = "pyrobot.plugin-builder.draft.v1";

export function parsePluginDraft(value: unknown): PluginDraft {
  if (!value || typeof value !== "object") throw new Error("Invalid builder draft");
  const d = value as Record<string, unknown>;
  for (const key of ["slug", "name", "version", "description", "template", "sample", "source"])
    if (typeof d[key] !== "string") throw new Error(`Invalid draft field: ${key}`);
  if (!["sensor", "processing"].includes(String(d.template)) || typeof d.dirty !== "boolean") throw new Error("Invalid draft template/state");
  for (const key of ["inputs", "outputs"]) {
    const ports = d[key];
    if (!Array.isArray(ports) || ports.length > 16 || ports.some(p => !p || typeof p !== "object" ||
      typeof p.name !== "string" || typeof p.data_type !== "string" || typeof p.required !== "boolean" ||
      !(p.schema === null || typeof p.schema === "string"))) throw new Error(`Invalid draft ${key}`);
  }
  if (!Array.isArray(d.params) || d.params.length > 32 || d.params.some(p => !p || typeof p !== "object" ||
    ["name", "kind", "value", "min", "max"].some(k => typeof p[k] !== "string"))) throw new Error("Invalid draft parameters");
  if (JSON.stringify(d).length > 200000) throw new Error("Builder draft exceeds 200 KB");
  return Object.fromEntries(["slug","name","version","description","template","inputs","outputs","params","sample","source","dirty"].map(k=>[k,d[k]])) as unknown as PluginDraft;
}

export function loadPluginDraft(): PluginDraft | null {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    return raw ? parsePluginDraft(JSON.parse(raw)) : null;
  } catch { return null; }
}
