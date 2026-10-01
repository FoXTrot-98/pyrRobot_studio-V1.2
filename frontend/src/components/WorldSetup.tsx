// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState } from "react";
import { WorldWorkspace } from "./WorldWorkspace";

export function WorldSetup({onClose,onApplied}:{onClose:()=>void;onApplied:()=>Promise<void>}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const [busy,setBusy]=useState(false);
  useEffect(()=>{dialog.current?.showModal();},[]);
  return <dialog ref={dialog} className="world-dialog" aria-labelledby="world-setup-title"
    onCancel={event=>{event.preventDefault();if(!busy)onClose();}}>
    <header><div><h2 id="world-setup-title">World setup</h2><p>Choose your environment before starting the robot.</p></div>
      <button aria-label="Close world setup" disabled={busy} onClick={onClose}>Close</button></header>
    <WorldWorkspace running={false} onApplied={onApplied} onBusyChange={setBusy}/>
  </dialog>;
}
