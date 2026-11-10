// Assessment selection is held in the real form controls: tabs never discard selections.
(() => {
  const form = document.getElementById('assessmentBuilder');
  if (!form) return;
  const byId = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const suite = byId('tnagfTemplateSelect');
  const mapping = JSON.parse(byId('template-framework-map').textContent);
  const suiteInfo = JSON.parse(byId('template-info-map').textContent);
  const cards = [...form.querySelectorAll('[data-framework-code]')];
  const tabs = [...form.querySelectorAll('[data-reference-tab]')];
  const panels = [...form.querySelectorAll('[data-reference-panel]')];
  const checkbox = card => card.querySelector('input');
  const selected = () => cards.filter(card => checkbox(card).checked && !checkbox(card).disabled);
  const eligible = card => !checkbox(card).disabled;
  const pageSize = 6;
  let activeType = '', page = 1, files = [], confirmed = false, submitting = false, reviewedState = '';
  const input = byId('assessmentFiles');
  const dialog = byId('assessmentConfirmDialog');
  const upload = byId('assessmentUpload');
  const fileKey = f => `${f.name}:${f.size}:${f.lastModified}`;
  const sizeLabel = size => size < 1024 * 1024 ? `${(size / 1024).toFixed(1)} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`;
  const announce = message => { byId('selectionAnnouncement').textContent = message; };
  function setError(id, message) { const el = byId(id); el.textContent = message; el.hidden = !message; }

  function renderCatalog() {
    const query = byId('referenceSearch').value.trim().toLocaleLowerCase();
    const matches = cards.filter(card => eligible(card) && card.dataset.frameworkType === activeType &&
      `${card.dataset.frameworkCode} ${card.dataset.referenceName}`.toLocaleLowerCase().includes(query));
    const pages = Math.max(1, Math.ceil(matches.length / pageSize));
    page = Math.min(page, pages);
    const visible = new Set(matches.slice((page - 1) * pageSize, page * pageSize));
    cards.forEach(card => { card.hidden = !visible.has(card); });
    panels.forEach(panel => { panel.hidden = panel.dataset.referencePanel !== activeType; });
    tabs.forEach(tab => {
      const active = tab.dataset.referenceTab === activeType;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    byId('referenceSearchEmpty').hidden = matches.length > 0;
    byId('referencePrev').disabled = page === 1;
    byId('referenceNext').disabled = page >= pages;
    byId('referencePageLabel').textContent = matches.length ? `${(page-1)*pageSize+1}–${Math.min(page*pageSize,matches.length)} จาก ${matches.length} รายการ · หน้า ${page}/${pages}` : '0 รายการ';
    byId('frameworkCountChip').textContent = `${cards.filter(eligible).length} references ที่เกี่ยวข้อง`;
  }

  function groupedSelection(removable) {
    const chosen = selected();
    return panels.map(panel => {
      const rows = chosen.filter(card => card.dataset.frameworkType === panel.dataset.referencePanel);
      if (!rows.length) return '';
      return `<section class="selection-group"><h3>${escape(panel.dataset.groupLabel)} <span>${rows.length}</span></h3><ul>${rows.map(card =>
        `<li><div><strong>${escape(card.dataset.frameworkCode)}</strong><span>${escape(card.dataset.referenceName)}</span></div>${removable ? `<button type="button" class="remove-reference" data-remove-reference="${escape(checkbox(card).value)}" aria-label="นำ ${escape(card.dataset.frameworkCode)} ออกจากชุด"><i class="bi bi-x-lg" aria-hidden="true"></i></button>` : ''}</li>`).join('')}</ul></section>`;
    }).join('');
  }

  function renderSelection() {
    const chosen = selected();
    byId('selectionSuiteName').textContent = suiteInfo[suite.value]?.name || 'ยังไม่ได้เลือก Test Suite';
    byId('selectionCount').textContent = `${chosen.length} references ที่เลือก`;
    byId('selectionGroups').innerHTML = groupedSelection(true) || '<p class="selection-empty">เลือก references เพื่อจัดชุดการประเมินของคุณ</p>';
    byId('continueToUpload').disabled = !chosen.length || !suite.value;
    byId('clearReferences').disabled = !chosen.length;
    cards.forEach(card => {
      const checked = checkbox(card).checked;
      card.classList.toggle('is-selected', checked);
      card.querySelector('.reference-selection-label').innerHTML = checked ? '<i class="bi bi-check-circle-fill"></i> อยู่ในชุดแล้ว' : '<i class="bi bi-plus-circle"></i> เพิ่มในชุด';
    });
    tabs.forEach(tab => {
      const type = tab.dataset.referenceTab;
      const total = cards.filter(card => eligible(card) && card.dataset.frameworkType === type).length;
      const count = chosen.filter(card => card.dataset.frameworkType === type).length;
      tab.querySelector('.tab-count').textContent = count ? `${count}/${total}` : String(total);
    });
    if (chosen.length) setError('referenceError', '');
  }

  function applySuite(announceChange = false) {
    const allowed = new Set(mapping[suite.value] || []);
    let removed = 0;
    cards.forEach(card => {
      const permitted = !!suite.value && allowed.has(card.dataset.frameworkCode);
      if (!permitted && checkbox(card).checked) { checkbox(card).checked = false; removed++; }
      checkbox(card).disabled = !permitted;
    });
    tabs.forEach(tab => { tab.hidden = !cards.some(card => eligible(card) && card.dataset.frameworkType === tab.dataset.referenceTab); });
    activeType = tabs.find(tab => !tab.hidden)?.dataset.referenceTab || '';
    page = 1;
    byId('referenceSearch').value = '';
    byId('frameworkSelectionList').hidden = !suite.value || !activeType;
    byId('frameworkSelectionEmpty').hidden = !!suite.value && !!activeType;
    byId('templateInfoPanel').hidden = !suite.value;
    byId('templateInfoPanel').textContent = suiteInfo[suite.value]?.description || '';
    if (announceChange) announce(removed ? `นำออก ${removed} รายการที่ไม่เกี่ยวข้องกับ Test Suite ใหม่ รายการที่ยังใช้ได้คงอยู่ในชุด` : 'เลือก references จากแท็บประเภทที่ต้องการได้เลย');
    renderCatalog(); renderSelection();
  }
  suite.addEventListener('change', () => applySuite(true));
  cards.forEach(card => checkbox(card).addEventListener('change', () => {
    renderSelection();
    announce(`${checkbox(card).checked ? 'เพิ่ม' : 'นำออก'} ${card.dataset.frameworkCode} · รวม ${selected().length} references`);
  }));
  function activateTab(tab) { activeType = tab.dataset.referenceTab; page = 1; byId('referenceSearch').value = ''; renderCatalog(); }
  tabs.forEach(tab => {
    tab.addEventListener('click', () => activateTab(tab));
    tab.addEventListener('keydown', event => {
      const available = tabs.filter(t => !t.hidden);
      let index = available.indexOf(tab);
      if (event.key === 'ArrowRight') index = (index + 1) % available.length;
      else if (event.key === 'ArrowLeft') index = (index - 1 + available.length) % available.length;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = available.length - 1;
      else return;
      event.preventDefault(); activateTab(available[index]); available[index].focus();
    });
  });
  byId('referenceSearch').addEventListener('input', () => { page = 1; renderCatalog(); });
  byId('referencePrev').addEventListener('click', () => { page--; renderCatalog(); });
  byId('referenceNext').addEventListener('click', () => { page++; renderCatalog(); });
  byId('selectionGroups').addEventListener('click', event => {
    const button = event.target.closest('[data-remove-reference]');
    if (!button) return;
    const card = cards.find(c => checkbox(c).value === button.dataset.removeReference);
    checkbox(card).checked = false;
    renderSelection(); announce(`นำ ${card.dataset.frameworkCode} ออกจากชุดแล้ว`);
    byId('selectionToggle').focus();
  });
  byId('clearReferences').addEventListener('click', () => {
    cards.forEach(card => { checkbox(card).checked = false; }); renderSelection(); announce('ล้างรายการ references แล้ว');
  });
  function toggleSummary(expanded) {
    byId('selectionBody').hidden = !expanded;
    byId('selectionToggle').setAttribute('aria-expanded', String(expanded));
    byId('selectionChevron').className = `bi bi-chevron-${expanded ? 'down' : 'up'} ms-auto`;
  }
  byId('selectionToggle').addEventListener('click', () => toggleSummary(byId('selectionBody').hidden));
  toggleSummary(window.matchMedia('(min-width: 1200px)').matches);
  byId('continueToUpload').addEventListener('click', () => {
    upload.open = true;
    if (!window.matchMedia('(min-width: 1200px)').matches) toggleSummary(false);
    upload.scrollIntoView({behavior: 'smooth', block: 'start'});
    form.querySelector('input[name="data_classification"]').focus({preventScroll:true});
  });

  function syncFiles() {
    const transfer = new DataTransfer();
    files.forEach(file => transfer.items.add(file));
    input.files = transfer.files;
    const total = files.reduce((sum,file) => sum + file.size, 0);
    const tooLarge = total >= 30 * 1024 * 1024;
    input.setCustomValidity(tooLarge ? 'ขนาดไฟล์รวมต้องน้อยกว่า 30 MB' : '');
    byId('fileSummary').textContent = files.length ? `${files.length} ไฟล์ · ${sizeLabel(total)} / 30 MB` : 'ยังไม่ได้เลือกไฟล์';
    byId('selectedFiles').innerHTML = files.map((file,index) => `<li><i class="bi bi-file-earmark-pdf"></i><span>${escape(file.name)}<small>${sizeLabel(file.size)}</small></span><button type="button" data-remove-file="${index}" class="btn btn-sm btn-light" aria-label="นำไฟล์ ${escape(file.name)} ออก"><i class="bi bi-x-lg"></i></button></li>`).join('');
    setError('uploadError', tooLarge ? 'ไฟล์รวมเกินขนาดที่รองรับ กรุณานำบางไฟล์ออก (ต้องน้อยกว่า 30 MB)' : '');
  }
  function addFiles(incoming) {
    const known = new Set(files.map(fileKey));
    let invalid = 0;
    [...incoming].forEach(file => {
      if (!file.name.toLowerCase().endsWith('.pdf')) { invalid++; return; }
      if (!known.has(fileKey(file))) { files.push(file); known.add(fileKey(file)); }
    });
    syncFiles();
    if (invalid) setError('uploadError', `ไม่ได้เพิ่ม ${invalid} ไฟล์ที่ไม่ใช่ PDF กรุณาเลือกเฉพาะไฟล์ .pdf${input.validationMessage ? ' · ' + input.validationMessage : ''}`);
  }
  input.addEventListener('change', () => addFiles(input.files));
  const zone = input.closest('.dropzone');
  ['dragenter','dragover'].forEach(type => zone.addEventListener(type,event => { event.preventDefault(); zone.classList.add('dragover'); }));
  ['dragleave','drop'].forEach(type => zone.addEventListener(type,event => { event.preventDefault(); zone.classList.remove('dragover'); }));
  zone.addEventListener('drop', event => addFiles(event.dataTransfer.files));
  byId('selectedFiles').addEventListener('click', event => {
    const button = event.target.closest('[data-remove-file]');
    if (button) { files.splice(Number(button.dataset.removeFile), 1); syncFiles(); input.focus(); }
  });

  const classDialog = byId('classificationDialog');
  const ack = byId('classificationAcknowledged');
  let acceptedClass = '', pendingClass = '', reviewAfterAck = false;
  const classificationCopy = {
    open: {title:'Open · เอกสารเปิดเผยได้', description:'เอกสาร Open จะส่งข้อความและหลักฐานไปยัง Gemini API ของ Google โปรดใช้เฉพาะเอกสารที่คุณมีสิทธิ์ส่งและไม่มีข้อมูลลับหรือข้อมูลอ่อนไหว', examples:['นโยบายหรือแนวปฏิบัติที่เผยแพร่สาธารณะ','รายงานประจำปีหรือเอกสารประชาสัมพันธ์ที่เปิดเผยได้'], icon:'bi-globe2'},
    confidential: {title:'Confidential · เอกสารภายในหรือข้อมูลลับ', description:'ใช้สำหรับเอกสารภายใน ข้อมูลส่วนบุคคล ความลับทางธุรกิจ หรือข้อมูลที่ต้องจำกัดการเข้าถึง โปรดตรวจสอบว่าคุณมีสิทธิ์นำเอกสารมาประเมิน', examples:['Risk Register / Incident Report ภายใน','ข้อมูลส่วนบุคคลหรือรายละเอียดระบบที่เป็นความลับ'], icon:'bi-shield-lock'}
  };
  function askClassification(value, continueReview = false) {
    const data = classificationCopy[value]; if (!data) return;
    pendingClass = value; reviewAfterAck = continueReview;
    byId('classificationTitle').textContent = data.title;
    byId('classificationDescription').textContent = data.description;
    byId('classificationExamples').innerHTML = data.examples.map(text=>`<li>${escape(text)}</li>`).join('');
    byId('classificationIcon').className = 'bi '+data.icon;
    if (!classDialog.open) classDialog.showModal();
  }
  form.querySelectorAll('[name="data_classification"]').forEach(radio=>radio.addEventListener('change',()=>askClassification(radio.value)));
  function cancelClassification() {
    form.querySelectorAll('[name="data_classification"]').forEach(radio=>{radio.checked=radio.value===acceptedClass;});
    pendingClass=''; reviewAfterAck=false; classDialog.close();
  }
  ['cancelClassification','closeClassification'].forEach(id=>byId(id).addEventListener('click',cancelClassification));
  classDialog.addEventListener('cancel',event=>{event.preventDefault();cancelClassification();});
  byId('acknowledgeClassification').addEventListener('click',()=>{
    if (!pendingClass) return;
    acceptedClass=pendingClass; ack.value=acceptedClass;
    form.querySelectorAll('[name="data_classification"]').forEach(radio=>{radio.checked=radio.value===acceptedClass;});
    byId('classificationStatus').textContent='รับทราบแล้ว · '+classificationCopy[acceptedClass].title;
    const resume=reviewAfterAck; pendingClass='';reviewAfterAck=false;classDialog.close();
    if(resume)form.requestSubmit(byId('reviewAssessment'));
  });

  function stateSignature() {
    return JSON.stringify([suite.value, selected().map(card=>checkbox(card).value),
      form.querySelector('[name="data_classification"]:checked')?.value, [...input.files].map(fileKey)]);
  }
  function showReview() {
    const classification = form.querySelector('[name="data_classification"]:checked').value;
    byId('confirmationDetails').innerHTML = `<div class="confirmation-scope"><small>TEST SUITE</small><strong>${escape(suiteInfo[suite.value]?.name)}</strong><span>${escape(classification === 'open' ? 'Open · เอกสารเปิดเผยได้' : 'Confidential · เอกสารภายในหรือข้อมูลลับ')}</span></div><h3 class="confirmation-subtitle">References ที่เลือก <span>${selected().length}</span></h3>${groupedSelection(false)}<h3 class="confirmation-subtitle">ไฟล์หลักฐาน <span>${input.files.length}</span></h3><ul class="confirmation-files">${[...input.files].map(file=>`<li><i class="bi bi-file-earmark-pdf"></i><span>${escape(file.name)}</span><small>${sizeLabel(file.size)}</small></li>`).join('')}</ul>`;
    reviewedState = stateSignature();
    if (!dialog.open) dialog.showModal();
  }
  // Open the details panel before the browser focuses any invalid required field.
  form.addEventListener('invalid', event => { if (upload.contains(event.target)) upload.open = true; }, true);
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    if (!selected().length) {
      event.preventDefault(); confirmed = false;
      setError('referenceError', 'กรุณาเลือกอย่างน้อย 1 reference ก่อนเริ่มประเมิน');
      byId('referencesTitle').scrollIntoView({block:'center'}); return;
    }
    const chosenClass = form.querySelector('[name="data_classification"]:checked')?.value;
    if (!chosenClass || chosenClass !== acceptedClass || ack.value !== chosenClass) {
      event.preventDefault(); confirmed = false; askClassification(chosenClass, true); return;
    }
    if (!confirmed || reviewedState !== stateSignature()) {
      event.preventDefault(); confirmed = false; showReview(); return;
    }
    confirmed = false; submitting = true;
    byId('confirmAssessment').disabled = true;
    byId('reviewAssessment').disabled = true;
    byId('continueToUpload').disabled = true;
    dialog.close();
  });
  byId('confirmAssessment').addEventListener('click', () => {
    if (submitting) return;
    if (!form.checkValidity()) { dialog.close(); form.reportValidity(); return; }
    if (reviewedState !== stateSignature()) { showReview(); return; }
    confirmed = true;
    form.requestSubmit(byId('reviewAssessment'));
    confirmed = false;
  });
  [byId('closeConfirmation'),byId('cancelConfirmation')].forEach(button => button.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('close', () => { confirmed = false; if (!submitting) byId('reviewAssessment').focus(); });
  window.addEventListener('pageshow', () => {
    submitting = false; confirmed = false;
    byId('confirmAssessment').disabled = false;
    byId('reviewAssessment').disabled = false;
    if (dialog.open) dialog.close();
    files = [...input.files]; syncFiles(); applySuite();
  });
  applySuite();
})();
