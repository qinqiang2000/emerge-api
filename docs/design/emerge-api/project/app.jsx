// app.jsx — main app, mounts the prototype

const { useState: useS, useEffect: useE } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "scene": "default",
  "showRight": true,
  "leftHidden": false,
  "rightHidden": false
}/*EDITMODE-END*/;

const SCENES = [
  { id:'default',  label:'default' },
  { id:'empty',    label:'empty project' },
  { id:'improve',  label:'/improve running' },
  { id:'review',   label:'review doc' },
  { id:'eval',     label:'eval results' },
  { id:'publish_check', label:'publish check' },
  { id:'publish_key',   label:'key reveal' },
];

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [scene, setScene] = useS(t.scene || 'default');
  useE(()=>{ setScene(t.scene); }, [t.scene]);

  const [composer, setComposer] = useS('');
  const [activeProject, setActiveProject] = useS('invoices');
  const [leftPeek, setLeftPeek] = useS(false); // FS spine in review mode
  const [rightPeek, setRightPeek] = useS(false); // ctx surface in review mode
  const [leftHidden, setLeftHidden] = useS(!!t.leftHidden);
  const [rightHidden, setRightHidden] = useS(!!t.rightHidden);
  useE(()=>{ setLeftHidden(!!t.leftHidden); }, [t.leftHidden]);
  useE(()=>{ setRightHidden(!!t.rightHidden); }, [t.rightHidden]);

  // resizable sidebars
  const LEFT_MIN = 180, LEFT_MAX = 460;
  const RIGHT_MIN = 260, RIGHT_MAX = 600;
  const [leftW, setLeftW]   = useS(()=> { const v = +localStorage.getItem('emerge.leftW'); return v>=LEFT_MIN && v<=LEFT_MAX ? v : 248; });
  const [rightW, setRightW] = useS(()=> { const v = +localStorage.getItem('emerge.rightW'); return v>=RIGHT_MIN && v<=RIGHT_MAX ? v : 360; });
  const [drag, setDrag] = useS(null); // 'left' | 'right' | null
  useE(()=>{ localStorage.setItem('emerge.leftW', String(leftW)); }, [leftW]);
  useE(()=>{ localStorage.setItem('emerge.rightW', String(rightW)); }, [rightW]);
  useE(()=>{
    if (!drag) return;
    function onMove(e){
      const x = e.touches ? e.touches[0].clientX : e.clientX;
      if (drag==='left')  setLeftW(Math.max(LEFT_MIN,  Math.min(LEFT_MAX,  x)));
      if (drag==='right') setRightW(Math.max(RIGHT_MIN, Math.min(RIGHT_MAX, window.innerWidth - x)));
    }
    function onUp(){ setDrag(null); }
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    window.addEventListener('touchmove', onMove, {passive:false});
    window.addEventListener('touchend', onUp);
    return ()=>{
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      window.removeEventListener('touchmove', onMove);
      window.removeEventListener('touchend', onUp);
    };
  }, [drag]);

  const slashOpen = composer.startsWith('/');

  function go(s){ setTweak('scene', s); setScene(s); if (s!=='review') { setLeftPeek(false); setRightPeek(false); } }
  function toggleLeft(){ const nv = !leftHidden; setLeftHidden(nv); setTweak('leftHidden', nv); }
  function toggleRight(){ const nv = !rightHidden; setRightHidden(nv); setTweak('rightHidden', nv); }

  const isReview = scene==='review';
  let shellClass = 'shell';
  if (isReview) {
    if (leftPeek && rightPeek) shellClass = 'shell';
    else if (leftPeek) shellClass = 'shell no-right';
    else if (rightPeek) shellClass = 'shell no-left';
    else shellClass = 'shell solo';
  } else {
    if (leftHidden && rightHidden) shellClass = 'shell solo';
    else if (leftHidden) shellClass = 'shell no-left';
    else if (rightHidden) shellClass = 'shell no-right';
  }

  // Compute effective sidebar widths. When a side is hidden/solo, the inline
  // style would otherwise override the .shell.solo / .shell.no-left|right CSS
  // rules and the middle column wouldn't expand. So zero them here directly.
  const leftCollapsed  = shellClass.indexOf('no-left')  !== -1 || shellClass.indexOf('solo') !== -1;
  const rightCollapsed = shellClass.indexOf('no-right') !== -1 || shellClass.indexOf('solo') !== -1;
  const shellStyle = {
    '--left-w':  (leftCollapsed  ? 0 : leftW)  + 'px',
    '--right-w': (rightCollapsed ? 0 : rightW) + 'px',
  };
  const fullShellClass = shellClass + (drag ? ' dragging' : '');

  function startDrag(side, e){ e.preventDefault(); setDrag(side); }

  return (
    <>
      <div className={fullShellClass} style={shellStyle}>
        <div className="resizer left"
             onMouseDown={(e)=>startDrag('left', e)}
             onTouchStart={(e)=>startDrag('left', e)}
             title="Drag to resize"></div>
        <div className="resizer right"
             onMouseDown={(e)=>startDrag('right', e)}
             onTouchStart={(e)=>startDrag('right', e)}
             title="Drag to resize"></div>
        <Topbar
          projectName={activeProject + '/'}
          improveRunning={scene==='improve'}
          onToggleImprove={()=>go('improve')}
          leftHidden={isReview ? !leftPeek : leftHidden}
          rightHidden={isReview ? !rightPeek : rightHidden}
          onToggleLeft={isReview ? (()=>setLeftPeek(v=>!v)) : toggleLeft}
          onToggleRight={isReview ? (()=>setRightPeek(v=>!v)) : toggleRight}
        />
        <FSSpine activeProject={activeProject} onSwitchProject={(id)=>{
          setActiveProject(id);
          if (id==='forms') go('empty'); else if (scene==='empty') go('default');
        }}/>
        <div className="conv">
          {scene !== 'review' && (
            <ConvHeader activeProject={activeProject} onNew={()=>go('empty')} />
          )}
          {scene==='default'   && <DefaultConversation onReview={()=>go('review')} onEval={()=>go('eval')} onPublish={()=>go('publish_check')} onImprove={()=>go('improve')} />}
          {scene==='empty'     && <EmptyHero onInit={()=>go('default')} />}
          {scene==='improve'   && <ImproveConversation onReview={()=>go('review')} />}
          {scene==='eval'      && <EvalConversation onImprove={()=>go('improve')} />}
          {scene==='publish_check' && <PublishStage stage="check" onAdvance={()=>go('publish_key')} onClose={()=>go('default')} />}
          {scene==='publish_key'   && <PublishStage stage="key"   onClose={()=>go('default')} />}
          {scene==='review'    && <ReviewOverlay onBack={()=>go('default')} leftPeek={leftPeek} setLeftPeek={setLeftPeek} rightPeek={rightPeek} setRightPeek={setRightPeek} />}

          {scene !== 'review' && scene !== 'publish_check' && scene !== 'publish_key' && (
            <Composer value={composer} onChange={setComposer} slashOpen={slashOpen} onSlash={(c)=>setComposer(c+' ')} />
          )}
          {scene==='improve' && <ImproveBanner pct={62} onOpen={()=>{}} />}
        </div>
        <ContextSurface />
      </div>

      {/* quick scene switcher (visible without opening tweaks) */}
      <div className="twk-quick">
        {SCENES.map(s => (
          <button key={s.id}
                  className={'qbtn ' + (scene===s.id ? 'active':'')}
                  onClick={()=>go(s.id)}>
            {s.label}
          </button>
        ))}
      </div>

      <TweaksPanel>
        <TweakSection label="Scene" />
        <TweakSelect label="Active state" value={scene}
                     options={SCENES.map(s=>({value:s.id,label:s.label}))}
                     onChange={(v)=>go(v)} />
        <TweakSection label="Notes" />
        <div style={{fontSize:11,lineHeight:1.5,color:'rgba(41,38,27,.65)'}}>
          The visible buttons in the bottom-left switch the same scene. They’re kept on-canvas so reviewers don’t need to open Tweaks to flip through states.
        </div>
      </TweaksPanel>
    </>
  );
}

// ─────────── empty hero ───────────
function EmptyHero({ onInit }) {
  const STARTERS = [
    'Extract invoices from these PDFs — vendor, totals, line items',
    'Build me a schema, then I’ll edit it before extraction',
    'Pull contract terms — parties, effective date, renewal clause',
  ];
  return (
    <div className="empty-hero">
      <div className="ey">~/projects/tax-forms/</div>
      <h1>An empty folder, a willing agent, <em>and a stack of PDFs.</em></h1>
      <p>Drop documents in. Tell the agent what you want. It’ll derive a schema, run the first extractions, and come back to you for review.</p>
      <div className="invite">
        <span className="cmd">/init</span>
        <span style={{color:'var(--ink-3)'}}>derive a schema from the first few documents</span>
        <span style={{color:'var(--ink-5)',marginLeft:'auto'}}>↵</span>
      </div>
      <div className="drop">
        <b>drop PDFs or images here</b>
        <span>or run <span style={{color:'var(--ochre-2)',fontWeight:500}}>cp ~/Downloads/*.pdf docs/</span></span>
      </div>
      <div className="starters">
        <div className="lbl">or try saying ·</div>
        {STARTERS.map((s,i)=>(
          <button key={i} className="starter" onClick={onInit}>
            <span className="quote">“</span>
            <span>{s}</span>
            <span className="arr">↵</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ─────────── default conversation ───────────
function DefaultConversation({ onReview, onEval, onPublish, onImprove }) {
  return (
    <div className="conv-scroll">
      <div className="conv-inner">

        <Turn who="you" ts="14:02">
          <div className="msg user">I dropped a quarter of invoices into <code>docs/</code>. Make me an extraction API for them.</div>
        </Turn>

        <Turn who="agent" ts="14:02">
          <div className="msg">
            <p>I’ll start by reading a handful, deriving a candidate schema, and writing it to <code>schema.json</code>. We can edit it together once it’s on disk.</p>
          </div>
          <ToolStack
            steps={[
              {name:'read_documents', args:'docs/*.pdf, sample=4'},
              {name:'derive_schema',  args:'from=4 sampled docs'},
              {name:'write_file',     args:'schema.json'},
            ]}
            state="done"
            totalDur="13.6s"
            open={false}
          >
          <ToolCall name="read_documents" args="docs/*.pdf, sample=4" status="done" dur="2.1s" open={true}>
            <ToolRow glyph="·" label="2024-Q3-acme.pdf"     value="2 pages · 14kb text" />
            <ToolRow glyph="·" label="2024-Q3-globex.pdf"   value="3 pages · 21kb text" />
            <ToolRow glyph="·" label="2024-Q3-soylent.pdf"  value="2 pages · 18kb text" />
            <ToolRow glyph="·" label="2024-Q4-acme.pdf"     value="2 pages · 14kb text" />
          </ToolCall>

          <ToolCall name="derive_schema" args="from=4 sampled docs, with_descriptions=true" status="done" dur="11.4s" open={true}>
            <ToolRow glyph="↳" label="invoice_number"  value="string · printed at top" />
            <ToolRow glyph="↳" label="issue_date"      value="date · ISO 8601" />
            <ToolRow glyph="↳" label="vendor_name"     value="string · legal name of supplier" />
            <ToolRow glyph="↳" label="line_items[]"    value="array · billable rows + sub-schema" />
            <ToolRow glyph="↳" label="+ 10 more fields" mini="object · array · numbers" />
          </ToolCall>

          <ToolCall name="write_file" args="schema.json (14 fields, 1.2kb)" status="done" dur="0.1s" />
          </ToolStack>

          <div className="msg" style={{marginTop:12}}>
            <p>Schema is on disk. I ran a first-pass extraction across all 42 docs while we were talking — confidence is 87% overall. <strong style={{fontWeight:500,color:'var(--ochre-2)'}}>Three documents</strong> have low-confidence fields I’d like you to look at first.</p>
          </div>

          <ToolCall name="extract_batch" args="docs/*.pdf, schema=v0, n=42" status="done" dur="3m 12s" open={false}>
            <ToolRow glyph="·" label="38 documents extracted cleanly" />
            <ToolRow glyph="·" label="3 documents flagged for review" mini="low conf" />
            <ToolRow glyph="·" label="1 document failed" mini="OCR" />
          </ToolCall>

          <div style={{display:'flex',gap:8,marginTop:8}}>
            <button className="t-btn primary" style={{padding:'7px 14px',fontFamily:'var(--mono)',fontSize:11.5}} onClick={onReview}>review 2024-Q4-acme.pdf →</button>
            <button className="t-btn" style={{padding:'7px 14px',fontFamily:'var(--mono)',fontSize:11.5}} onClick={onEval}>show eval scores</button>
          </div>
        </Turn>

        <Turn who="you" ts="14:08">
          <div className="msg user">I reviewed three. Where am I weak?</div>
        </Turn>

        <Turn who="agent" ts="14:08">
          <div className="msg">
            <p>Two fields are dragging the average down: <code>line_items[]</code> at 0.72 F1 (multi-page tables) and <code>vendor_tax_id</code> at 0.77 (formatting drift). Both look like description problems, not model problems.</p>
          </div>
          <div style={{display:'flex',gap:8,marginTop:4}}>
            <button className="t-btn" style={{padding:'7px 14px',fontFamily:'var(--mono)',fontSize:11.5}} onClick={onEval}>see full eval</button>
            <button className="t-btn primary" style={{padding:'7px 14px',fontFamily:'var(--mono)',fontSize:11.5}} onClick={onImprove}>/improve descriptions →</button>
            <button className="t-btn" style={{padding:'7px 14px',fontFamily:'var(--mono)',fontSize:11.5}} onClick={onPublish}>/publish anyway</button>
          </div>
        </Turn>

      </div>
    </div>
  );
}

// ─────────── improve conversation ───────────
function ImproveConversation({ onReview }) {
  const [accepted, setAccepted] = useS({});
  return (
    <div className="conv-scroll">
      <div className="conv-inner">

        <Turn who="you" ts="14:11">
          <div className="msg user">/improve — focus on the bottom three fields.</div>
        </Turn>

        <Turn who="agent" ts="14:11">
          <div className="msg">
            <p>Working on it. I’ll generate candidate descriptions, run them against <code>reviewed/</code>, and surface only the ones that move F1. Feel free to switch projects — I’ll keep going.</p>
          </div>

          <ToolCall name="autoresearch" args="targets=[line_items[], vendor_tax_id, notes, due_date]" status="run" open={true}
            footer={<div className="t-foot">
              <button className="t-btn danger">cancel</button>
              <button className="t-btn">pause</button>
              <span style={{marginLeft:'auto',fontFamily:'var(--mono)',fontSize:11,color:'var(--ink-4)',alignSelf:'center'}}>est. 4 min remaining</span>
            </div>}
          >
            <div className="t-bar"><i style={{width:'62%'}}></i></div>
            <ToolRow glyph="✓" label="line_items[]"    value="2 candidates · best +0.18 F1" mini="done" />
            <ToolRow glyph="↻" label="vendor_tax_id"   value="searching… 12 variants tried" mini="running" />
            <ToolRow glyph="·" label="notes"           value="queued" />
            <ToolRow glyph="·" label="due_date"        value="queued" />
          </ToolCall>

          <div className="msg" style={{marginTop:12}}>
            <p>First candidate is in. Take a look — these don’t apply until you accept.</p>
          </div>

          {IMPROVE_CANDIDATES.slice(0,2).map(c => (
            <ToolCall key={c.field}
                      name="propose_description"
                      args={'field='+c.field+', delta='+c.delta}
                      status="cand"
                      open={true}
                      footer={<div className="t-foot">
                        <button className={'t-btn '+(accepted[c.field]?'':'primary')}
                                onClick={()=>setAccepted(s=>({...s,[c.field]:!s[c.field]}))}>
                          {accepted[c.field] ? 'accepted ✓' : 'accept'}
                        </button>
                        <button className="t-btn">edit</button>
                        <button className="t-btn danger">reject</button>
                        <span style={{marginLeft:'auto',fontFamily:'var(--mono)',fontSize:11,color:'var(--moss)',alignSelf:'center'}}>{c.delta}</span>
                      </div>}>
              <div className="diff">
                <div className="row">
                  <span className="field">description</span>
                  <span className="col">
                    <span className="old">{c.oldDesc}</span>
                    <span className="new">{c.newDesc}</span>
                  </span>
                </div>
              </div>
            </ToolCall>
          ))}
        </Turn>

      </div>
    </div>
  );
}

// ─────────── eval conversation ───────────
function EvalConversation({ onImprove }) {
  return (
    <div className="conv-scroll">
      <div className="conv-inner">

        <Turn who="you" ts="14:09">
          <div className="msg user">/eval</div>
        </Turn>

        <Turn who="agent" ts="14:09">
          <div className="msg">
            <p>Scored the current schema (v3 draft) against the 5 documents in <code>reviewed/</code>. Wrote results to <code>metrics/eval_2025-05-09.json</code>.</p>
          </div>
          <ToolCall name="run_eval" args="schema=v3-draft, against=reviewed/*.json (n=5)" status="done" dur="44s" open={true}>
            <ToolRow glyph="·" label={<span className="term" title="F1 — harmonic mean of precision & recall, scored against the reviewed/ folder. 1.0 = perfect.">overall F1</span>} value="0.914" mini="↑ from 0.873" />
            <ToolRow glyph="·" label="fields ≥ 0.90" value="9 of 14" />
            <ToolRow glyph="·" label="fields < 0.80" value="3 of 14" mini="needs work" />
          </ToolCall>

          <EvalCard />

          <div className="msg" style={{marginTop:12}}>
            <p>Three fields are below 0.80 — all of them look like description issues. Want me to <code>/improve</code> them in the background while you keep reviewing?</p>
          </div>
          <div style={{display:'flex',gap:8,marginTop:4}}>
            <button className="t-btn primary" style={{padding:'7px 14px',fontFamily:'var(--mono)',fontSize:11.5}} onClick={onImprove}>/improve those three →</button>
            <button className="t-btn" style={{padding:'7px 14px',fontFamily:'var(--mono)',fontSize:11.5}}>open metrics/</button>
          </div>
        </Turn>

      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
