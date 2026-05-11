// data.jsx — fixtures for the emerge prototype

const PROJECTS = [
  { id:'invoices', name:'invoices/',     active:true,  meta:'42 docs',  status:'live' },
  { id:'leases',   name:'leases/',       active:false, meta:'18 docs',  status:'draft' },
  { id:'labs',     name:'lab-reports/',  active:false, meta:'7 docs',   status:'draft' },
  { id:'permits',  name:'permits/',      active:false, meta:'124 docs', status:'live' },
  { id:'forms',    name:'tax-forms/',    active:false, meta:'0 docs',   status:'empty' },
];

const TREE = [
  { kind:'dir',  name:'docs/',           depth:0, count:42 },
  { kind:'file', name:'2024-Q3-acme.pdf',           depth:1, stamp:'reviewed' },
  { kind:'file', name:'2024-Q3-globex.pdf',         depth:1, stamp:'reviewed' },
  { kind:'file', name:'2024-Q4-acme.pdf',           depth:1, stamp:'pending'  },
  { kind:'file', name:'2024-Q4-soylent.pdf',        depth:1, stamp:'pending'  },
  { kind:'file', name:'2025-Q1-globex.pdf',         depth:1, stamp:'new'      },
  { kind:'ghost', name:'… 37 more',                  depth:1 },
  { kind:'dir',  name:'reviewed/',       depth:0, count:5 },
  { kind:'file', name:'acme-q3.json',                depth:1, stamp:'v3' },
  { kind:'file', name:'globex-q3.json',              depth:1, stamp:'v3' },
  { kind:'file', name:'soylent-q2.json',             depth:1, stamp:'v2' },
  { kind:'dir',  name:'versions/',       depth:0, count:3 },
  { kind:'file', name:'v1.json',                     depth:1, stamp:'frozen' },
  { kind:'file', name:'v2.json',                     depth:1, stamp:'frozen' },
  { kind:'file', name:'v3.json',                     depth:1, stamp:'draft'  },
  { kind:'dir',  name:'metrics/',        depth:0, count:4 },
  { kind:'file', name:'eval_2025-05-09.json',        depth:1, stamp:'F1 .91' },
  { kind:'file', name:'eval_2025-05-08.json',        depth:1, stamp:'F1 .87' },
  { kind:'file', name:'eval_2025-05-04.json',        depth:1, stamp:'F1 .82' },
  { kind:'file', name:'schema.json',                 depth:0, stamp:'14 fields' },
  { kind:'file', name:'README.md',                   depth:0, stamp:'' },
];

const SCHEMA_FIELDS = [
  { name:'invoice_number',  type:'string', desc:'Document identifier printed at the top of the invoice.' },
  { name:'issue_date',      type:'date',   desc:'Date the invoice was issued (ISO 8601).' },
  { name:'due_date',        type:'date',   desc:'Payment due date.' },
  { name:'vendor_name',     type:'string', desc:'Legal name of the supplier issuing the invoice.' },
  { name:'vendor_tax_id',   type:'string', desc:'Tax identifier (EIN, VAT, ABN). Strip dashes.' },
  { name:'bill_to',         type:'object', desc:'Recipient block; address, contact.' },
  { name:'line_items[]',    type:'array',  desc:'One row per billable item. See sub-schema.' },
  { name:'subtotal',        type:'number', desc:'Sum of line items before tax and discount.' },
  { name:'tax',             type:'number', desc:'Total tax. Combine VAT/GST/State if line-itemized.' },
  { name:'total',           type:'number', desc:'Grand total payable.' },
  { name:'currency',        type:'string', desc:'ISO 4217 currency code.' },
  { name:'payment_terms',   type:'string', desc:'Net 30, Due on receipt, etc.' },
  { name:'po_number',       type:'string', desc:'Buyer-side purchase order. Optional.' },
  { name:'notes',           type:'string', desc:'Free text payment instructions.' },
];

const DOCS = [
  { name:'2024-Q3-acme.pdf',     status:'reviewed' },
  { name:'2024-Q3-globex.pdf',   status:'reviewed' },
  { name:'2024-Q3-soylent.pdf',  status:'reviewed' },
  { name:'2024-Q4-acme.pdf',     status:'pending' },
  { name:'2024-Q4-globex.pdf',   status:'pending' },
  { name:'2024-Q4-soylent.pdf',  status:'pending' },
  { name:'2025-Q1-globex.pdf',   status:'new' },
  { name:'2025-Q1-soylent.pdf',  status:'new' },
  { name:'2025-Q1-stark.pdf',    status:'error' },
];

const METRICS = [
  { k:'overall F1',         v:'0.914',     tone:'ok' },
  { k:'fields',             v:'14',        tone:'' },
  { k:'docs reviewed',      v:'5 / 42',    tone:'' },
  { k:'last eval',          v:'2h ago',    tone:'' },
  { k:'extraction cost',    v:'$0.011/doc',tone:'' },
  { k:'avg latency',        v:'4.2s',      tone:'' },
];

const EVAL_ROWS = [
  { f:'invoice_number', p:1.00, r:1.00, f1:1.00, n:42, tone:'ok',  err:null },
  { f:'issue_date',     p:0.98, r:0.95, f1:0.96, n:42, tone:'ok',  err:null },
  { f:'due_date',       p:0.91, r:0.88, f1:0.89, n:42, tone:'mid', err:'2 docs missed Net-15 stamps printed in the footer; 1 doc had a handwritten override the model didn’t pick up.' },
  { f:'vendor_name',    p:1.00, r:0.97, f1:0.98, n:42, tone:'ok',  err:null },
  { f:'vendor_tax_id',  p:0.84, r:0.71, f1:0.77, n:38, tone:'mid', err:'EIN format inconsistent across vendors — some include dashes, some don’t. Description doesn’t specify normalization.' },
  { f:'bill_to',        p:0.93, r:0.90, f1:0.91, n:42, tone:'ok',  err:null },
  { f:'line_items[]',   p:0.79, r:0.66, f1:0.72, n:42, tone:'bad', err:'Multi-page line item tables are mis-grouped on 4 documents. Acme Q4 lost the discount row. Soylent puts shipping as a line item, not a fee.' },
  { f:'subtotal',       p:0.95, r:0.95, f1:0.95, n:42, tone:'ok',  err:null },
  { f:'tax',            p:0.88, r:0.86, f1:0.87, n:42, tone:'mid', err:null },
  { f:'total',          p:1.00, r:1.00, f1:1.00, n:42, tone:'ok',  err:null },
  { f:'currency',       p:0.97, r:0.97, f1:0.97, n:42, tone:'ok',  err:null },
  { f:'payment_terms',  p:0.81, r:0.74, f1:0.77, n:35, tone:'mid', err:null },
  { f:'po_number',      p:0.92, r:0.88, f1:0.90, n:21, tone:'ok',  err:null },
  { f:'notes',          p:0.74, r:0.70, f1:0.72, n:28, tone:'bad', err:'Treated as catch-all; some payment instructions ended up in `payment_terms` instead. Description needs disambiguation rule.' },
];

// review document — grouped into sections for navigability
const REVIEW_DOC = {
  name:'2024-Q4-acme.pdf',
  pages:2,
  sections:[
    { id:'identity', label:'identity', fields:[
      { name:'invoice_number', type:'string', val:'ACM-2024-1187', conf:0.99, evidence:'p.1', confLab:'high' },
      { name:'issue_date',     type:'date',   val:'2024-10-14',    conf:0.97, evidence:'p.1', confLab:'high' },
      { name:'due_date',       type:'date',   val:'2024-11-13',    conf:0.62, evidence:'p.1', confLab:'low',  note:'Footer says "Net 30 from receipt" — agent assumed issue date. Confirm.' },
      { name:'po_number',      type:'string', val:'GBX-PO-44219',  conf:0.95, evidence:'p.1', confLab:'high' },
    ]},
    { id:'parties', label:'parties', fields:[
      { name:'vendor_name',    type:'string', val:'Acme Corp.',    conf:0.99, evidence:'p.1', confLab:'high' },
      { name:'vendor_tax_id',  type:'string', val:'82-3214567',    conf:0.74, evidence:'p.1', confLab:'mid', note:'Dashes left in. Schema description should clarify.' },
      // bill_to is an OBJECT — its sub-fields render inline once expanded
      { name:'bill_to', type:'object', conf:0.94, evidence:'p.1', confLab:'high',
        summary:'Globex Industries · Pittsburgh PA',
        sub:[
          { name:'company',  type:'string', val:'Globex Industries',     conf:0.98, confLab:'high' },
          { name:'street',   type:'string', val:'4400 Forbes Ave',       conf:0.95, confLab:'high' },
          { name:'city',     type:'string', val:'Pittsburgh',            conf:0.97, confLab:'high' },
          { name:'state',    type:'string', val:'PA',                    conf:0.96, confLab:'high' },
          { name:'postcode', type:'string', val:'15213',                 conf:0.93, confLab:'high' },
          { name:'country',  type:'string', val:'US',                    conf:0.81, confLab:'mid', note:'Inferred — not printed.' },
        ] },
    ]},
    { id:'lines', label:'line items', fields:[
      // line_items[] is an ARRAY — each row is a card with sub-fields
      { name:'line_items[]', type:'array', conf:0.79, evidence:'p.1 table', confLab:'mid',
        rows:[
          { _summary:'Consulting hours, October 2024', _amount:'$13,200.00',
            sub:[
              { name:'description', type:'string', val:'Consulting hours, October 2024', conf:0.98, confLab:'high' },
              { name:'qty',         type:'number', val:'120',        conf:0.99, confLab:'high' },
              { name:'rate',        type:'number', val:'110.00',     conf:0.99, confLab:'high' },
              { name:'amount',      type:'number', val:'13,200.00',  conf:0.99, confLab:'high' },
              { name:'tax',         type:'number', val:'924.00',     conf:0.84, confLab:'mid' },
            ]},
          { _summary:'On-site travel', _amount:'$1,020.00',
            sub:[
              { name:'description', type:'string', val:'On-site travel', conf:0.97, confLab:'high' },
              { name:'qty',         type:'number', val:'4',           conf:0.98, confLab:'high' },
              { name:'rate',        type:'number', val:'255.00',      conf:0.98, confLab:'high' },
              { name:'amount',      type:'number', val:'1,020.00',    conf:0.97, confLab:'high' },
              { name:'tax',         type:'number', val:'71.40',       conf:0.79, confLab:'mid' },
            ]},
          { _summary:'Volume discount (Net 30)', _amount:'−$0.00', _warn:'discount row — verify',
            sub:[
              { name:'description', type:'string', val:'Volume discount (Net 30)', conf:0.71, confLab:'mid', note:'Agent unsure if this is a line item or a top-level discount.' },
              { name:'qty',         type:'number', val:'—',     conf:0.50, confLab:'low' },
              { name:'rate',        type:'number', val:'—',     conf:0.50, confLab:'low' },
              { name:'amount',      type:'number', val:'0.00',  conf:0.88, confLab:'high' },
              { name:'tax',         type:'number', val:'0.00',  conf:0.60, confLab:'low' },
            ]},
        ]},
    ]},
    { id:'totals', label:'totals & terms', fields:[
      { name:'subtotal',       type:'number', val:'14,820.00',     conf:0.96, evidence:'p.2', confLab:'high' },
      { name:'tax',            type:'number', val:'1,037.40',      conf:0.91, evidence:'p.2', confLab:'high' },
      { name:'total',          type:'number', val:'15,857.40',     conf:1.00, evidence:'p.2', confLab:'high' },
      { name:'currency',       type:'string', val:'USD',           conf:0.99, evidence:'p.1', confLab:'high' },
      { name:'payment_terms',  type:'string', val:'Net 30',        conf:0.71, evidence:'p.2', confLab:'mid' },
    ]},
  ]
};

// extended schema (tweak: simulate a heavy schema with 50+ fields)
const REVIEW_DOC_HEAVY_EXTRA = [
  { id:'metadata', label:'metadata', fields:[
    { name:'language',         type:'string', val:'en',                conf:0.99, evidence:'auto',  confLab:'high' },
    { name:'page_count',       type:'number', val:'2',                 conf:1.00, evidence:'auto',  confLab:'high' },
    { name:'doc_type',         type:'string', val:'invoice',           conf:1.00, evidence:'auto',  confLab:'high' },
    { name:'doc_subtype',      type:'string', val:'services',          conf:0.92, evidence:'p.1',   confLab:'high' },
    { name:'doc_template_id',  type:'string', val:'acme-v3',           conf:0.88, evidence:'fingerprint', confLab:'high' },
    { name:'received_at',      type:'date',   val:'2024-10-15T09:14Z', conf:0.99, evidence:'email', confLab:'high' },
    { name:'source_channel',   type:'string', val:'email',             conf:0.97, evidence:'meta',  confLab:'high' },
    { name:'source_address',   type:'string', val:'ap@acme.example',   conf:0.96, evidence:'meta',  confLab:'high' },
  ]},
  { id:'remittance', label:'remittance', fields:[
    { name:'bank_name',        type:'string', val:'First Republic',           conf:0.93, evidence:'p.2', confLab:'high' },
    { name:'bank_routing',     type:'string', val:'321081669',                conf:0.81, evidence:'p.2', confLab:'mid' },
    { name:'bank_account',     type:'string', val:'•••• 4421',                conf:0.79, evidence:'p.2', confLab:'mid' },
    { name:'swift_bic',        type:'string', val:'FRBKUS6S',                 conf:0.74, evidence:'p.2', confLab:'mid' },
    { name:'iban',             type:'string', val:'—',                        conf:0.40, evidence:'—',   confLab:'low' },
    { name:'remit_to_name',    type:'string', val:'Acme Corp.',               conf:0.95, evidence:'p.2', confLab:'high' },
    { name:'remit_to_address', type:'string', val:'2200 Mission St, SF CA',   conf:0.88, evidence:'p.2', confLab:'high' },
    { name:'reference_memo',   type:'string', val:'INV ACM-2024-1187',        conf:0.91, evidence:'p.2', confLab:'high' },
    { name:'payment_methods[]',type:'array',  conf:0.86, evidence:'p.2', confLab:'high',
      rows:[
        { _summary:'ACH', _amount:'preferred', sub:[
          { name:'method', type:'string', val:'ACH', conf:0.97, confLab:'high' },
          { name:'fee',    type:'number', val:'0.00', conf:0.95, confLab:'high' }]},
        { _summary:'Wire', _amount:'+$25 fee', sub:[
          { name:'method', type:'string', val:'Wire', conf:0.94, confLab:'high' },
          { name:'fee',    type:'number', val:'25.00', conf:0.91, confLab:'high' }]},
      ]},
  ]},
  { id:'tax', label:'tax breakdown', fields:[
    { name:'tax_jurisdiction', type:'string', val:'PA, US',         conf:0.86, evidence:'p.2', confLab:'high' },
    { name:'tax_rate',         type:'number', val:'7.00',           conf:0.93, evidence:'p.2', confLab:'high' },
    { name:'tax_basis',        type:'number', val:'14,820.00',      conf:0.95, evidence:'p.2', confLab:'high' },
    { name:'tax_exempt',       type:'string', val:'false',          conf:0.99, evidence:'auto',confLab:'high' },
    { name:'reverse_charge',   type:'string', val:'false',          conf:0.99, evidence:'auto',confLab:'high' },
    { name:'tax_breakdown[]',  type:'array',  conf:0.84, evidence:'p.2', confLab:'high',
      rows:[
        { _summary:'PA state sales', _amount:'$1,037.40', sub:[
          { name:'name',  type:'string', val:'PA state sales', conf:0.91, confLab:'high' },
          { name:'rate',  type:'number', val:'7.00',           conf:0.95, confLab:'high' },
          { name:'amount',type:'number', val:'1,037.40',       conf:0.97, confLab:'high' }]},
      ]},
  ]},
  { id:'discounts', label:'discounts & fees', fields:[
    { name:'discount_total',   type:'number', val:'0.00',     conf:0.92, evidence:'p.2', confLab:'high' },
    { name:'shipping_fee',     type:'number', val:'0.00',     conf:0.96, evidence:'auto',confLab:'high' },
    { name:'handling_fee',     type:'number', val:'0.00',     conf:0.96, evidence:'auto',confLab:'high' },
    { name:'late_fee_rate',    type:'number', val:'1.50',     conf:0.83, evidence:'p.2', confLab:'high' },
    { name:'early_pay_discount', type:'string', val:'—',      conf:0.45, evidence:'—',   confLab:'low' },
  ]},
  { id:'flags', label:'flags & audit', fields:[
    { name:'is_credit_note',   type:'string', val:'false',    conf:1.00, evidence:'auto',confLab:'high' },
    { name:'is_proforma',      type:'string', val:'false',    conf:1.00, evidence:'auto',confLab:'high' },
    { name:'has_handwriting',  type:'string', val:'false',    conf:0.96, evidence:'ocr', confLab:'high' },
    { name:'has_stamp',        type:'string', val:'false',    conf:0.94, evidence:'ocr', confLab:'high' },
    { name:'pii_detected',     type:'string', val:'true',     conf:0.99, evidence:'auto',confLab:'high', note:'Vendor signatory name on p.2.' },
    { name:'extraction_model', type:'string', val:'emerge-x4',conf:1.00, evidence:'meta',confLab:'high' },
    { name:'extraction_cost',  type:'number', val:'0.011',    conf:1.00, evidence:'meta',confLab:'high' },
  ]},
];

// improve candidates (diff data)
const IMPROVE_CANDIDATES = [
  { field:'line_items[]',
    oldDesc:'One row per billable item. See sub-schema.',
    newDesc:'One row per billable item. Include discount lines and shipping as separate items only when printed as table rows; otherwise place them under top-level fields. Tables that span pages should be merged by repeated header detection.',
    delta:'+0.18 F1' },
  { field:'vendor_tax_id',
    oldDesc:'Tax identifier (EIN, VAT, ABN). Strip dashes.',
    newDesc:'Tax identifier (EIN, VAT, ABN). Output digits only — strip dashes, spaces, and country prefixes (e.g. "US-" or "VAT "). Preserve leading zeros.',
    delta:'+0.13 F1' },
  { field:'notes',
    oldDesc:'Free text payment instructions.',
    newDesc:'Free text payment instructions, remittance addresses, late fees and discounts. Do NOT include Net-N terms here — those go in payment_terms.',
    delta:'+0.09 F1' },
  { field:'due_date',
    oldDesc:'Payment due date.',
    newDesc:'Payment due date. If the document only states "Net N from receipt", compute due_date = issue_date + N days. If a handwritten override is visible, use that.',
    delta:'+0.07 F1' },
];

window.PROJECTS = PROJECTS;
window.TREE = TREE;
window.SCHEMA_FIELDS = SCHEMA_FIELDS;
window.DOCS = DOCS;
window.METRICS = METRICS;
window.EVAL_ROWS = EVAL_ROWS;
window.REVIEW_DOC = REVIEW_DOC;
window.REVIEW_DOC_HEAVY_EXTRA = REVIEW_DOC_HEAVY_EXTRA;
window.IMPROVE_CANDIDATES = IMPROVE_CANDIDATES;
