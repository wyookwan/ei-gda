/* Domain Taxonomy explorer. No framework; all text goes through textContent. */
(function () {
  var app = document.getElementById('taxApp');
  if (!app) return;
  var TYPE = {domain:'Domain',org_type:'องค์กร',functional_area:'ภารกิจ',use_case:'Use Case',dimension:'มิติ',control:'Control',regulation:'กฎหมาย',evidence:'หลักฐาน',rubric:'เกณฑ์',test_suite:'Test Suite',domain_suite:'ชุดทดสอบเฉพาะ Domain',test_case:'กรณีทดสอบ SILA'};
  var STATUS = {expert_verified:'ยืนยันโดยผู้ดูแล',source_confirmed:'พบแหล่งทางการ',source_indexed:'พบจากการค้นหา ยังไม่เปิดอ่าน',pending_verification:'รอตรวจสอบ',draft:'ร่าง ไม่พบแหล่ง'};
  var CLASS = {binding_legislation:'กฎหมายบังคับ',mandated_standard:'มาตรฐานภาครัฐ',voluntary_standard:'มาตรฐานที่เกี่ยวข้อง',non_binding_guideline:'แนวปฏิบัติ'};
  var HIERARCHY = ['HAS_ORG_TYPE','OPERATES','HAS_USE_CASE','CONCERNS','HAS_DIMENSION','INHERITS_CORE','GOVERNED_BY','DERIVED_FROM','REQUIRES_EVIDENCE','ASSESSED_USING','IN_SUITE','DOMAIN_REFERENCE'];
  var data, children = {}, parents = {}, expanded = new Set(), selectedKey = null, visible = null;
  var tree = document.getElementById('taxTree'), detail = document.getElementById('taxDetail'), crumb = document.getElementById('taxCrumb'), count = document.getElementById('fCount');
  var search = document.getElementById('fSearch'), selects = Array.prototype.slice.call(document.querySelectorAll('select[data-facet]'));
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined && text !== null) n.textContent = text; return n; }
  function label(n) { return n.title_th || n.title; }

  document.getElementById('taxDomain').addEventListener('change', function () { location.href = this.value; });
  fetch(app.dataset.api, {credentials: 'same-origin'}).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(init).catch(function () {
    tree.textContent = '';
    var box = el('div', 'empty', 'โหลด Taxonomy ไม่สำเร็จ '); var retry = el('button', 'btn btn-sm btn-outline-secondary', 'ลองใหม่'); retry.addEventListener('click', function () { location.reload(); }); box.appendChild(retry); tree.appendChild(box);
  });

  function init(payload) {
    data = payload;
    payload.edges.forEach(function (e) { (children[e.src] = children[e.src] || []).push(e); (parents[e.dst] = parents[e.dst] || []).push(e); });
    Object.keys(children).forEach(function (k) { children[k].sort(function (a, b) { return HIERARCHY.indexOf(a.rel) - HIERARCHY.indexOf(b.rel) || label(payload.nodes[a.dst]).localeCompare(label(payload.nodes[b.dst]), 'th'); }); });
    if (payload.provisional_note_th) { var note = el('div', 'notice notice-warn'); note.appendChild(el('div', '', payload.provisional_note_th)); document.getElementById('taxNote').appendChild(note); }
    fillFacet('fOrg', 'org_type'); fillFacet('fArea', 'functional_area'); fillFacet('fCase', 'use_case'); fillFacet('fDim', 'dimension');
    expanded.add('/' + payload.root);
    selects.forEach(function (s) { s.addEventListener('change', apply); });
    search.addEventListener('input', apply);
    document.getElementById('fClear').addEventListener('click', function () { selects.forEach(function (s) { s.value = ''; }); search.value = ''; apply(); });
    document.getElementById('tCollapse').addEventListener('click', function () { expanded = new Set(['/' + payload.root]); render(); });
    document.getElementById('tExpand').addEventListener('click', function () { expandTo(function (n) { return n.type === 'control'; }); render(); });
    apply();
    select(payload.root, '/' + payload.root);
  }
  function fillFacet(id, type) {
    var s = document.getElementById(id); s.appendChild(new Option('ทั้งหมด', ''));
    Object.values(data.nodes).filter(function (n) { return n.type === type; }).sort(function (a, b) { return label(a).localeCompare(label(b), 'th'); }).forEach(function (n) { s.appendChild(new Option(label(n), n.id)); });
  }
  function matchingControls() {
    var active = selects.filter(function (s) { return s.value; });
    if (!active.length) return null;
    return new Set(Object.keys(data.control_index).filter(function (id) {
      var row = data.control_index[id];
      return active.every(function (s) { var v = row[s.dataset.facet]; return Array.isArray(v) ? v.indexOf(s.value) >= 0 : v === s.value; });
    }));
  }
  /* Keep a node only if it leads to a matching control, is one, or sits below one. */
  function computeVisible() {
    var matched = matchingControls(), term = search.value.trim().toLowerCase();
    if (!matched && !term) return null;
    var keep = new Set();
    function climb(id) { if (keep.has(id)) return; keep.add(id); (parents[id] || []).forEach(function (e) { climb(e.src); }); }
    function descend(id) { (children[id] || []).forEach(function (e) { if (!keep.has(e.dst)) { keep.add(e.dst); descend(e.dst); } }); }
    if (matched) matched.forEach(function (id) { if (data.nodes[id]) { climb(id); descend(id); } });
    if (term) {
      var hits = new Set();
      Object.values(data.nodes).forEach(function (n) { if ((n.id + ' ' + n.title + ' ' + (n.title_th || '')).toLowerCase().indexOf(term) >= 0) { if (!matched || keep.has(n.id)) hits.add(n.id); } });
      keep = new Set(); hits.forEach(climb); hits.forEach(descend);
    }
    /* A chosen organisation, function, use case or dimension hides its siblings. */
    ['fOrg', 'fArea', 'fCase', 'fDim'].forEach(function (id) {
      var chosen = document.getElementById(id).value;
      if (!chosen) return;
      var type = data.nodes[chosen].type;
      Object.values(data.nodes).forEach(function (n) { if (n.type === type && n.id !== chosen) keep.delete(n.id); });
    });
    /* Count and show only what is reachable from the root after pruning. */
    var reachable = new Set([data.root]), stack = [data.root];
    while (stack.length) { (children[stack.pop()] || []).forEach(function (e) { if (keep.has(e.dst) && !reachable.has(e.dst)) { reachable.add(e.dst); stack.push(e.dst); } }); }
    return reachable;
  }
  function expandTo(stop) {
    var walk = function (id, path, depth) { if (depth > 8 || (visible && !visible.has(id))) return; var n = data.nodes[id]; if (stop(n)) return; expanded.add(path); (children[id] || []).forEach(function (e) { if (path.split('/').indexOf(e.dst) < 0) walk(e.dst, path + '/' + e.dst, depth + 1); }); };
    walk(data.root, '/' + data.root, 0);
  }
  function apply() {
    visible = computeVisible();
    if (visible) expandTo(function (n) { return n.type === 'control'; });
    var total = Object.keys(data.control_index).length, shown = visible ? Object.keys(data.control_index).filter(function (id) { return visible.has(id); }).length : total;
    count.textContent = 'แสดง ' + shown + ' จาก ' + total + ' Control';
    render();
  }
  function render() { tree.textContent = ''; var ul = el('ul'); ul.appendChild(item(data.root, '/' + data.root)); tree.appendChild(ul); }
  function item(id, path) {
    var node = data.nodes[id], li = el('li'); li.setAttribute('role', 'treeitem');
    var kids = (children[id] || []).filter(function (e) { return (!visible || visible.has(e.dst)) && path.split('/').indexOf(e.dst) < 0; });
    var open = expanded.has(path);
    if (kids.length) li.setAttribute('aria-expanded', open ? 'true' : 'false');
    var row = el('button', 'tax-row' + (selectedKey === path ? ' selected' : '')); row.type = 'button';
    var caret = el('i', 'tax-caret bi ' + (kids.length ? (open ? 'bi-chevron-down' : 'bi-chevron-right') : '')); row.appendChild(caret);
    row.appendChild(el('span', 'tax-type', TYPE[node.type] || node.type));
    if (node.type === 'control') row.appendChild(el('code', '', node.id));
    row.appendChild(el('span', 'tax-title', label(node)));
    if (node.attrs && node.attrs.critical) row.appendChild(el('span', 'badge-s s-bad', 'วิกฤต'));
    if (node.attrs && node.attrs.provisional) row.appendChild(el('span', 'chip', 'ชั่วคราว'));
    if (node.attrs && node.attrs.verification_status) row.appendChild(el('span', 'chip', STATUS[node.attrs.verification_status] || ''));
    row.addEventListener('click', function () { if (kids.length) { if (expanded.has(path)) expanded.delete(path); else expanded.add(path); } select(id, path); render(); });
    li.appendChild(row);
    if (kids.length && open) { var ul = el('ul'); ul.setAttribute('role', 'group'); kids.forEach(function (e) { ul.appendChild(item(e.dst, path + '/' + e.dst)); }); li.appendChild(ul); }
    return li;
  }
  function related(title, ids) {
    if (!ids.length) return;
    detail.appendChild(el('h3', 'mt-3', title));
    ids.forEach(function (id) {
      var n = data.nodes[id]; if (!n) return;
      var line = el('div', 'small'); line.textContent = (n.type === 'control' ? n.id + ' ' : '') + label(n); detail.appendChild(line);
    });
  }
  function select(id, path) {
    selectedKey = path;
    var n = data.nodes[id], a = n.attrs || {};
    crumb.textContent = '';
    path.split('/').filter(Boolean).forEach(function (p, i, all) { var sp = el('span', '', label(data.nodes[p])); crumb.appendChild(sp); if (i < all.length - 1) crumb.appendChild(el('i', 'bi bi-chevron-right')); });
    detail.textContent = '';
    detail.appendChild(el('span', 'tax-type', TYPE[n.type] || n.type));
    detail.appendChild(el('h2', 'mt-1', label(n)));
    if (n.title_th && n.title !== n.title_th) detail.appendChild(el('div', 'small-note', n.title));
    detail.appendChild(el('div', 'small-note', 'รหัส ' + n.id));
    ['summary_th','objective_th','why_th','focus_th','condition_th','provisional_note_th'].forEach(function (k) { if (a[k]) detail.appendChild(el('p', 'mt-2 mb-1', a[k])); });
    if (a.normative_class) detail.appendChild(el('div', 'chip me-1', CLASS[a.normative_class]));
    if (a.verification_status) detail.appendChild(el('div', 'chip', STATUS[a.verification_status]));
    if (a.official_url && /^https?:\/\//.test(a.official_url)) { var link = el('a', 'd-block small mt-1', 'เปิดแหล่งทางการ'); link.href = a.official_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; detail.appendChild(link); }
    if (a.levels) { detail.appendChild(el('h3', 'mt-3', 'ระดับเกณฑ์')); Object.keys(a.levels).sort().forEach(function (k) { detail.appendChild(el('div', 'small', k + ': ' + a.levels[k])); }); if (a.gate_min_level !== undefined) detail.appendChild(el('div', 'small-note mt-1', 'Control วิกฤตต้องได้อย่างน้อยระดับ ' + a.gate_min_level)); }
    if (a.details_th) { detail.appendChild(el('h3', 'mt-3', 'ขอบเขต')); a.details_th.forEach(function (d) { detail.appendChild(el('div', 'small', '• ' + d)); }); }
    var out = children[id] || [], into = parents[id] || [];
    var byRel = function (rel) { return out.filter(function (e) { return e.rel === rel; }).map(function (e) { return e.dst; }); };
    related('กฎหมายและมาตรฐาน', byRel('DERIVED_FROM'));
    related('หลักฐานที่ต้องใช้', byRel('REQUIRES_EVIDENCE'));
    related('Test Suite ที่เกี่ยวข้อง', byRel('IN_SUITE'));
    related('เกณฑ์', byRel('ASSESSED_USING'));
    related('Control ที่เกี่ยวข้อง', out.filter(function (e) { return e.rel === 'GOVERNED_BY'; }).map(function (e) { return e.dst; }).concat(into.filter(function (e) { return ['DERIVED_FROM','REQUIRES_EVIDENCE','IN_SUITE'].indexOf(e.rel) >= 0; }).map(function (e) { return e.src; })));
  }
})();
