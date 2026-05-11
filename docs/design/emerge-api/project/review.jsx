// review.jsx — review overlay (PDF + grouped, collapsible field editor)

const { useState: useStateR, useMemo: useMemoR, useEffect: useEffectR, useRef: useRefR } = React;

// ─────────── helpers ───────────
function confDotFor(lab){ return lab==='low'?'low':lab==='mid'?'mid':'high'; }
function confTagFor(lab){
  if (lab==='low') return <span className="ctag low">low conf</span>;
  if (lab==='mid') return <span className="ctag mid">mid conf</span>;
  return null;
}

// Flat / sub field row — used for top-level scalars AND for nested sub-fields.
function FieldRow({ f, parentName, edits, setEdits, notes, setNotes, onActivate, activeField, nested }) {
  const path = parentName ? parentName + '.' + f.name : f.name;
  const editedVal = edits[path];
  const finalVal = editedVal != null ? editedVal : f.val;
  const isEdited = editedVal != null;
  const note = notes[path];
  // Activation is path-based so nested fields work too. Top-level fields still match by bare name.
  const isActive = activeField === path || activeField === f.name;
  return (
    <div className={'rev-fld '+(nested?'nested ':'')+(isActive?'active ':'')}
         onClick={(e)=>{e.stopPropagation(); onActivate && onActivate(path);}}
         title={'confidence '+(f.conf*100).toFixed(0)+'%'}>
      <div className="kv">
        <div className="ktop">
          <span className={'cdot '+confDotFor(f.confLab)}></span>
          <span className="name">{f.name}</span>
        </div>
        <div className="valwrap">
          <div
            className={'val '+(isEdited?'edited':'')}
            contentEditable suppressContentEditableWarning
            onBlur={e=>setEdits(s=>({...s,[path]:e.target.textContent}))}
          >{finalVal}</div>
          {isEdited && <span className="edstamp" title="edited">●</span>}
        </div>
      </div>
      {(note || isActive) && (
        <div
          className="notes"
          contentEditable suppressContentEditableWarning
          onBlur={e=>setNotes(s=>({...s,[path]:e.target.textContent}))}
        >{note||''}</div>
      )}
    </div>
  );
}

// Object field — collapsed shows summary row; expanded reveals sub-fields.
function ObjectField({ f, edits, setEdits, notes, setNotes, onActivate, activeField, forceOpen }) {
  const [open, setOpen] = useStateR(false);
  useEffectR(()=>{ if (forceOpen!==null) setOpen(forceOpen); }, [forceOpen]);
  const isActive = activeField === f.name;
  return (
    <div className={'rev-obj '+(open?'open ':'')+(isActive?'active ':'')}
         onClick={()=>onActivate && onActivate(f.name)}>
      <div className="objhead" onClick={(e)=>{e.stopPropagation();setOpen(o=>!o);}}>
        <span className={'cdot '+confDotFor(f.confLab)}></span>
        <span className="name">{f.name}</span>
        <span className="ty">object · {f.sub.length} keys</span>
        {!open && <span className="objsum">{f.summary}</span>}
        <span className="caret">{open?'▾':'▸'}</span>
      </div>
      {open && (
        <div className="objbody">
          {f.sub.map(sf => (
            <FieldRow key={sf.name} f={sf} parentName={f.name}
                      edits={edits} setEdits={setEdits}
                      notes={notes} setNotes={setNotes}
                      onActivate={onActivate} activeField={activeField}
                      nested />
          ))}
        </div>
      )}
    </div>
  );
}

// Array field — stack of row-cards. Each row is a tiny collapsible card.
function ArrayField({ f, edits, setEdits, notes, setNotes, onActivate, activeField, forceOpen }) {
  const isActive = activeField === f.name;
  // keys: per-row index -> bool. forceOpen=true → all open, false → all closed.
  const [openRows, setOpenRows] = useStateR(()=>{
    const o = {}; f.rows.forEach((r,i)=>{ if (r._warn) o[i]=true; });
    return o;
  });
  useEffectR(()=>{
    if (forceOpen===null) return;
    const o = {}; f.rows.forEach((_,i)=>{ o[i]=forceOpen; });
    setOpenRows(o);
  }, [forceOpen]);
  return (
    <div className={'rev-arr '+(isActive?'active ':'')}
         onClick={()=>onActivate && onActivate(f.name)}>
      <div className="arrhead">
        <span className={'cdot '+confDotFor(f.confLab)}></span>
        <span className="name">{f.name}</span>
        <span className="ty">array · {f.rows.length} rows</span>
        <span className="actions">
          <button className="rowbtn" onClick={(e)=>e.stopPropagation()}>⟳ re-parse</button>
          <button className="rowbtn">+ row</button>
        </span>
      </div>
      <div className="arrlist">
        {f.rows.map((r, i) => {
          const open = !!openRows[i];
          return (
            <div key={i} className={'rcard '+(open?'open ':'')+(r._warn?'warn ':'')}>
              <div className="rhead" onClick={(e)=>{e.stopPropagation();setOpenRows(s=>({...s,[i]:!s[i]}));}}>
                <span className="ix">{String(i+1).padStart(2,'0')}</span>
                <span className="rsum">{r._summary}</span>
                {r._warn && <span className="rwarn">{r._warn}</span>}
                <span className="ramt">{r._amount}</span>
                <span className="caret">{open?'▾':'▸'}</span>
              </div>
              {open && (
                <div className="rbody">
                  {r.sub.map(sf => (
                    <FieldRow key={sf.name} f={sf}
                              parentName={f.name+'['+i+']'}
                              edits={edits} setEdits={setEdits}
                              notes={notes} setNotes={setNotes}
                              onActivate={onActivate} activeField={activeField}
                              nested />
                  ))}
                  <div className="rfoot">
                    <button className="rowbtn">duplicate</button>
                    <button className="rowbtn danger">delete row</button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────── section ───────────
function Section({ s, edits, setEdits, notes, setNotes, activeField, setActiveField, forceOpen }) {
  const [open, setOpen] = useStateR(true);
  useEffectR(()=>{ if (forceOpen!==null) setOpen(forceOpen); }, [forceOpen]);
  const flagged = s.fields.reduce((n,f) => n + ((f.confLab==='low'||f.confLab==='mid')?1:0), 0);
  const total = s.fields.length;
  return (
    <div className={'rev-sect '+(open?'open ':'')}>
      <div className="sect-h" onClick={()=>setOpen(o=>!o)}>
        <span className="caret">{open?'▾':'▸'}</span>
        <span className="lab">{s.label}</span>
        <span className="cnt">{total} {total===1?'field':'fields'}</span>
      </div>
      {open && (
        <div className="sect-body">
          {s.fields.map(f => {
            if (f.type==='object') return (
              <ObjectField key={f.name} f={f}
                           edits={edits} setEdits={setEdits}
                           notes={notes} setNotes={setNotes}
                           onActivate={setActiveField}
                           activeField={activeField}
                           forceOpen={forceOpen}/>
            );
            if (f.type==='array') return (
              <ArrayField key={f.name} f={f}
                          edits={edits} setEdits={setEdits}
                          notes={notes} setNotes={setNotes}
                          onActivate={setActiveField}
                          activeField={activeField}
                          forceOpen={forceOpen}/>
            );
            return (
              <FieldRow key={f.name} f={f}
                        edits={edits} setEdits={setEdits}
                        notes={notes} setNotes={setNotes}
                        onActivate={setActiveField}
                        activeField={activeField}/>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─────────── JSON view ───────────
function buildJsonFromSections(sections, edits) {
  const out = {};
  sections.forEach(s => {
    s.fields.forEach(f => {
      if (f.type==='object') {
        const o = {};
        f.sub.forEach(sf => {
          const path = f.name+'.'+sf.name;
          o[sf.name] = edits[path] != null ? edits[path] : sf.val;
        });
        out[f.name.replace('[]','')] = o;
      } else if (f.type==='array') {
        const arr = f.rows.map((r,i) => {
          const o = {};
          r.sub.forEach(sf => {
            const path = f.name+'['+i+'].'+sf.name;
            o[sf.name] = edits[path] != null ? edits[path] : sf.val;
          });
          return o;
        });
        out[f.name.replace('[]','')] = arr;
      } else {
        out[f.name] = edits[f.name] != null ? edits[f.name] : f.val;
      }
    });
  });
  return out;
}

function JsonView({ sections, edits, activeField }) {
  const obj = useMemoR(()=>buildJsonFromSections(sections, edits), [sections, edits]);
  const text = JSON.stringify(obj, null, 2);
  return <div className="rev-json"><pre dangerouslySetInnerHTML={{__html: highlightJson(text, activeField)}}></pre></div>;
}

function highlightJson(text, activeField) {
  const lines = text.split('\n');
  return lines.map((line, i) => {
    let html = line
      .replace(/[&]/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    html = html.replace(/(&quot;|")(?:[^"\\]|\\.)*?(&quot;|")(\s*:)?/g, (m) => {
      const colonMatch = m.match(/:\s*$/);
      const isKey = !!colonMatch;
      const kname = m.replace(/^"|"\s*:?\s*$/g,'').replace(/^"|"$/g,'');
      const activeCls = isKey && activeField && (kname===activeField || kname===activeField.replace('[]','')) ? ' active' : '';
      const cls = isKey ? 'jk'+activeCls : 'js';
      const inner = isKey ? m.replace(/:\s*$/,'') : m;
      return '<span class="'+cls+'">'+inner+'</span>'+(isKey?':':'');
    });
    // numbers
    html = html.replace(/(:\s*)(-?\d+\.?\d*)(\b)/g, '$1<span class="jn">$2</span>$3');
    // booleans / null
    html = html.replace(/(:\s*)(true|false|null)(\b)/g, '$1<span class="jb">$2</span>$3');
    return '<div class="jl"><span class="ln">'+String(i+1).padStart(3,' ')+'</span><span class="jc">'+html+'</span></div>';
  }).join('');
}

// ─────────── doc viewer (unified PDF + image shell) ───────────
const DOC_FILES = [
  { id:'invoice-pdf', name:'2024-Q4-acme.pdf', type:'pdf',   pages:2 },
  { id:'receipt-img', name:'receipt-scan.jpg', type:'image', pages:1 },
];

function IconBtn({ title, onClick, disabled, on, children }) {
  return (
    <button className={'dv-btn '+(on?'on':'')} title={title} onClick={onClick} disabled={disabled}>
      {children}
    </button>
  );
}

function DocViewer({ activeField, file, onPickFile }) {
  const [page, setPage] = useStateR(1);    // current "in view" page, derived from scroll
  const [zoom, setZoom] = useStateR(1);
  const [rot, setRot] = useStateR(0);   // 0/90/180/270
  const [fit, setFit] = useStateR(true); // boolean — fit-to-width on/off
  const [pickerOpen, setPickerOpen] = useStateR(false);
  const viewportRef = React.useRef(null);
  const pageRefs = React.useRef({});

  // reset when file changes
  useEffectR(()=>{ setPage(1); setZoom(1); setRot(0); setFit(true); }, [file.id]);

  // auto-scroll viewport to the page containing the active field
  useEffectR(()=>{
    if (file.type!=='pdf') return;
    const targetPage = ['subtotal','tax','total','payment_terms','currency'].includes(activeField) ? 2 : 1;
    const el = pageRefs.current[targetPage];
    const vp = viewportRef.current;
    if (el && vp) {
      const top = el.offsetTop - 14;
      vp.scrollTo({ top, behavior: 'smooth' });
    }
  }, [activeField, file.type]);

  // observe scroll to update current page indicator
  useEffectR(()=>{
    const vp = viewportRef.current;
    if (!vp) return;
    function onScroll(){
      let best = 1, bestDist = Infinity;
      for (let i=1; i<=file.pages; i++){
        const el = pageRefs.current[i];
        if (!el) continue;
        const dist = Math.abs(el.offsetTop - vp.scrollTop - 20);
        if (dist < bestDist){ bestDist = dist; best = i; }
      }
      setPage(best);
    }
    vp.addEventListener('scroll', onScroll, {passive:true});
    return ()=>vp.removeEventListener('scroll', onScroll);
  }, [file.id, file.pages]);

  function jumpToPage(p){
    const el = pageRefs.current[p];
    const vp = viewportRef.current;
    if (el && vp) vp.scrollTo({ top: el.offsetTop - 14, behavior: 'smooth' });
  }
  function bumpZoom(d){ const base = fit ? fitZoom : zoom; setFit(false); setZoom(Math.max(0.2, Math.min(3, +(base + d).toFixed(2)))); }
  function rotate(dir){ setRot(r => (r + (dir>0?90:-90) + 360) % 360); }

  // Page base dimensions (must match .dv-pagewrap width + each page's natural height)
  const PAGE_W = 680;
  const PDF_H = 880;   // 8.5/11 aspect from 680 → ~880
  const IMG_H = 510;   // 4/3 aspect
  const isRot = rot !== 0;
  // fit-to-width = scale the rotated page's current width to the viewport's
  // inner width. When rotated 90/270 the page's "width" on screen is its
  // original height — so fit must shrink (or grow) to accommodate that.
  const [vpW, setVpW] = useStateR(PAGE_W);
  useEffectR(()=>{
    const vp = viewportRef.current; if (!vp) return;
    const measure = ()=>{
      const cs = getComputedStyle(vp);
      const padL = parseFloat(cs.paddingLeft)||0;
      const padR = parseFloat(cs.paddingRight)||0;
      setVpW(Math.max(120, vp.clientWidth - padL - padR));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(vp);
    return ()=>ro.disconnect();
  }, [file.id]);
  // Fit uses the WIDEST page on the stack so PDF + image share a scale.
  const naturalWFor = (t)=> t==='pdf' ? (isRot ? PDF_H : PAGE_W) : (isRot ? IMG_H : PAGE_W);
  const fitZoom = Math.min(3, Math.max(0.2, +(vpW / naturalWFor(file.type)).toFixed(3)));
  const effZoom = fit ? fitZoom : zoom;
  // Translate after rotation to keep top-left-origin content inside the sizer.
  function wrapXform(h){
    const W = PAGE_W * effZoom, H = h * effZoom;
    let tx = 0, ty = 0;
    if (rot===90)  { tx = H; ty = 0; }
    else if (rot===180){ tx = W; ty = H; }
    else if (rot===270){ tx = 0; ty = W; }
    return `translate(${tx}px, ${ty}px) rotate(${rot}deg) scale(${effZoom})`;
  }
  function sizerStyle(h){
    const w = isRot ? h : PAGE_W;
    const ht = isRot ? PAGE_W : h;
    return { width: w*effZoom + 'px', height: ht*effZoom + 'px' };
  }

  return (
    <>
      <div className="dv-toolbar">
        <button className="dv-file" onClick={()=>setPickerOpen(o=>!o)} title={'switch file · '+file.name}>
          <span className="ftype">{file.type}</span>
          <span className="fcaret">▾</span>
        </button>
        {pickerOpen && (
          <div className="dv-files" onMouseLeave={()=>setPickerOpen(false)}>
            {DOC_FILES.map(f => (
              <div key={f.id}
                   className={'opt '+(f.id===file.id?'active':'')}
                   onClick={()=>{onPickFile(f); setPickerOpen(false);}}>
                <span className="ftype">{f.type}</span>
                <span className="fname">{f.name}</span>
                {f.id===file.id && <span style={{color:'var(--ochre-2)',fontSize:10}}>●</span>}
              </div>
            ))}
          </div>
        )}

        <span className="dv-sep"></span>

        {/* page nav — jumps within the continuous scroll */}
        <IconBtn title="previous page" disabled={page<=1 || file.pages<=1} onClick={()=>jumpToPage(Math.max(1,page-1))}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="9,3 4,7 9,11"/></svg>
        </IconBtn>
        <span className="dv-page">
          <input value={page} onChange={e=>{
            const v = parseInt(e.target.value)||1;
            jumpToPage(Math.max(1, Math.min(file.pages, v)));
          }} disabled={file.pages<=1} />
          <span className="of">/</span>
          <span className="tot">{file.pages}</span>
        </span>
        <IconBtn title="next page" disabled={page>=file.pages || file.pages<=1} onClick={()=>jumpToPage(Math.min(file.pages,page+1))}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="5,3 10,7 5,11"/></svg>
        </IconBtn>

        <span className="dv-sep"></span>

        {/* zoom */}
        <div className="dv-zoom">
          <button onClick={()=>bumpZoom(-0.1)} title="zoom out">−</button>
          <span className="lvl">{Math.round(effZoom*100)}%</span>
          <button onClick={()=>bumpZoom(+0.1)} title="zoom in">+</button>
        </div>
        {/* fit-to-width: ACTIVE when off (so click = activate). Active = subtle accent, not black. */}
        <IconBtn title={fit ? 'fit to width (on)' : 'fit to width'} on={!fit} onClick={()=>{ if (fit){ setZoom(fitZoom); setFit(false);} else { setFit(true);} }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="3" width="10" height="8" rx="1"/>
            <polyline points="4.5,6 3,7.5 4.5,9"/>
            <polyline points="9.5,6 11,7.5 9.5,9"/>
            <line x1="3" y1="7.5" x2="11" y2="7.5"/>
          </svg>
        </IconBtn>

        <span className="dv-sep"></span>

        {/* rotate */}
        <IconBtn title="rotate left 90°" onClick={()=>rotate(-1)}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 7a4 4 0 1 1 1.2 2.85"/>
            <polyline points="3,4 3,7 6,7"/>
          </svg>
        </IconBtn>
        <IconBtn title="rotate right 90°" onClick={()=>rotate(+1)}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 7a4 4 0 1 0 -1.2 2.85"/>
            <polyline points="11,4 11,7 8,7"/>
          </svg>
        </IconBtn>

        <span className="dv-spacer"></span>

        <IconBtn title="download original">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 2v7"/><polyline points="4,6 7,9 10,6"/><path d="M3 11h8"/>
          </svg>
        </IconBtn>
      </div>

      <div className="dv-viewport" ref={viewportRef}>
        <div className="dv-stack">
          {file.type === 'pdf' && (
            <div className="dv-sizer" style={sizerStyle(PDF_H)}>
            <div ref={el=>pageRefs.current[1]=el} className={'dv-pagewrap '+(isRot?'is-rot':'')} style={{transform: wrapXform(PDF_H)}}>
              <div className="rev-page">
                <div className="pgnum">page 1 / {file.pages}</div>
                <div className="pgcontent">
                  <h3>ACME CORP. — Invoice <span className={'hi '+(activeField==='invoice_number'?'active':'')}>ACM-2024-1187</span></h3>
                  <p className="ll"><span className="lbl">Issued:</span> <span className={'hi '+(activeField==='issue_date'?'active':'')}>October 14, 2024</span></p>
                  <p className="ll"><span className="lbl">Due:</span> <span className={'hi '+(activeField==='due_date'?'active':'')}>Net 30 from receipt</span></p>
                  <p className="ll"><span className="lbl">EIN:</span> <span className={'hi '+(activeField==='vendor_tax_id'?'active':'')}>82-3214567</span></p>
                  <p className="ll"><span className="lbl">Bill To:</span> <span className={'hi '+(activeField==='bill_to'?'active':'')}>Globex Industries, 4400 Forbes Ave, Pittsburgh PA 15213</span></p>
                  <p className="ll"><span className="lbl">PO #:</span> <span className={'hi '+(activeField==='po_number'?'active':'')}>GBX-PO-44219</span></p>
                  <p className="ll" style={{marginTop:18}}><i>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Suspendisse potenti. Praesent ac nisl auctor, vehicula nisl ut, lacinia neque.</i></p>
                  <table>
                    <thead><tr><th>Description</th><th>Qty</th><th>Rate</th><th>Amount</th></tr></thead>
                    <tbody>
                      <tr className={activeField==='line_items[]'?'rowhi':''}><td>Consulting hours, October 2024</td><td>120</td><td>$110.00</td><td>$13,200.00</td></tr>
                      <tr className={activeField==='line_items[]'?'rowhi':''}><td>On-site travel</td><td>4</td><td>$255.00</td><td>$1,020.00</td></tr>
                      <tr className={activeField==='line_items[]'?'rowhi':''}><td>Volume discount (Net 30)</td><td>—</td><td>—</td><td>−$0.00</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
            </div>
          )}
          {file.type === 'pdf' && (
            <div className="dv-sizer" style={sizerStyle(PDF_H)}>
            <div ref={el=>pageRefs.current[2]=el} className={'dv-pagewrap '+(isRot?'is-rot':'')} style={{transform: wrapXform(PDF_H)}}>
              <div className="rev-page">
                <div className="pgnum">page 2 / {file.pages}</div>
                <div className="pgcontent">
                  <h3>Continued — totals</h3>
                  <table>
                    <tbody>
                      <tr><td>Subtotal</td><td className={'hi '+(activeField==='subtotal'?'active':'')}>$14,820.00</td></tr>
                      <tr><td>Tax (7%)</td><td className={'hi '+(activeField==='tax'?'active':'')}>$1,037.40</td></tr>
                      <tr><td><b>Total Due</b></td><td className={'hi '+(activeField==='total'?'active':'')}><b>$15,857.40</b></td></tr>
                    </tbody>
                  </table>
                  <p className="ll" style={{marginTop:18}}><span className="lbl">Terms:</span> <span className={'hi '+(activeField==='payment_terms'?'active':'')}>Net 30</span>. Late payments accrue 1.5% interest monthly.</p>
                  <p className="ll"><span className="lbl">Currency:</span> <span className={'hi '+(activeField==='currency'?'active':'')}>USD</span></p>
                </div>
              </div>
            </div>
            </div>
          )}
          {file.type === 'image' && (
            <div className="dv-sizer" style={sizerStyle(IMG_H)}>
            <div ref={el=>pageRefs.current[1]=el} className={'dv-pagewrap '+(isRot?'is-rot':'')} style={{transform: wrapXform(IMG_H)}}>
            <div className="dv-imgpage">
              <div className="pgnum">scan · 2400×1800</div>
              <svg className="placeholder" viewBox="0 0 400 300" preserveAspectRatio="xMidYMid slice">
                <defs>
                  <pattern id="stripes" width="14" height="14" patternUnits="userSpaceOnUse" patternTransform="rotate(35)">
                    <rect width="14" height="14" fill="#F2EFE6"/>
                    <line x1="0" y1="0" x2="0" y2="14" stroke="#E4DFCF" strokeWidth="6"/>
                  </pattern>
                </defs>
                <rect width="400" height="300" fill="url(#stripes)"/>
                <g fontFamily="ui-monospace,Menlo,monospace" fill="#8A877D" fontSize="10">
                  <text x="20" y="32">▢ receipt-scan.jpg · placeholder</text>
                  <text x="20" y="48" fill="#B3B0A5">drop a real image here — same viewer</text>
                </g>
                {/* faux receipt content for evidence highlight demo */}
                <g fontFamily="ui-monospace,Menlo,monospace" fill="#37352E">
                  <text x="60" y="92" fontSize="13" fontWeight="600">CORNER CAFE</text>
                  <text x="60" y="112" fontSize="10">Receipt #4471</text>
                  <text x="60" y="132" fontSize="10">2024-12-03  14:22</text>
                  <text x="60" y="170" fontSize="11">2× Espresso . . . . . $7.50</text>
                  <text x="60" y="190" fontSize="11">1× Croissant . . . . . $4.20</text>
                  <text x="60" y="220" fontSize="12" fontWeight="600">TOTAL  $11.70</text>
                </g>
              </svg>
              {/* evidence boxes overlay the image — coords are % of the box */}
              {activeField==='total' && (
                <div className="imghi" style={{left:'14%', top:'70%', width:'34%', height:'8%'}}>
                  <div className="imghi-lbl">total · evidence</div>
                </div>
              )}
              {activeField==='issue_date' && (
                <div className="imghi" style={{left:'14%', top:'42%', width:'30%', height:'6%'}}>
                  <div className="imghi-lbl">issue_date · evidence</div>
                </div>
              )}
              {activeField==='vendor_name' && (
                <div className="imghi" style={{left:'14%', top:'28%', width:'40%', height:'8%'}}>
                  <div className="imghi-lbl">vendor · evidence</div>
                </div>
              )}
            </div>
            </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ─────────── overlay ───────────
function ReviewOverlay({ onBack, leftPeek, setLeftPeek, rightPeek, setRightPeek }) {
  const [docFile, setDocFile] = useStateR(DOC_FILES[0]);
  const [activeField, setActiveField] = useStateR('due_date');
  const [edits, setEdits] = useStateR({ due_date:'2024-11-14', vendor_tax_id:'823214567' });
  const [notes, setNotes] = useStateR({});
  const [view, setView] = useStateR('form'); // form | json
  const [forceOpen, setForceOpen] = useStateR(null); // null | true | false
  // Reset force after pulse so child useEffect fires; we keep last value sticky for new mounts
  useEffectR(()=>{
    if (forceOpen===null) return;
    const t = setTimeout(()=>{}, 0);
    return ()=>clearTimeout(t);
  }, [forceOpen]);

  const sections = REVIEW_DOC.sections;
  const totalFields = sections.reduce((n,s)=>n + s.fields.length, 0);
  const flaggedCount = sections.reduce((n,s) => n + s.fields.filter(f=>f.confLab!=='high').length, 0);

  // ─── draggable splitter between doc viewer and field editor ───
  const bodyRef = useRefR(null);
  const SPLIT_MIN = 22, SPLIT_MAX = 78; // percent of body width
  const [splitPct, setSplitPct] = useStateR(()=>{
    const v = parseFloat(localStorage.getItem('emerge.revSplit'));
    return (v>=SPLIT_MIN && v<=SPLIT_MAX) ? v : 52;
  });
  const [splitDrag, setSplitDrag] = useStateR(false);
  useEffectR(()=>{ localStorage.setItem('emerge.revSplit', String(splitPct)); }, [splitPct]);
  useEffectR(()=>{
    if (!splitDrag) return;
    function onMove(e){
      const body = bodyRef.current; if (!body) return;
      const rect = body.getBoundingClientRect();
      const x = e.touches ? e.touches[0].clientX : e.clientX;
      const pct = ((x - rect.left) / rect.width) * 100;
      setSplitPct(Math.max(SPLIT_MIN, Math.min(SPLIT_MAX, pct)));
      if (e.cancelable) e.preventDefault();
    }
    function onUp(){ setSplitDrag(false); }
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
  }, [splitDrag]);
  function startSplitDrag(e){ e.preventDefault(); setSplitDrag(true); }

  return (
    <div className="rev-overlay">
      <div className="rev-bar">
        <button className="back" onClick={onBack}>◂ back to chat</button>
        <div className="title">
          reviewing <span className="doc">docs/{REVIEW_DOC.name}</span>
        </div>
        <div className="spacer"></div>
        <div className="rev-toolbar">
          <div className="seg">
            <button className={view==='form'?'on':''} onClick={()=>setView('form')}>form</button>
            <button className={view==='json'?'on':''} onClick={()=>setView('json')}>json</button>
          </div>
          <button className="ghostbtn" onClick={()=>setForceOpen(o=> o===true ? false : true)} title={forceOpen===true?'collapse all':'expand all'}>
            {forceOpen===true ? '⤡' : '⤢'}
          </button>
        </div>
        <div className="nav">
          <span>{flaggedCount}/{totalFields} flagged</span>
          <span className="arrow">◂</span>
          <span className="arrow">▸</span>
        </div>
        <button className="save">save</button>
      </div>
      <div className={'rev-body'+(splitDrag?' dragging':'')}
           ref={bodyRef}
           style={{'--rev-split': splitPct+'%'}}>
        <div className="rev-pdf">
          <DocViewer activeField={activeField} file={docFile} onPickFile={setDocFile} />
        </div>

        <div className={'rev-split'+(splitDrag?' active':'')}
             onMouseDown={startSplitDrag}
             onTouchStart={startSplitDrag}
             onDoubleClick={()=>setSplitPct(52)}
             title="Drag to resize · double-click to reset"></div>

        {view==='form' ? (
          <div className="rev-fields">
            {sections.map(s => (
              <Section key={s.id} s={s}
                       edits={edits} setEdits={setEdits}
                       notes={notes} setNotes={setNotes}
                       activeField={activeField}
                       setActiveField={setActiveField}
                       forceOpen={forceOpen}/>
            ))}
          </div>
        ) : (
          <JsonView sections={sections} edits={edits} activeField={activeField}/>
        )}
      </div>
    </div>
  );
}

// ─────────── eval card ───────────
function EvalCard() {
  const [open, setOpen] = useStateR(null);
  return (
    <div className="eval-card">
      <div className="eh">
        <span className="nm">metrics/eval_2025-05-09.json</span>
        <span className="stamp">5 reviewed · 14 fields · 2h ago</span>
        <span className="agg"><span className="lbl">F1</span>0.914</span>
      </div>
      <div className="eval-row head">
        <span className="f">field</span>
        <span className="num term" title="Precision — of fields the agent extracted, how many matched the reviewed truth">P</span>
        <span className="num term" title="Recall — of fields that should have been extracted, how many it caught">R</span>
        <span className="num term" title="F1 — harmonic mean of precision & recall. 1.0 = perfect, 0.85 = our publish threshold">F1</span>
        <span></span>
      </div>
      {EVAL_ROWS.map(r => (
        <React.Fragment key={r.f}>
          <div className="eval-row" onClick={()=> r.err ? setOpen(o => o===r.f ? null : r.f) : null} style={{cursor: r.err?'default':'auto'}}>
            <span className="f">{r.f} {r.err && <span style={{color:'var(--ochre-2)',marginLeft:6,fontSize:10}}>▾ explain</span>}</span>
            <span className="num">{r.p.toFixed(2)}</span>
            <span className="num">{r.r.toFixed(2)}</span>
            <span className={'num f1 '+r.tone}>{r.f1.toFixed(2)}</span>
            <div className="bar"><i className={r.tone} style={{width:(r.f1*100)+'%'}}></i></div>
          </div>
          {open===r.f && r.err && (
            <div className="eval-row expand">
              <b>{r.f} · {r.f1.toFixed(2)}</b> — {r.err}
            </div>
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

// ─────────── publish stage ───────────
function PublishStage({ stage, onAdvance, onClose }) {
  if (stage === 'check') {
    return (
      <div className="pub-stage">
        <div className="pub-card">
          <div className="pub-eyebrow">readiness check<span className="ln"></span></div>
          <div className="pub-h">Almost ready to <em>publish v3.</em></div>
          <p className="pub-sub">Three checks passed, one wants a glance. Once you confirm, the schema and reviewed examples freeze together — that bundle becomes the API.</p>
          <div className="pub-checks">
            <div className="pub-check ok"><span className="mk">✓</span><span className="lab">Schema covers all reviewed documents</span><span className="det">14/14 fields populated</span></div>
            <div className="pub-check ok"><span className="mk">✓</span><span className="lab">Eval F1 ≥ 0.85 threshold</span><span className="det">0.914 · 2h ago</span></div>
            <div className="pub-check ok"><span className="mk">✓</span><span className="lab">No unresolved /improve candidates</span><span className="det">all accepted or dismissed</span></div>
            <div className="pub-check warn"><span className="mk">!</span><span className="lab">3 documents still pending review</span><span className="det">publish anyway · they won't enter v3</span></div>
          </div>
          <div style={{display:'flex',gap:10,marginTop:6}}>
            <button className="t-btn primary" style={{padding:'10px 16px',fontSize:12}} onClick={onAdvance}>freeze v3 → mint key</button>
            <button className="t-btn" style={{padding:'10px 16px',fontSize:12}} onClick={onClose}>back to chat</button>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="pub-stage">
      <div className="pub-card">
        <div className="pub-eyebrow">v3 frozen · 2025-05-09 14:22 UTC<span className="ln"></span></div>
        <div className="pub-h">Your API is <em>live.</em></div>
        <p className="pub-sub">A snapshot of <code style={{fontFamily:'var(--mono)',fontSize:14,background:'var(--paper-2)',padding:'1px 6px',borderRadius:4}}>schema.json</code> and the 5 reviewed examples is now <code style={{fontFamily:'var(--mono)',fontSize:14,background:'var(--paper-2)',padding:'1px 6px',borderRadius:4}}>versions/v3.json</code>. The agent stops editing it.</p>

          <div className="pub-key">
            <div className="lab2"><span>API key — invoices · v3</span><span className="warn">⚠ shown once</span></div>
            <div className="key">
              <span>emrg_live_pk_8f3a2c1e94b76d05a1f3</span>
              <button className="copy">copy</button>
            </div>
            <div className="one">We never store this key in plaintext. Close this card and it’s gone — you can mint a new one, but you can’t see this one again.</div>
          </div>

          <div className="pub-snip">
<span className="c"># curl your new endpoint</span>{`\n`}
curl https://api.emerge.run/v3/invoices/extract \{`\n`}
{`  `}-H <span className="s">"Authorization: Bearer $EMERGE_KEY"</span> \{`\n`}
{`  `}-F <span className="k">file</span>=@2025-Q1-acme.pdf{`\n`}
{`\n`}
<span className="c"># → returns matching schema.json shape</span>
          </div>

        <div style={{display:'flex',gap:10}}>
          <button className="t-btn primary" style={{padding:'10px 16px',fontSize:12}} onClick={onClose}>done · back to chat</button>
          <button className="t-btn" style={{padding:'10px 16px',fontSize:12}}>view versions/v3.json</button>
        </div>
      </div>
    </div>
  );
}

window.ReviewOverlay = ReviewOverlay;
window.EvalCard = EvalCard;
window.PublishStage = PublishStage;
