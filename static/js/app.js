document.addEventListener('DOMContentLoaded', () => {
  const escapeHtml=(value)=>String(value??'').replace(/[&<>\"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#039;'}[ch]||ch));
  const loader = document.getElementById('nodeLoader');
  const loaderTitle = document.getElementById('nodeLoaderTitle');
  const loaderMessage = document.getElementById('nodeLoaderMessage');
  const showLoader = (title, message) => {
    if (!loader) return;
    if (title && loaderTitle) loaderTitle.textContent = title;
    if (message && loaderMessage) loaderMessage.textContent = message;
    loader.classList.add('is-visible');
    loader.setAttribute('aria-hidden', 'false');
    document.body.setAttribute('aria-busy', 'true');
  };
  const hideLoader = () => {
    loader?.classList.remove('is-visible');
    loader?.setAttribute('aria-hidden', 'true');
    document.body.removeAttribute('aria-busy');
  };
  window.addEventListener('pageshow', hideLoader);

  document.querySelectorAll('form').forEach(form => form.addEventListener('submit', event => {
    queueMicrotask(() => {
      if (event.defaultPrevented || !form.checkValidity()) return;
      const isCompliance = form.action.includes('/run-compliance');
      showLoader(
        form.dataset.loadingTitle || (isCompliance ? 'กำลังวิเคราะห์เอกสาร' : 'กำลังบันทึกข้อมูล'),
        form.dataset.loadingMessage || (isCompliance
          ? 'กำลังสร้าง Knowledge Graph และประเมิน Compliance ด้วย AI อาจใช้เวลาสักครู่'
          : 'กรุณารอสักครู่ ระบบกำลังดำเนินการ')
      );
    });
  }));

  document.querySelectorAll('a[href]').forEach(link => link.addEventListener('click', event => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (link.target === '_blank' || link.hasAttribute('download')) return;
    const url = new URL(link.href, window.location.href);
    const isFileResponse = url.pathname.endsWith('/report') || url.pathname.endsWith('/source-pdf');
    if (url.origin !== window.location.origin || isFileResponse || (url.pathname === window.location.pathname && url.hash)) return;
    showLoader('กำลังเปิดหน้าเว็บ', 'กรุณารอสักครู่ ระบบกำลังโหลดข้อมูลล่าสุด');
  }));

  const sidebar = document.getElementById('appSidebar');
  document.querySelector('.sidebar-toggle')?.addEventListener('click', () => sidebar?.classList.toggle('open'));
  document.querySelectorAll('.side-nav a').forEach(a => {
    if (a.pathname === window.location.pathname || (a.pathname !== '/' && window.location.pathname.startsWith(a.pathname))) a.classList.add('active');
  });

  const dz = document.querySelector('.dropzone');
  const fileInput = dz?.querySelector('input[type=file]');
  if (dz && fileInput) {
    let selectedFiles = [];
    const fileKey = file => `${file.name}:${file.size}:${file.lastModified}`;
    const addFiles = incoming => {
      const known = new Set(selectedFiles.map(fileKey));
      [...incoming].forEach(file => {
        if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
          if (!known.has(fileKey(file))) selectedFiles.push(file);
          known.add(fileKey(file));
        }
      });
      const transfer = new DataTransfer();
      selectedFiles.forEach(file => transfer.items.add(file));
      fileInput.files = transfer.files;
      updateFileLabel();
    };
    ['dragenter','dragover'].forEach(e => dz.addEventListener(e, ev => {ev.preventDefault();dz.classList.add('dragover')}));
    ['dragleave','drop'].forEach(e => dz.addEventListener(e, ev => {ev.preventDefault();dz.classList.remove('dragover')}));
    dz.addEventListener('drop', e => { if(e.dataTransfer.files.length) addFiles(e.dataTransfer.files); });
    fileInput.addEventListener('change', () => addFiles(fileInput.files));
    function updateFileLabel(){const label=dz.querySelector('.file-name');if(label)label.textContent=selectedFiles.length?`${selectedFiles.length} file(s): ${selectedFiles.map(f=>f.name).join(', ')}`:'No files selected';}
  }

  // Confidentiality selector + informative modal
  const classificationData = {
    open: {
      title: 'Open · เอกสารเปิดเผยได้',
      icon: '<i class="bi bi-globe2"></i>',
      description: 'เอกสารที่ไม่มีข้อมูลลับหรือข้อมูลอ่อนไหว โดย Ei-GDA จะประมวลผลผ่าน Gemini และ Knowledge Graph',
      examples: ['นโยบาย AI ที่เผยแพร่สาธารณะ', 'คู่มือ/แนวปฏิบัติที่เผยแพร่บนเว็บไซต์องค์กร', 'รายงานวิจัยหรือรายงานประจำปีที่เปิดเผยต่อสาธารณะ', 'เอกสารมาตรฐานหรือเอกสารประชาสัมพันธ์ทั่วไป'],
      route: '<strong>Processing route:</strong> Gemini API + Knowledge Graph'
    },
    confidential: {
      title: 'Confidential · เอกสารชั้นความลับ',
      icon: '<i class="bi bi-shield-lock"></i>',
      description: 'เอกสารที่มีข้อมูลภายใน ข้อมูลส่วนบุคคล ความลับทางธุรกิจ ข้อมูลความมั่นคง หรือข้อมูลที่องค์กรไม่อนุญาตให้ส่งออกไปยังบริการ AI ภายนอก',
      examples: ['นโยบายภายในที่ยังไม่ประกาศ', 'เอกสารที่มีข้อมูลส่วนบุคคลหรือข้อมูลตาม PDPA', 'Risk Register / Incident Report ภายใน', 'รายละเอียดระบบ ความมั่นคงปลอดภัย สถาปัตยกรรม หรือข้อมูลเชิงเทคนิคที่เป็นความลับ'],
      route: '<strong>Processing route:</strong> Local Model API + Knowledge Graph · ข้อมูลไม่ถูกส่งไปบริการ AI ภายนอก'
    }
  };
  document.querySelectorAll('[data-classification-info]').forEach(label => {
    label.addEventListener('click', (ev) => {
      const type = label.dataset.classificationInfo;
      const data = classificationData[type];
      const route = document.getElementById('classificationRoute');
      if(route) route.innerHTML = data.route;
      document.getElementById('classificationModalTitle').textContent = data.title;
      document.getElementById('classificationModalHero').innerHTML = data.icon;
      document.getElementById('classificationModalDescription').textContent = data.description;
      document.getElementById('classificationModalExamples').innerHTML = data.examples.map(x=>`<li>${x}</li>`).join('');
      document.getElementById('classificationModalRoute').innerHTML = data.route;
      const modalEl = document.getElementById('classificationInfoModal');
      if (modalEl && window.bootstrap && window.bootstrap.Modal) {
        const modal = window.bootstrap.Modal.getOrCreateInstance(modalEl, {
          backdrop: true,
          keyboard: true,
          focus: true
        });
        modal.show();
      } else {
        console.error('Bootstrap Modal is not available or modal element was not found.');
      }
    });
  });


  // Ei-GDA Test Suite -> mapped standards/frameworks/laws filtering
  const tplSelect = document.getElementById('tnagfTemplateSelect');
  const tplMapEl = document.getElementById('template-framework-map');
  const tplInfoEl = document.getElementById('template-info-map');
  if (tplSelect && tplMapEl && tplInfoEl) {
    let frameworkMap = {}, infoMap = {};
    try { frameworkMap = JSON.parse(tplMapEl.textContent || '{}'); } catch(e) {}
    try { infoMap = JSON.parse(tplInfoEl.textContent || '{}'); } catch(e) {}

    const list = document.getElementById('frameworkSelectionList');
    const empty = document.getElementById('frameworkSelectionEmpty');
    const infoPanel = document.getElementById('templateInfoPanel');
    const countChip = document.getElementById('frameworkCountChip');

    const applyTemplateFilter = () => {
      const id = tplSelect.value;
      const allowed = new Set((frameworkMap[id] || []).map(String));
      document.querySelectorAll('.framework-option').forEach(opt => {
        const show = allowed.has(String(opt.dataset.frameworkCode));
        opt.classList.toggle('d-none', !show);
        const cb = opt.querySelector('input[type=checkbox]');
        if (!show && cb) cb.checked = false;
      });
      document.querySelectorAll('.framework-group').forEach(group => {
        const visible = [...group.querySelectorAll('.framework-option')].some(x => !x.classList.contains('d-none'));
        group.classList.toggle('d-none', !visible);
      });

      if (!id) {
        list?.classList.add('d-none');
        empty?.classList.remove('d-none');
        infoPanel?.classList.add('d-none');
        if(countChip) countChip.textContent = 'Select Test Suite first';
        return;
      }

      list?.classList.remove('d-none');
      empty?.classList.add('d-none');
      const info = infoMap[id] || {};
      if (infoPanel) {
        infoPanel.innerHTML = `
          <div class="d-flex gap-2 align-items-start">
            <i class="bi bi-file-earmark-check text-primary"></i>
            <div>
              <strong>${info.name || 'Test Suite'}</strong>
              <div class="small text-secondary mt-1">${info.description || ''}</div>
              <div class="small mt-2"><strong>Mode:</strong> Direct compliance assessment</div>
            </div>
          </div>`;
        infoPanel.classList.remove('d-none');
      }
      if(countChip) countChip.textContent = `${allowed.size} applicable references`;
    };
    tplSelect.addEventListener('change', applyTemplateFilter);
    applyTemplateFilter();
  }

    document.querySelectorAll('.score-range').forEach(r => r.addEventListener('input', () => {
    const out = r.closest('.review-item, .border, .mb-4')?.querySelector('.range-value'); if(out) out.textContent = r.value;
  }));

  const sortableEl = document.getElementById('sortable-items');
  if(sortableEl && window.Sortable){new Sortable(sortableEl,{animation:170,handle:'.drag-handle',onEnd:async()=>{const order=[...sortableEl.children].map(x=>x.dataset.id);const url=sortableEl.dataset.reorderUrl; if(url) await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order})});}})}


  document.querySelectorAll('.committee-source-switch').forEach(btn => btn.addEventListener('click', () => {
    const frame=document.getElementById('committeeSourceFrame');
    if(frame) frame.src=`${btn.dataset.pdfSrc}#toolbar=1&navpanes=1`;
    document.querySelectorAll('.committee-source-switch').forEach(x=>{x.classList.remove('btn-primary');x.classList.add('btn-outline-primary')});
    btn.classList.remove('btn-outline-primary');btn.classList.add('btn-primary');
  }));

  const multiFileInput = document.querySelector('input[name="pdf_files"]');
  if(multiFileInput){
    const out = multiFileInput.closest('.dropzone')?.querySelector('.file-name');
    multiFileInput.addEventListener('change', () => {
      const files = [...multiFileInput.files];
      if(out) out.textContent = files.length ? `${files.length} file(s): ${files.map(f=>f.name).join(', ')}` : 'No files selected';
    });
  }

  const evidenceDataEl = document.getElementById('compliance-evidence-json');
  const evidenceModalEl = document.getElementById('evidenceDetailModal');
  if(evidenceDataEl && evidenceModalEl && window.bootstrap){
    let rows=[];
    try{ rows=JSON.parse(evidenceDataEl.textContent||'[]'); }catch(e){}
    const modal = new bootstrap.Modal(evidenceModalEl);
    document.querySelectorAll('[data-evidence-index]').forEach(btn => btn.addEventListener('click', () => {
      const item = rows[Number(btn.dataset.evidenceIndex)] || {};
      const checkId = evidenceModalEl.dataset.checkId;
      const set=(id,val)=>{const el=document.getElementById(id); if(el) el.textContent=val||'-';};
      set('evidenceModalItem', `${item.item_code||''} · ${item.title||''}`);
      set('evidenceModalScore', `${item.score ?? 0} / 5`);
      set('evidenceModalMaturity', item.maturity);
      set('evidenceModalReason', item.reason);
      set('evidenceModalGap', item.gap);
      set('evidenceModalRecommendation', item.recommendation);
      const box=document.getElementById('evidenceModalList');
      const ev=item.evidence||[];
      if(box){
        box.innerHTML = ev.length ? ev.map(e => `
          <div class="evidence-card mb-2">
            <div class="d-flex justify-content-between gap-2 flex-wrap">
              <strong><i class="bi bi-file-earmark-pdf me-1 text-danger"></i>${escapeHtml(e.filename||'Source PDF')}</strong>
              <span class="data-chip">Page ${Number(e.page||1)}</span>
            </div>
            <div class="small text-secondary mt-2">${escapeHtml(e.snippet||'')}</div>
            <div class="mt-2"><a class="btn btn-sm btn-outline-primary" target="_blank" href="/check/${checkId}/source/${Number(e.file_id)}#page=${Number(e.page||1)}"><i class="bi bi-box-arrow-up-right me-1"></i>Open source page</a></div>
          </div>`).join('') : '<div class="alert alert-light border mb-0">No page-level evidence was located for this item.</div>';
      }
      modal.show();
    }));
  }

  if(window.Chart){
    const committeeEl=document.getElementById('committee-graph-json');
    if(committeeEl){
      try{
        const rows=JSON.parse(committeeEl.value||'[]');
        const canvas=document.getElementById('committeeCompareChart');
        if(canvas)new Chart(canvas,{type:'radar',data:{labels:rows.map(x=>x.code),datasets:[
          {label:'System',data:rows.map(x=>Number(x.system||0)),backgroundColor:'rgba(11,92,255,.10)',borderColor:'#0b5cff',pointBackgroundColor:'#0b5cff'},
          {label:'Committee',data:rows.map(x=>Number(x.committee||0)),backgroundColor:'rgba(18,183,106,.08)',borderColor:'#12b76a',pointBackgroundColor:'#12b76a'}
        ]},options:{responsive:true,maintainAspectRatio:false,scales:{r:{beginAtZero:true,max:5,ticks:{stepSize:1}}}}});
      }catch(e){console.warn(e)}
    }
    const stdEl=document.getElementById('standard-summary-json');
    if(stdEl){
      try{
        const arr=JSON.parse(stdEl.value||'[]');
        const labels=arr.map(x=>x.code), values=arr.map(x=>Number(x.avg_score_0_to_5||0));
        const b=document.getElementById('barChart');
        if(b)new Chart(b,{type:'bar',data:{labels,datasets:[{label:'Maturity 0-5',data:values,borderRadius:8,backgroundColor:'rgba(11,92,255,.78)'}]},options:{responsive:true,maintainAspectRatio:false,scales:{y:{beginAtZero:true,max:5,ticks:{stepSize:1}}},plugins:{legend:{display:false}}}});
        const r=document.getElementById('radarChart');
        if(r)new Chart(r,{type:'radar',data:{labels,datasets:[{label:'Maturity',data:values,backgroundColor:'rgba(11,92,255,.14)',borderColor:'#0b5cff',pointBackgroundColor:'#0b5cff'}]},options:{responsive:true,maintainAspectRatio:false,scales:{r:{beginAtZero:true,max:5,ticks:{stepSize:1}}}}});
      }catch(e){console.warn(e)}
    }
    const mdEl=document.getElementById('maturity-distribution-json');
    if(mdEl){try{const d=JSON.parse(mdEl.value||'{}');const c=document.getElementById('maturityDonut');if(c)new Chart(c,{type:'doughnut',data:{labels:['0 Not Impl.','1 Initial','2 Defined','3 Implemented','4 Managed','5 Optimized'],datasets:[{data:[0,1,2,3,4,5].map(x=>d[String(x)]||0),backgroundColor:['#d92d20','#f79009','#fdb022','#2e90fa','#1570ef','#12b76a']}]},options:{responsive:true,maintainAspectRatio:false,cutout:'62%'}})}catch(e){}}
    const catEl=document.getElementById('category-summary-json');
    if(catEl){try{const a=JSON.parse(catEl.value||'[]').sort((x,y)=>y.avg_score_0_to_5-x.avg_score_0_to_5).slice(0,12);const c=document.getElementById('categoryChart');if(c)new Chart(c,{type:'bar',data:{labels:a.map(x=>x.category),datasets:[{data:a.map(x=>x.avg_score_0_to_5),backgroundColor:'rgba(18,183,106,.75)',borderRadius:6}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,scales:{x:{beginAtZero:true,max:5,ticks:{stepSize:1}}},plugins:{legend:{display:false}}}})}catch(e){}}
  }
});
