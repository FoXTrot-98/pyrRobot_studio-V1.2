// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from "react";
import { Switch } from "./Switch";

export interface GridSettings {
  visible: boolean;
  spacing: number;
  opacity: number; // 0..1
  style: "dots" | "lines" | "cross";
  snap: boolean;
}

export const DEFAULT_GRID_SETTINGS: GridSettings = {
  visible: true,
  spacing: 22,
  opacity: 0.55,
  style: "dots",
  snap: true,
};

interface Props {
  settings: GridSettings;
  onChange: (next: GridSettings) => void;
}

export function GridToolbar({ settings, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const gearRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        e.target !== gearRef.current
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("click", handleClickOutside);
    return () => document.removeEventListener("click", handleClickOutside);
  }, []);

  const patch = (partial: Partial<GridSettings>) => onChange({ ...settings, ...partial });

  return (
    <>
      <div className="toolbar-divider" />
      <button
        className={settings.visible ? "active" : ""}
        title="Toggle grid"
        onClick={() => patch({ visible: !settings.visible })}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
        </svg>
      </button>
      <button ref={gearRef} title="Grid settings" onClick={() => setOpen((o) => !o)}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06A1.65 1.65 0 005 15a1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06A1.65 1.65 0 009 4.6a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z" />
        </svg>
      </button>

      <div className={`grid-popover raised${open ? " open" : ""}`} ref={popoverRef}>
        <div className="gp-title">Canvas Grid</div>

        <div className="gp-row">
          <span>Show grid</span>
          <Switch on={settings.visible} onChange={(v) => patch({ visible: v })} />
        </div>

        <div className="gp-row">
          <span>Snap to grid</span>
          <Switch on={settings.snap} onChange={(v) => patch({ snap: v })} disabled={!settings.visible} />
        </div>

        <div className="gp-row-col">
          <div className="gp-row">
            <span>Spacing</span>
            <span className="gp-val mono">{settings.spacing}px</span>
          </div>
          <input
            type="range"
            className="n-slider"
            min={12}
            max={48}
            step={2}
            value={settings.spacing}
            onChange={(e) => patch({ spacing: Number(e.target.value) })}
          />
        </div>

        <div className="gp-row-col">
          <div className="gp-row">
            <span>Opacity</span>
            <span className="gp-val mono">{Math.round(settings.opacity * 100)}%</span>
          </div>
          <input
            type="range"
            className="n-slider"
            min={10}
            max={100}
            step={5}
            value={Math.round(settings.opacity * 100)}
            onChange={(e) => patch({ opacity: Number(e.target.value) / 100 })}
          />
        </div>

        <div className="gp-row-col">
          <span>Style</span>
          <div className="style-choices">
            {(["dots", "lines", "cross"] as const).map((s) => (
              <button
                key={s}
                className={`style-choice${settings.style === s ? " active" : ""}`}
                onClick={() => patch({ style: s })}
              >
                {s[0].toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
