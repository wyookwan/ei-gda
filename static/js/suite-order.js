(() => {
  const list = document.getElementById('suiteOrderList');
  if (!list) return;
  const status = document.getElementById('suiteOrderStatus');
  const readOrder = () => [...list.children].map(row => Number(row.dataset.suiteId));
  let savedOrder = readOrder(), busy = false, sortable = null, dragged = null;
  function updateControls() {
    [...list.children].forEach((row,index) => {
      row.querySelector('.suite-order-number').textContent = String(index + 1).padStart(2, '0');
      row.querySelector('[data-move="up"]').disabled = busy || index === 0;
      row.querySelector('[data-move="down"]').disabled = busy || index === list.children.length - 1;
    });
    list.setAttribute('aria-busy', String(busy));
    sortable?.option('disabled', busy);
  }
  function restore(order) {
    const rows = new Map([...list.children].map(row => [Number(row.dataset.suiteId), row]));
    order.forEach(id => list.append(rows.get(id)));
  }
  async function save() {
    if (busy) return;
    const nextOrder = readOrder();
    if (JSON.stringify(nextOrder) === JSON.stringify(savedOrder)) { updateControls(); return; }
    busy = true; updateControls();
    status.textContent = 'กำลังบันทึกลำดับ…'; status.classList.remove('is-error');
    try {
      const response = await fetch(list.dataset.saveUrl, {
        method:'POST', credentials:'same-origin',
        headers:{'Content-Type':'application/json', 'X-Suite-Order-Token':list.dataset.orderToken},
        body:JSON.stringify({order:nextOrder, previous_order:savedOrder})
      });
      if (response.redirected) throw new Error('เซสชันหมดอายุ กรุณารีเฟรชและเข้าสู่ระบบใหม่');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'บันทึกลำดับไม่ได้');
      if (JSON.stringify(data.order) !== JSON.stringify(nextOrder)) throw new Error('ผลบันทึกไม่ตรงกัน กรุณารีเฟรชหน้า');
      savedOrder = data.order;
      savedOrder.forEach(id => {
        const editor = document.querySelector(`[data-suite-edit-id="${id}"]`);
        if (editor) editor.parentElement.append(editor);
      });
      status.textContent = 'บันทึกลำดับแล้ว · หน้าที่เปิดใหม่จะแสดงตามลำดับนี้';
    } catch(error) {
      restore(savedOrder);
      status.textContent = `${error.message} · คืนลำดับที่แสดงเป็นค่าก่อนแก้ไขแล้ว`;
      status.classList.add('is-error');
    } finally { busy = false; updateControls(); }
  }
  list.addEventListener('click', event => {
    const button = event.target.closest('[data-move]');
    if (!button || busy || button.disabled) return;
    const row = button.closest('[data-suite-id]');
    if (button.dataset.move === 'up' && row.previousElementSibling) list.insertBefore(row,row.previousElementSibling);
    else if (button.dataset.move === 'down' && row.nextElementSibling) list.insertBefore(row.nextElementSibling,row);
    save();
  });
  if (window.Sortable) {
    sortable = new Sortable(list, {handle:'.suite-drag-handle', animation:180, ghostClass:'suite-order-ghost', onEnd:save});
  } else {
    // Native fallback plus up/down buttons when the optional CDN is unavailable.
    [...list.children].forEach(row => {
      row.draggable = true;
      row.addEventListener('dragstart', event => {
        if (busy) { event.preventDefault(); return; }
        dragged = row; event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain',row.dataset.suiteId);
      });
      row.addEventListener('dragover', event => { if (dragged && !busy) event.preventDefault(); });
      row.addEventListener('drop', event => {
        event.preventDefault(); if (!dragged || busy || dragged === row) return;
        const below = event.clientY > row.getBoundingClientRect().top + row.getBoundingClientRect().height / 2;
        list.insertBefore(dragged,below ? row.nextSibling : row); dragged = null; save();
      });
      row.addEventListener('dragend', () => { dragged = null; });
    });
  }
  updateControls();
})();
