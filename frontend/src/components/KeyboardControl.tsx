// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from "react";
import { controlWebSocketUrl, studioSocketProtocols } from "../api/client";

const KEYS = new Set(["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight", "Space"]);

export function KeyboardControl({ nodeId, runId, active }: { nodeId: string; runId: string | null; active: boolean }) {
  const keys = useRef(new Set<string>());
  const socket = useRef<WebSocket | null>(null);
  const sequence = useRef(0);
  const pad = useRef<HTMLDivElement>(null);
  const [connected, setConnected] = useState(false);
  const [focused, setFocused] = useState(false);
  const send = () => {
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify({ sequence: sequence.current++, keys: [...keys.current] }));
  };
  const release = () => { keys.current.clear(); send(); };

  useEffect(() => {
    if (!active || !runId) return;
    const ws = new WebSocket(controlWebSocketUrl(nodeId, runId), studioSocketProtocols());
    socket.current = ws;
    sequence.current = 0;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => { setConnected(false); keys.current.clear(); };
    const ownerDocument=pad.current?.ownerDocument??document;
    const ownerWindow=ownerDocument.defaultView??window;
    const timer = ownerWindow.setInterval(send, 75);
    ownerWindow.addEventListener("blur", release);
    ownerWindow.addEventListener("pagehide", release);
    ownerDocument.addEventListener("visibilitychange", release);
    return () => {
      release();
      ownerWindow.clearInterval(timer);
      ownerWindow.removeEventListener("blur", release);
      ownerWindow.removeEventListener("pagehide", release);
      ownerDocument.removeEventListener("visibilitychange", release);
      ws.close();
      socket.current = null;
    };
    // Callbacks read refs; reconnect only when the node/run/mode changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId, runId, active]);

  return <div ref={pad} className={`keyboard-pad${active && focused ? " focused" : ""}`} tabIndex={active ? 0 : -1}
    role="group" aria-label="Keyboard driving pad"
    onFocus={() => setFocused(true)} onBlur={() => { setFocused(false); release(); }}
    onKeyDown={(event) => {
      if (active && KEYS.has(event.code)) { event.preventDefault(); keys.current.add(event.code); send(); }
    }}
    onKeyUp={(event) => {
      if (KEYS.has(event.code)) { event.preventDefault(); keys.current.delete(event.code); send(); }
    }}>
    <strong>Keyboard driving</strong>
    <div>{!active ? "Select Manual to drive" : !connected ? "Connecting keyboard…" : focused ? "Hold W/A/S/D or arrow keys · Space stops" : "Click here, then hold W/A/S/D or arrow keys"}</div>
    <small>Releasing keys or leaving this pad stops manual motion.</small>
  </div>;
}
