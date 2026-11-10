(() => {
  const root = document.getElementById('reportWorkspace');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const score = item => item.score !== null && item.score !== undefined && item.score !== '' && Number.isFinite(Number(item.score)) && Number(item.score) >= 0 && Number(item.score) <= 5 ? Number(item.score) : null;
  const reference = item => item.standard || item.standard_code || 'OTHER';
  const evidence = item => Array.isArray(item.evidence) ? item.evidence : [];
  const rows = JSON.parse($('report-results-json').textContent).map((item,index) => ({...item,index}));
  const colors = ['#c24145','#e27925','#b89116','#258bb4','#4265cf','#16856e'];
  const color = value => value === null ? '#94a3b8' : colors[Math.floor(value)];
  let page = 0, chartPage = 0, active = null, category = '';
  const pageSize = 6;
  const tabs = [...root.querySelectorAll('[data-report-tab]')];
  function tab(name) {
    tabs.forEach(button => {
      const selected = button.dataset.reportTab === name;
      button.setAttribute('aria-selected',String(selected)); button.tabIndex = selected ? 0 : -1;
      $('report-' + button.dataset.reportTab).hidden = !selected;
    });
  }
  tabs.forEach((button,index) => {
    button.addEventListener('click', () => tab(button.dataset.reportTab));
    button.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index+1)%tabs.length;
      if (event.key === 'ArrowLeft') next = (index+tabs.length-1)%tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length-1;
      if (next !== undefined) { event.preventDefault(); tabs[next].click(); tabs[next].focus(); }
    });
  });
  const known = new Set([...$('reportReference').options].map(option=>option.value));
  rows.forEach(item => { if (!known.has(reference(item))) { const option = new Option(reference(item), reference(item)); $('reportReference').add(option); known.add(reference(item)); } });
  const searchable = item => [reference(item), item.item_code,item.title,item.category,item.reason,item.gap,item.recommendation,item.maturity,...evidence(item).flatMap(e=>[e.filename,e.snippet])].join(' ').toLocaleLowerCase();
  function filtered() {
    const query = $('reportSearch').value.trim().toLocaleLowerCase(), ref = $('reportReference').value, filter = $('reportScore').value;
    return rows.filter(item => (!query || searchable(item).includes(query)) && (!ref || reference(item) === ref) && (!category || (item.category || 'Other') === category) &&
      (!filter || (filter === 'low' ? score(item) !== null && score(item) < 3 : filter === 'missing' ? !evidence(item).length : filter === 'unscored' ? score(item) === null : score(item) !== null && Math.floor(score(item)) === Number(filter))));
  }
  function detail(item) {
    const panel = $('reportItemDetail');
    if (!item) { panel.innerHTML = '<div class="report-empty"><i class="bi bi-search"></i><h3>ไม่พบรายการ</h3><p>ลองเปลี่ยนคำค้นหาหรือล้างตัวกรอง</p></div>'; return; }
    const s = score(item);
    panel.innerHTML = `<div class="report-detail-top"><span class="data-chip">${esc(reference(item))}</span><span class="report-score" style="--score-color:${color(s)}">${s ?? '—'} / 5</span></div><h2>${esc(item.item_code)} · ${esc(item.title)}</h2><p class="text-secondary">${esc(item.category || 'Other')} · ${esc(item.maturity || 'ยังไม่มีระดับ Maturity')}</p><section><h3>Assessment reason</h3><p>${esc(item.reason || '—')}</p></section><div class="report-gap-grid"><section><h3>Gap</h3><p>${esc(item.gap || '—')}</p></section><section><h3>Recommendation</h3><p>${esc(item.recommendation || '—')}</p></section></div><section><h3>Traceable evidence <span class="data-chip">${evidence(item).length}</span></h3>${evidence(item).map(e => `<div class="report-evidence"><strong>${esc(e.filename || 'Source PDF')} · p.${esc(e.page ?? '—')}</strong><p>${esc(e.snippet || '—')}</p>${Number.isInteger(Number(e.file_id)) && Number(e.file_id)>0 ? `<a class="btn btn-sm btn-outline-primary" target="_blank" rel="noopener" href="/check/${Number(root.dataset.checkId)}/source/${Number(e.file_id)}#page=${Math.max(1,Number(e.page)||1)}">เปิดหน้าหลักฐาน ↗</a>` : ''}</div>`).join('') || '<p>ไม่พบหลักฐานระดับหน้าเอกสารสำหรับรายการนี้</p>'}</section>`;
    panel.scrollTop = 0;
  }
  function renderItems() {
    const list = filtered(), pages = Math.max(1,Math.ceil(list.length/pageSize));
    page = Math.min(page,pages-1);
    const visible = list.slice(page*pageSize,(page+1)*pageSize);
    if (!visible.some(item=>item.index === active)) active = visible[0]?.index ?? null;
    $('reportItemList').innerHTML = visible.map(item=>`<button type="button" class="report-item ${item.index === active ? 'selected' : ''}" data-item-index="${item.index}" aria-pressed="${item.index === active}"><span><small>${esc(reference(item))} · ${esc(item.item_code)}</small><strong>${esc(item.title || 'Untitled item')}</strong><small>${evidence(item).length} evidence · ${esc(item.maturity || '—')}</small></span><span class="report-score" style="--score-color:${color(score(item))}">${score(item) ?? '—'}<small>/5</small></span></button>`).join('') || '<p class="report-empty">ไม่มีรายการตรงกับตัวกรอง</p>';
    $('reportPageStatus').textContent = `${list.length ? page*pageSize+1 : 0}–${Math.min((page+1)*pageSize,list.length)} / ${list.length} รายการ${category ? ' · หมวด: '+category : ''}`;
    $('reportPrev').disabled = page === 0; $('reportNext').disabled = page >= pages-1;
    detail(rows.find(item=>item.index === active));
  }
  $('reportItemList').addEventListener('click', event => { const button=event.target.closest('[data-item-index]'); if(button){active=Number(button.dataset.itemIndex);renderItems();$('reportItemList').querySelector(`[data-item-index="${active}"]`).focus();} });
  ['reportSearch','reportReference','reportScore'].forEach(id => $(id).addEventListener(id === 'reportSearch' ? 'input' : 'change', () => { page=0;renderItems(); }));
  function reset() { $('reportSearch').value='';$('reportReference').value='';$('reportScore').value='';category='';page=0; }
  $('reportReset').addEventListener('click',()=>{reset();renderItems();});
  $('reportPrev').addEventListener('click',()=>{page--;renderItems();});
  $('reportNext').addEventListener('click',()=>{page++;renderItems();});
  const valid = rows.filter(item=>score(item)!==null), traced=rows.filter(item=>evidence(item).length).length, low=valid.filter(item=>score(item)<3).length;
  $('reportInsights').innerHTML = `<div><small>ITEMS ASSESSED</small><strong>${rows.length}</strong><span>${valid.length} รายการมีคะแนน</span></div><button type="button" data-insight="low"><small>FOCUS NEXT</small><strong>${low}</strong><span>คะแนนต่ำกว่า 3 · ดูรายการ →</span></button><button type="button" data-insight="missing"><small>EVIDENCE COVERAGE</small><strong>${rows.length ? Math.round(traced/rows.length*100)+'%' : '—'}</strong><span>${traced}/${rows.length} รายการมีหลักฐาน · ดูที่ยังไม่มี →</span></button>`;
  $('reportInsights').addEventListener('click',event=>{const button=event.target.closest('[data-insight]');if(button){reset();$('reportScore').value=button.dataset.insight;renderItems();tab('items');$('tab-items').focus();}});
  let chartEntries=[];
  function chart() {
    const view=$('reportChartView').value;
    $('reportChartTitle').textContent={reference:'Reference maturity',category:'Category maturity',distribution:'Maturity distribution',heatmap:'Item score map'}[view];
    if(view==='reference'||view==='category') {
      const groups=new Map();rows.forEach(item=>{const key=view==='reference'?reference(item):item.category||'Other';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);});
      chartEntries=[...groups].map(([label,items])=>{const scored=items.filter(item=>score(item)!==null);return {label,value:scored.length?scored.reduce((sum,item)=>sum+score(item),0)/scored.length:null,count:items.length,scored:scored.length};});
      chartEntries.sort((a,b)=>(a.value??6)-(b.value??6)||a.label.localeCompare(b.label));
    } else if(view==='distribution') chartEntries=[0,1,2,3,4,5,null].map(value=>({label:value===null?'ยังไม่มีคะแนน':value===5?'5':`${value}–<${value+1}`,value,count:rows.filter(item=>value===null?score(item)===null:score(item)!==null&&Math.floor(score(item))===value).length}));
    else chartEntries=rows.map(item=>({label:item.item_code||item.title,value:score(item),item}));
    const size=view==='heatmap'?30:8, pages=Math.max(1,Math.ceil(chartEntries.length/size)); chartPage=Math.min(chartPage,pages-1);
    const visible=chartEntries.slice(chartPage*size,(chartPage+1)*size);
    $('reportChart').className='report-chart '+(view==='heatmap'?'report-heatmap':'');
    $('reportChart').innerHTML = visible.map((entry,index)=>{
      const label=esc(entry.label), value=entry.value===null?'—':entry.value.toFixed(view==='distribution'||view==='heatmap'?0:2);
      if(view==='heatmap')return `<button type="button" class="report-heat-cell" data-chart-index="${chartPage*size+index}" style="--score-color:${color(entry.value)}" title="${esc(reference(entry.item)+' · '+entry.item.title)}"><strong>${value}</strong><span>${label}</span><small>${esc(reference(entry.item))}</small></button>`;
      const percent=view==='distribution'?(rows.length?entry.count/rows.length*100:0):(entry.value??0)*20;
      return `<button type="button" class="report-bar-row" data-chart-index="${chartPage*size+index}"><span class="report-bar-label">${label}<small>${view==='distribution'?'รายการตามช่วงคะแนน':`${entry.scored}/${entry.count} items มีคะแนน`}</small></span><span class="report-bar-track"><span style="width:${percent}%;background:${color(entry.value)}"></span></span><strong>${view==='distribution'?entry.count+' items':value+' / 5'}</strong></button>`;
    }).join('') || '<div class="report-empty">ยังไม่มีผลประเมินสำหรับสร้างกราฟ</div>';
    $('chartPageStatus').textContent=`${chartEntries.length ? chartPage*size+1 : 0}–${Math.min((chartPage+1)*size,chartEntries.length)} / ${chartEntries.length} ${view==='heatmap'?'items':'กลุ่ม'} · ${view==='heatmap'?'สีแดง → เขียว: คะแนน 0 → 5 · เทา: ไม่มีคะแนน':'แสดงทุกกลุ่มด้วยการเปลี่ยนหน้า'}`;
    $('chartPrev').disabled=chartPage===0;$('chartNext').disabled=chartPage>=pages-1;
  }
  $('reportChart').addEventListener('click',event=>{
    const button=event.target.closest('[data-chart-index]');if(!button)return;
    const entry=chartEntries[Number(button.dataset.chartIndex)],view=$('reportChartView').value;reset();
    if(view==='reference')$('reportReference').value=entry.label;
    if(view==='category')category=entry.label;
    if(view==='distribution')$('reportScore').value=entry.value===null?'unscored':String(entry.value);
    if(view==='heatmap'){active=entry.item.index;page=Math.floor(entry.item.index/pageSize);}
    renderItems();tab('items');$('tab-items').focus();
  });
  $('reportChartView').addEventListener('change',()=>{chartPage=0;chart();});
  $('chartPrev').addEventListener('click',()=>{chartPage--;chart();});$('chartNext').addEventListener('click',()=>{chartPage++;chart();});
  renderItems();chart();
})();
