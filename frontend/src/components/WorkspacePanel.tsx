// SPDX-FileCopyrightText: 2026 Kanishka Kularathna (FoXTrot-98)
// SPDX-License-Identifier: Apache-2.0

import { useEffect, useRef, useState, type ReactNode, type PointerEvent } from 'react';
import { createPortal } from 'react-dom';
import '../styles/workspace-panel.css';

type Layout = { floating: boolean; x: number; y: number; width: number; height: number };
const initial: Layout = { floating:false, x:80, y:100, width:620, height:520 };
function readLayout(id:string):Layout {
  try {
    const value=JSON.parse(localStorage.getItem(`studio.panel.${id}`)??'null');
    if (value && ['x','y','width','height'].every(key=>Number.isFinite(value[key])))
      return {...initial,...value,floating:value.floating===true};
  } catch { /* Storage may be unavailable. */ }
  return {...initial};
}
function visible(value:Layout):Layout {
  const width=Math.min(Math.max(280,value.width),window.innerWidth);
  const height=Math.min(Math.max(200,value.height),window.innerHeight);
  return {...value,width,height,x:Math.max(0,Math.min(value.x,window.innerWidth-width)),y:Math.max(0,Math.min(value.y,window.innerHeight-height))};
}

export function WorkspacePanel({id,title,children}:{id:string;title:string;children:ReactNode}) {
  const [layout,setLayout]=useState(()=>visible(readLayout(id)));
  const [maximized,setMaximized]=useState(false);
  const [popup,setPopup]=useState<{window:Window;root:HTMLDivElement}|null>(null);
  const [error,setError]=useState('');
  const popupRef=useRef<Window|null>(null);
  const panel=useRef<HTMLElement|null>(null);
  const gesture=useRef<{x:number;y:number;layout:Layout;resize:boolean}|null>(null);
  useEffect(()=>{
    try {localStorage.setItem(`studio.panel.${id}`,JSON.stringify(layout));} catch { /* Session-only layout. */ }
  },[id,layout]);
  useEffect(()=>{
    const resize=()=>setLayout(value=>visible(value));
    const reset=()=>{popupRef.current?.close();popupRef.current=null;setPopup(null);setMaximized(false);setLayout({...initial});setError('');};
    window.addEventListener('resize',resize);
    window.addEventListener('studio-reset-panels',reset);
    const close=()=>popupRef.current?.close();
    window.addEventListener('pagehide',close);
    return ()=>{window.removeEventListener('resize',resize);window.removeEventListener('studio-reset-panels',reset);window.removeEventListener('pagehide',close);close();};
  },[]);
  useEffect(()=>{
    if(!popup)return;
    const closed=()=>{if(!popup.window.closed)popup.window.close();popupRef.current=null;setPopup(null);setMaximized(false);};
    popup.window.addEventListener('pagehide',closed);
    const timer=window.setInterval(()=>{if(popup.window.closed)closed();},300);
    return ()=>{clearInterval(timer);popup.window.removeEventListener('pagehide',closed);};
  },[popup]);
  const dock=()=>{popupRef.current?.close();popupRef.current=null;setPopup(null);setMaximized(false);setLayout(value=>({...value,floating:false}));};
  const detach=()=>{
    const child=window.open('','_blank','popup=yes,width=1000,height=760');
    if(!child){setError('Pop-up blocked. Allow pop-ups for Studio, then try again.');return;}
    child.document.title=`${title} — PyRobot Studio`;
    const base=child.document.createElement('base');base.href=document.baseURI;child.document.head.append(base);
    document.querySelectorAll('style,link[rel="stylesheet"]').forEach(style=>child.document.head.append(style.cloneNode(true)));
    child.document.body.className='studio-panel-window';
    const root=child.document.createElement('div');child.document.body.append(root);
    popupRef.current=child;setPopup({window:child,root});setMaximized(false);setError('');
  };
  const start=(event:PointerEvent<HTMLElement>,resize=false)=>{
    if(popup||maximized||event.button!==0||(!resize&&(event.target as HTMLElement).closest('button')))return;
    const rect=panel.current!.getBoundingClientRect();
    const next=visible({...layout,floating:true,x:rect.x,y:rect.y,width:rect.width,height:rect.height});
    gesture.current={x:event.clientX,y:event.clientY,layout:next,resize};
    setLayout(next);event.currentTarget.setPointerCapture(event.pointerId);event.preventDefault();
  };
  const move=(event:PointerEvent<HTMLElement>)=>{
    const current=gesture.current;if(!current)return;
    const dx=event.clientX-current.x,dy=event.clientY-current.y;
    setLayout(visible(current.resize?{...current.layout,width:current.layout.width+dx,height:current.layout.height+dy}:{...current.layout,x:current.layout.x+dx,y:current.layout.y+dy}));
  };
  const end=()=>{gesture.current=null;};
  const floating=layout.floating&&!popup;
  const content=<section ref={panel} aria-label={`${title} panel`} className={`workspace-panel ${floating?'floating':''} ${maximized?'maximized':''} ${popup?'detached':''}`}
    style={floating&&!maximized?{left:layout.x,top:layout.y,width:layout.width,height:layout.height}:undefined}>
    <header className="workspace-panel-title" onPointerDown={start} onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
      <strong title="Drag to move this panel">{title}</strong><div>
        {(floating||popup||maximized)&&<button onClick={dock} aria-label={`Dock ${title}`}>Dock</button>}
        {!popup&&!floating&&<button onClick={()=>setLayout(value=>({...visible(value),floating:true}))} aria-label={`Float ${title}`}>Float</button>}
        <button onClick={()=>setMaximized(value=>!value)} aria-label={`${maximized?'Restore':'Maximize'} ${title}`}>{maximized?'Restore':'Maximize'}</button>
        <button onClick={()=>{const element=panel.current; if(element)void element.requestFullscreen().catch(()=>setError('Full screen is unavailable in this browser. Use Maximize instead.'));}} aria-label={`Full screen ${title}`}>Full screen</button>
        {!popup&&<button onClick={detach} aria-label={`Pop out ${title}`}>Pop out</button>}
      </div>
    </header>
    {error&&<p role="alert">{error}</p>}
    <div className="workspace-panel-content">{children}</div>
    {floating&&!maximized&&<button className="workspace-resize" aria-label={`Resize ${title}`} onPointerDown={event=>start(event,true)}
      onPointerMove={move} onPointerUp={end} onPointerCancel={end} onKeyDown={event=>{
        if(['ArrowRight','ArrowLeft','ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();setLayout(value=>visible({...value,width:value.width+(event.key==='ArrowRight'?20:event.key==='ArrowLeft'?-20:0),height:value.height+(event.key==='ArrowDown'?20:event.key==='ArrowUp'?-20:0)}));}
      }}>◢</button>}
  </section>;
  return popup?<><div className="workspace-placeholder"><strong>{title} is in another window</strong><button onClick={()=>popup.window.focus()}>Focus window</button><button onClick={dock}>Dock {title}</button></div>{createPortal(content,popup.root)}</>:content;
}
