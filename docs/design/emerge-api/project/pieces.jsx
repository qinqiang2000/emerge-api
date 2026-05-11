// pieces.jsx — building blocks: filesystem spine, conversation, tool calls, composer, context surface

const { useState, useRef, useEffect, useMemo } = React;

// ─────────── help popover ───────────
function HelpPopover({ onClose }) {
  useEffect(()=>{
    function onKey(e){ if (e.key==='Escape') onClose(); }
    function onClick(e){ if (!e.target.closest('.help-pop') && !e.target.closest('.help-btn')) onClose(); }
    window.addEventListener('keydown', onKey);
    setTimeout(()=>window.addEventListener('mousedown', onClick), 0);
    return ()=>{ window.removeEventListener('keydown', onKey); window.removeEventListener('mousedown', onClick); };
  }, [onClose]);
  return (
    <div className="help-pop" onClick={e=>e.stopPropagation()}>
      <div className="ey">how this works</div>
      <h4>An agent that writes the API for you.</h4>
      <p>Drop documents into a folder. The agent reads them, derives a <code>schema.json</code>, and runs first-pass extractions. You review the ones it's least sure about — every edit teaches it.</p>
      <div className="steps">
        <div className="step"><span className="n">1</span><span className="t">drop PDFs into <code style={{fontFamily:'var(--mono)',fontSize:11,color:'var(--ochre-2)'}}>docs/</code> · run <code style={{fontFamily:'var(--mono)',fontSize:11,color:'var(--ochre-2)'}}>/init</code></span></div>
        <div className="step"><span className="n">2</span><span className="t">review the flagged docs · accept or correct</span></div>
        <div className="step"><span className="n">3</span><span className="t">run <code style={{fontFamily:'var(--mono)',fontSize:11,color:'var(--ochre-2)'}}>/eval</code> · then <code style={{fontFamily:'var(--mono)',fontSize:11,color:'var(--ochre-2)'}}>/improve</code> any weak fields</span></div>
        <div className="step"><span className="n">4</span><span className="t"><code style={{fontFamily:'var(--mono)',fontSize:11,color:'var(--ochre-2)'}}>/publish</code> when you're ready · key is minted</span></div>
      </div>
      <p style={{color:'var(--ink-3)',fontSize:12.5,fontStyle:'italic'}}>Type <code>/</code> in the composer for the full menu. Everything is on disk — you can always read or edit the files yourself.</p>
      <div className="closehint"><kbd>Esc</kbd> to close</div>
    </div>
  );
}

// ─────────── topbar ───────────
function Topbar({ projectName, status, onToggleImprove, improveRunning, leftHidden, rightHidden, onToggleLeft, onToggleRight }) {
  const [helpOpen, setHelpOpen] = useState(false);
  return (
    <div className="top">
      <button
        className={'side-toggle left ' + (leftHidden ? 'collapsed' : '')}
        onClick={onToggleLeft}
        title={leftHidden ? 'show sidebar' : 'hide sidebar'}
        aria-label={leftHidden ? 'show sidebar' : 'hide sidebar'}>
        {leftHidden ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="2.5" y1="4" x2="13.5" y2="4"/>
            <line x1="2.5" y1="8" x2="13.5" y2="8"/>
            <line x1="2.5" y1="12" x2="13.5" y2="12"/>
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="3" width="12" height="10" rx="1.5"/>
            <line x1="6.5" y1="3.4" x2="6.5" y2="12.6"/>
          </svg>
        )}
      </button>
      <div className="brand"><span className="dot"></span>emerge</div>
      <div className="crumbs">
        <span>~/projects/</span>
        <span className="here">{projectName}</span>
        <span className="sep">/</span>
        <span>schema</span>
        <span className="sep">·</span>
        <span>v3</span>
        <span className="sep">·</span>
        <span style={{color:'var(--ochre-2)'}}>draft</span>
      </div>
      <div className="spacer"></div>
      {improveRunning && (
        <div className="pill" style={{cursor:'default'}} onClick={onToggleImprove}>
          <span className="dotr"></span>/improve · 2 of 4 fields
        </div>
      )}
      <div className="pill"><span className="dotg"></span>watching docs/ · 42 files</div>
      <div className="pill" style={{borderColor:'var(--ink)',color:'var(--ink)'}}>⌘K · ask agent</div>
      <button
        className={'help-btn ' + (helpOpen?'on':'')}
        onClick={()=>setHelpOpen(o=>!o)}
        title="how this works"
        aria-label="how this works">?</button>
      {helpOpen && <HelpPopover onClose={()=>setHelpOpen(false)} />}
      <button
        className={'side-toggle right ' + (rightHidden ? 'collapsed' : '')}
        onClick={onToggleRight}
        title={rightHidden ? 'show context' : 'hide context'}
        aria-label={rightHidden ? 'show context' : 'hide context'}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
          <rect x="2" y="3" width="12" height="10" rx="1.5"/>
          <line x1="9.5" y1="3.4" x2="9.5" y2="12.6"/>
        </svg>
      </button>
    </div>
  );
}

// ─────────── filesystem spine ───────────
function FSSpine({ activeProject, onSwitchProject }) {
  return (
    <div className="fs">
      <div className="fs-head">~/projects <span className="small">5</span></div>
      {PROJECTS.map(p => (
        <div key={p.id}
             className={'proj ' + (p.id===activeProject ? 'active' : '')}
             onClick={()=>onSwitchProject(p.id)}>
          <span className="glyph">{p.id===activeProject ? '▸' : '·'}</span>
          <span>{p.name}</span>
          <span className="meta">{p.meta}</span>
        </div>
      ))}
      <hr/>
      <div className="fs-head">{PROJECTS.find(p=>p.id===activeProject)?.name || ''}<span className="small">ls</span></div>
      <div className="tree">
        {TREE.map((n, i) => {
          if (n.kind==='dir') return (
            <div key={i} className="branch dir">
              <span className="arrow">▾</span>
              <span>{n.name}</span>
              <span className="stamp">{n.count}</span>
            </div>
          );
          if (n.kind==='ghost') return <div key={i} className="ghost">{n.name}</div>;
          return (
            <div key={i} className="branch file">
              <span style={{color:'var(--ink-5)'}}>·</span>
              <span>{n.name}</span>
              <span className="stamp">{n.stamp}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────── tool call (collapsed and expanded) ───────────
function ToolCall({ name, args, status='done', dur, open:openProp=false, children, onCancel, footer }) {
  const [open, setOpen] = useState(openProp);
  useEffect(()=>{ setOpen(openProp); }, [openProp]);
  const statusLabel = {done:'done', run:'running', err:'failed', cand:'candidate'}[status];
  return (
    <div className={'tool ' + (open ? 'open' : '')}>
      <div className="t-head" onClick={()=>setOpen(o=>!o)}>
        <span className="t-arrow">{open?'▾':'▸'}</span>
        <span className="t-name">{name}</span>
        <span className="t-args">({args})</span>
        {status==='run' && <span className="spin"></span>}
        <span className={'t-status '+status}>{statusLabel}</span>
        {dur && <span className="t-dur">{dur}</span>}
      </div>
      {open && <div className="t-body">{children}</div>}
      {open && footer}
    </div>
  );
}

// ─── tool stack: claude-style sequence with in-place "current step" + collapse-to-one-line ───
// usage: <ToolStack steps={[{name,args},...]} state="done|run" running={idx} totalDur="13.6s">
//          <ToolCall ... /> <ToolCall ... /> ...
//        </ToolStack>
// each step in `steps` corresponds (by order) to a <ToolCall> child for the expanded view.
function ToolStack({ steps, state='done', running=0, totalDur, open:openProp=false, children }) {
  const [open, setOpen] = useState(openProp);
  const [liveIdx, setLiveIdx] = useState(running);
  useEffect(()=>{ setOpen(openProp); }, [openProp]);
  useEffect(()=>{ setLiveIdx(running); }, [running]);
  // auto-advance through steps while in 'run' mode, ~1.4s per step (demo cadence)
  useEffect(()=>{
    if (state !== 'run') return;
    const id = setInterval(()=>{
      setLiveIdx(i => (i + 1) % steps.length);
    }, 1400);
    return ()=>clearInterval(id);
  }, [state, steps.length]);

  const kids = React.Children.toArray(children);
  const total = steps.length;

  if (state === 'run') {
    return (
      <div className="tstack">
        <div className="ts-live">
          {steps.map((s, i)=>(
            <div key={i} className={'ts-row ' + (i===liveIdx ? 'cur' : (i<liveIdx ? 'prev' : ''))}>
              <span className="ts-orbit"><i></i><i></i><i></i><i></i><i></i><i></i></span>
              <span className="nm">{s.name}</span>
              <span className="ag">({s.args})</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={'tstack ' + (open ? 'open' : '')}>
      <div className="ts-ran" onClick={()=>setOpen(o=>!o)}>
        <span>Ran</span>
        <span className="cnt">{total}</span>
        <span>{total===1 ? 'tool' : 'tools'}</span>
        {totalDur && <span className="dur">· {totalDur}</span>}
        <span className="chev">›</span>
      </div>
      <div className="ts-tree">
        {kids.map((kid, i)=>(
          <div key={i} className={'ts-node ' + (steps[i]?.state || 'done')}>
            <span className="ts-dot" aria-hidden="true">
              <svg width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="2.5,3.5 5,6 2.5,8.5"/><line x1="6.5" y1="8.5" x2="9.5" y2="8.5"/>
              </svg>
            </span>
            {kid}
          </div>
        ))}
      </div>
    </div>
  );
}

function ToolRow({ glyph='·', label, value, mini, nest=0 }) {
  const c = nest===2 ? 't-row nest2' : nest===1 ? 't-row nest' : 't-row';
  return (
    <div className={c}>
      <span className="glyph">{glyph}</span>
      <span className="label">{label}{mini && <span className="mini">{mini}</span>}</span>
      {value && <span className="v">{value}</span>}
    </div>
  );
}

// ─────────── conversation turn ───────────
function Turn({ who, ts, children }) {
  const isAgent = who==='agent';
  return (
    <div className="turn">
      <div className="turn-meta">
        <span className={'who '+(isAgent?'agent':'')}>{isAgent?'agent':'you'}</span>
        <span className="ts">{ts}</span>
        <span className="rule"></span>
      </div>
      {children}
    </div>
  );
}

// ─────────── composer ───────────
function Composer({ value, onChange, onSlash, slashOpen }) {
  const SLASH = [
    {cmd:'/init',     desc:'derive a schema from the documents in this folder'},
    {cmd:'/extract',  desc:'run extraction on every doc, or a subset'},
    {cmd:'/review',   desc:'open the next pending document for review'},
    {cmd:'/eval',     desc:'score current schema against reviewed/'},
    {cmd:'/improve',  desc:'long-running: refine field descriptions to lift F1'},
    {cmd:'/publish',  desc:'freeze a version and mint an API key'},
  ];
  const [focused, setFocused] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const taRef = useRef(null);
  // auto-grow: resize textarea height to fit content (capped, then scrolls)
  useEffect(()=>{
    const el = taRef.current; if (!el) return;
    el.style.height = 'auto';
    const max = 220; // px cap before internal scroll
    el.style.height = Math.min(el.scrollHeight, max) + 'px';
    el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden';
  }, [value]);
  const showGhost = focused && !value;
  // when typing / — drive activeIdx by typed prefix match, but still allow ↑/↓
  const slashMatches = useMemo(()=>{
    if (!slashOpen) return SLASH;
    const q = value.trim().toLowerCase();
    const filt = SLASH.filter(s => s.cmd.toLowerCase().startsWith(q));
    return filt.length ? filt : SLASH;
  }, [slashOpen, value]);
  useEffect(()=>{ setActiveIdx(0); }, [slashOpen, focused]);

  function handleKey(e){
    const list = slashOpen ? slashMatches : (showGhost ? SLASH : null);
    if (!list) return;
    if (e.key === 'ArrowDown'){
      e.preventDefault();
      setActiveIdx(i => (i+1) % list.length);
    } else if (e.key === 'ArrowUp'){
      e.preventDefault();
      setActiveIdx(i => (i-1+list.length) % list.length);
    } else if (e.key === 'Enter' && !e.shiftKey){
      const pick = list[Math.min(activeIdx, list.length-1)];
      if (pick){ e.preventDefault(); onSlash(pick.cmd); }
    } else if (e.key === 'Escape' && slashOpen){
      e.preventDefault();
      onChange('');
    }
  }
  return (
    <>
      <div className="composer-wrap">
        <div className="composer">
          {slashOpen && (
            <div className="slashmenu">
              <div className="inner">
                {slashMatches.map((s,i)=> (
                  <div key={s.cmd}
                       className={'item '+(i===activeIdx?'active':'')}
                       onMouseEnter={()=>setActiveIdx(i)}
                       onMouseDown={(e)=>{e.preventDefault();onSlash(s.cmd);}}>
                    <span className="cmd">{s.cmd}</span>
                    <span className="desc">{s.desc}</span>
                    <span className="hint">{i===activeIdx?'↵':''}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="row1">
            <span className="caret">▸</span>
            <textarea
              ref={taRef}
              rows={1}
              placeholder="say something to the agent, or type / for a command…"
              value={value}
              onChange={e=>onChange(e.target.value)}
              onKeyDown={handleKey}
              onFocus={()=>setFocused(true)}
              onBlur={()=>setTimeout(()=>setFocused(false),120)}
            />
          </div>
          {showGhost && null}
          <div className="row2">
            <div className="slashes">
              <span className="slash"><b>/init</b></span>
              <span className="slash"><b>/extract</b></span>
              <span className="slash"><b>/review</b></span>
              <span className="slash"><b>/improve</b></span>
              <span className="slash"><b>/publish</b></span>
            </div>
            <div className="send"><kbd>⌘</kbd><kbd>↵</kbd> send</div>
          </div>
        </div>
      </div>
    </>
  );
}

// ─────────── right context surface ───────────
function ContextSurface({ mode='default' }) {
  return (
    <div className="ctx">
      <div className="ctx-section">
        <div className="ctx-h">schema.json <span className="small">14 fields · v3 draft</span></div>
        <div className="ctx-card" style={{padding:0}}>
          {SCHEMA_FIELDS.slice(0,7).map(f=>(
            <div key={f.name} className="schemaRow" style={{padding:'8px 12px',borderBottom:'1px solid var(--rule-soft)'}}>
              <span>{f.name}</span>
              <span className="typ">{f.type}</span>
            </div>
          ))}
          <div className="schemaRow" style={{padding:'8px 12px',color:'var(--ink-4)',fontStyle:'italic'}}>+ 7 more</div>
        </div>
        <p className="micro" style={{marginTop:10,fontSize:12}}>The schema becomes the agent's prompt at publish time. Edit through conversation.</p>
      </div>

      <div className="ctx-section">
        <div className="ctx-h">docs/ <span className="small">9 of 42 shown</span></div>
        <div className="ctx-card" style={{padding:6}}>
          {DOCS.map(d=>(
            <div key={d.name} className="doc">
              <span className="nm">{d.name}</span>
              <span className={'stat '+ ({reviewed:'rev',pending:'pen',new:'new',error:'err'}[d.status])}>
                {d.status}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="ctx-section">
        <div className="ctx-h">metrics/ <span className="small">latest eval</span></div>
        <div className="ctx-card">
          {METRICS.map(m=>(
            <div key={m.k} className="metric">
              <span className="k">{m.k}</span>
              <span className={'v '+(m.tone||'')}>{m.v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─────────── improve banner ───────────
function ImproveBanner({ pct, onOpen }) {
  return (
    <div className="improvebar">
      <span className="live"></span>
      <span className="lab"><b>/improve</b> running · field 2 of 4 · vendor_tax_id</span>
      <div className="progress">
        <span>{pct}%</span>
        <div className="miniseg"><i style={{width:pct+'%'}}></i></div>
      </div>
      <button className="openbtn" onClick={onOpen}>open</button>
    </div>
  );
}

window.Topbar = Topbar;
window.FSSpine = FSSpine;
window.ToolCall = ToolCall;
window.ToolStack = ToolStack;
window.ToolRow = ToolRow;
window.Turn = Turn;
window.Composer = Composer;
window.ContextSurface = ContextSurface;
window.ImproveBanner = ImproveBanner;
