// Usage: NODE_PATH=/path/to/test/node_modules node tests/test_dashboard.cjs rendered-dashboard.html
// Uses jsdom only; no browser session, real upload, database, or AI request.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');
const errors = [];
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', error => errors.push(error.message));
const dom = new JSDOM(fs.readFileSync(process.argv[2], 'utf8'), {url:'http://localhost/dashboard', runScripts:'outside-only', pretendToBeVisual:true, virtualConsole});
const w = dom.window, d = w.document;
w.matchMedia = () => ({matches:true});
w.HTMLElement.prototype.scrollIntoView = function() {};
w.HTMLDialogElement.prototype.showModal = function() { this.open=true; };
w.HTMLDialogElement.prototype.close = function() { this.open=false; this.dispatchEvent(new w.Event('close')); };
// jsdom has no DataTransfer. Populate a genuine FileList for native form validation.
const jsdomDir=path.dirname(require.resolve('jsdom/package.json'));
const generated=fs.existsSync(path.join(jsdomDir,'lib/generated/idl/utils.js')) ? 'lib/generated/idl' : 'lib/jsdom/living/generated';
const {implForWrapper}=require(path.join(jsdomDir,generated,'utils.js'));
w.DataTransfer = class {
  constructor() {
    const fileInput=d.createElement('input');fileInput.type='file';this.files=fileInput.files;
    this.items={add:file=>implForWrapper(this.files).push(implForWrapper(file))};
  }
};
const sent=[];
w.HTMLFormElement.prototype.requestSubmit = function() {
  if (!this.reportValidity()) return;
  const event = new w.Event('submit',{bubbles:true,cancelable:true});
  if (this.dispatchEvent(event)) sent.push(new w.FormData(this));
};
const byId=id=>d.getElementById(id);
const change=el=>el.dispatchEvent(new w.Event('change',{bubbles:true}));
const cards=()=>[...d.querySelectorAll('[data-framework-code]')];
const control=card=>card.querySelector('input');
const cardFor=code=>cards().find(card=>card.dataset.frameworkCode===code);
const choose=code=>{const card=cardFor(code);assert.ok(!control(card).disabled,code);control(card).checked=true;change(control(card));};
const activeTab=()=>d.querySelector('[data-reference-tab][aria-selected="true"]');
const visibleCards=()=>cards().filter(card=>!card.hidden);
const suite=byId('tnagfTemplateSelect');
function setSuite(name) { suite.value=[...suite.options].find(o=>o.textContent===name).value;change(suite); }
function addFiles(files) {
  const transfer=new w.DataTransfer(); files.forEach(file=>transfer.items.add(file));
  byId('assessmentFiles').files=transfer.files;change(byId('assessmentFiles'));
}
w.eval(fs.readFileSync('static/js/app.js','utf8'));
w.eval(fs.readFileSync('static/js/dashboard.js','utf8'));
(async()=>{
  if(d.readyState==='loading') await new Promise(resolve=>d.addEventListener('DOMContentLoaded',resolve,{once:true}));
  await new Promise(resolve=>w.setTimeout(resolve,0));
  const form=byId('assessmentBuilder');
  assert.equal(byId('frameworkSelectionList').hidden,true);
  assert.equal(byId('continueToUpload').disabled,true);
  // All eight suites display eligible tabs, standards first, at most two rows per page.
  for(const option of [...suite.options].filter(o=>o.value)) {
    suite.value=option.value;change(suite);
    assert.equal(activeTab().dataset.referenceTab,'international_standard');
    assert.ok(visibleCards().length>0 && visibleCards().length<=6);
    for(const card of visibleCards()) assert.equal(control(card).disabled,false);
  }
  setSuite('AI Data Quality & Governance');
  assert.equal(visibleCards().length,6);
  choose('ISO5259_1');
  byId('referenceNext').click();
  assert.equal(control(cardFor('ISO5259_1')).checked,true);
  assert.ok(visibleCards().length<=6);
  byId('referenceSearch').value='__no_such_reference__';
  byId('referenceSearch').dispatchEvent(new w.Event('input'));
  assert.equal(byId('referenceSearchEmpty').hidden,false);
  assert.equal(byId('referencePageLabel').textContent,'0 รายการ');
  byId('tab-thai_law').click();
  choose('TH_PDPA_2562');
  assert.ok(byId('selectionGroups').textContent.includes('Thai Laws'));
  assert.ok(byId('selectionGroups').textContent.includes('International Standards'));
  assert.equal(control(cardFor('ISO5259_1')).checked,true);
  byId('selectionToggle').click();assert.equal(byId('selectionBody').hidden,true);
  byId('selectionToggle').click();assert.equal(byId('selectionBody').hidden,false);
  // Changing suites retains shared references but removes inapplicable ones.
  setSuite('AI Risk, Security & Privacy');
  assert.equal(control(cardFor('ISO5259_1')).checked,false);
  assert.equal(control(cardFor('ISO5259_1')).disabled,true);
  assert.equal(control(cardFor('TH_PDPA_2562')).checked,true);
  assert.ok(byId('selectionAnnouncement').textContent.includes('1'));
  choose('ISO27090'); // Draft classification stays separate in the summary and modal.
  assert.ok(byId('selectionGroups').textContent.includes('Draft readiness'));
  d.querySelector(`[data-remove-reference="${control(cardFor('ISO27090')).value}"]`).click();
  assert.equal(control(cardFor('ISO27090')).checked,false);
  choose('ISO27090');
  byId('continueToUpload').click();assert.equal(byId('assessmentUpload').open,true);
  form.requestSubmit();assert.equal(byId('assessmentConfirmDialog').open,false);assert.equal(sent.length,0);
  const openRadio=d.querySelector('[name="data_classification"][value="open"]');
  const confidentialRadio=d.querySelector('[name="data_classification"][value="confidential"]');
  openRadio.checked=true;change(openRadio);
  assert.equal(byId('classificationDialog').open,true);
  assert.equal(byId('classificationAcknowledged').value,'');
  byId('cancelClassification').click();assert.equal(openRadio.checked,false);
  confidentialRadio.checked=true;change(confidentialRadio);
  assert.equal(byId('classificationDialog').open,true);
  byId('acknowledgeClassification').click();
  assert.equal(byId('classificationAcknowledged').value,'confidential');
  openRadio.checked=true;change(openRadio);
  byId('classificationDialog').dispatchEvent(new w.Event('cancel',{cancelable:true}));
  assert.equal(confidentialRadio.checked,true);
  assert.equal(byId('classificationAcknowledged').value,'confidential');
  const first=new w.File(['test pdf'],'evidence-one.pdf',{type:'application/pdf',lastModified:1});
  const second=new w.File(['second'],'evidence-two.pdf',{type:'application/pdf',lastModified:2});
  addFiles([first]);addFiles([second,first]);
  assert.equal(byId('assessmentFiles').files.length,2);
  addFiles([new w.File(['no'],'rejected.txt',{type:'text/plain'})]);
  assert.equal(byId('assessmentFiles').files.length,2);
  assert.equal(byId('uploadError').hidden,false);
  d.querySelector('[data-remove-file="1"]').click();
  assert.equal(byId('assessmentFiles').files.length,1);
  const hostileName=new w.File(['x'],'<img src=x onerror=alert(1)>.pdf',{lastModified:3});
  addFiles([hostileName]);
  assert.equal(byId('selectedFiles').querySelector('img'),null);
  form.requestSubmit();
  assert.equal(byId('assessmentConfirmDialog').open,true);
  assert.ok(byId('confirmationDetails').textContent.includes('AI Risk, Security & Privacy'));
  assert.ok(byId('confirmationDetails').textContent.includes('Confidential'));
  assert.ok(byId('confirmationDetails').textContent.includes('ISO27090'));
  assert.ok(byId('confirmationDetails').textContent.includes('TH_PDPA_2562'));
  assert.equal(byId('confirmationDetails').querySelector('img'),null);
  await Promise.resolve();
  assert.equal(byId('nodeLoader').classList.contains('is-visible'),false);
  byId('cancelConfirmation').click();assert.equal(sent.length,0);
  assert.equal(byId('assessmentFiles').files.length,2);
  // A state change after review must show an updated review before any submission.
  form.requestSubmit();
  control(cardFor('ISO27090')).checked=false;change(control(cardFor('ISO27090')));
  byId('confirmAssessment').click();assert.equal(sent.length,0);
  assert.ok(!byId('confirmationDetails').textContent.includes('ISO27090'));
  byId('cancelConfirmation').click();
  // Zero references cannot reach confirmation or submit even when other fields are valid.
  byId('clearReferences').click();form.requestSubmit();
  assert.equal(byId('referenceError').hidden,false);assert.equal(byId('assessmentConfirmDialog').open,false);
  choose('ISO27090');choose('TH_PDPA_2562');
  // Enforce file-size limit and allow recovery by removing the oversized file.
  const huge=new w.File(['x'],'oversized.pdf',{lastModified:4});Object.defineProperty(huge,'size',{value:31*1024*1024});
  addFiles([huge]);assert.ok(byId('assessmentFiles').validationMessage.includes('30 MB'));
  form.requestSubmit();assert.equal(byId('assessmentConfirmDialog').open,false);
  d.querySelector('[data-remove-file="2"]').click();
  assert.equal(byId('assessmentFiles').validationMessage,'');
  // First submit only reviews; the explicit confirm sends exactly the reviewed controls.
  form.requestSubmit();assert.equal(sent.length,0);
  byId('confirmAssessment').click();byId('confirmAssessment').click();
  assert.equal(sent.length,1);
  assert.deepEqual(sent[0].getAll('standard_ids').sort(),[control(cardFor('ISO27090')).value,control(cardFor('TH_PDPA_2562')).value].sort());
  assert.equal(sent[0].get('test_suite_id'),suite.value);
  assert.equal(sent[0].get('data_classification'),'confidential');
  assert.equal(sent[0].get('classification_acknowledged'),'confidential');
  assert.equal(sent[0].getAll('pdf_files').length,2);
  // Back navigation restores an interactive page rather than a disabled submit button.
  w.dispatchEvent(new w.Event('pageshow'));
  assert.equal(byId('reviewAssessment').disabled,false);
  assert.equal(byId('assessmentConfirmDialog').open,false);
  assert.deepEqual(errors,[]);
  console.log('PASS: 8 suites, tabs/pagination/search, grouped selection, collapse/remove/clear, suite filtering, PDF accumulation/removal/type/size, escaped names, modal cancel, no pre-confirm upload, exact confirmed payload, duplicate-submit guard, back navigation.');
  w.close();
})().catch(error=>{console.error(error);w.close();process.exitCode=1;});
