// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import { useMemo, useState } from "react";
import type { PluginManifest } from "../types";

interface Props {
  plugins: PluginManifest[];
  collapsed: boolean;
  onToggleCollapse: () => void;
  onAddNode: (pluginId: string) => void;
}

const CATEGORY_COLORS: Record<string, string> = {
  Sensors: "#3E63DD",
  "Sensors (Examples)": "#3E63DD",
  Processing: "#16A34A",
  Output: "#B7860B",
};

export function Palette({ plugins, collapsed, onToggleCollapse, onAddNode }: Props) {
  const [query, setQuery] = useState("");

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q ? plugins.filter((p) => p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q)) : plugins;
    const groups = new Map<string, PluginManifest[]>();
    for (const p of filtered) {
      const list = groups.get(p.category) ?? [];
      list.push(p);
      groups.set(p.category, list);
    }
    return groups;
  }, [plugins, query]);

  return (
    <div className={`side-panel raised${collapsed ? " collapsed" : ""}`}>
      <div className="panel-head">
        <span className="panel-label">NODE PALETTE</span>
        <button className="collapse-btn raised-sm" onClick={onToggleCollapse} title="Collapse">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 6l-6 6 6 6" />
          </svg>
        </button>
      </div>
      <div className="panel-body">
        <div className="panel-body-inner full">
          <div className="search inset">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="7" />
              <path d="M21 21l-4-4" />
            </svg>
            <input placeholder="Search nodes…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>

          {plugins.length === 0 && (
            <div className="empty-hint">
              No plugins discovered yet.
              <br />
              Drop a Node subclass into <code className="mono">plugins/</code> and restart the backend.
            </div>
          )}

          {[...grouped.entries()].map(([category, items]) => (
            <div key={category}>
              <div className="category">{category.toUpperCase()}</div>
              {items.map((p) => (
                <button
                  key={p.id}
                  className="palette-item raised-sm"
                  onClick={() => onAddNode(p.id)}
                  title={p.description}
                >
                  <span className="item-dot" style={{ background: CATEGORY_COLORS[p.category] ?? "#6B7480" }} />
                  {p.name}
                </button>
              ))}
            </div>
          ))}
        </div>
        <div className="collapsed-rail">
          {plugins.map((p) => (
            <div
              key={p.id}
              className="rail-dot"
              style={{ background: CATEGORY_COLORS[p.category] ?? "#6B7480" }}
              title={p.name}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
