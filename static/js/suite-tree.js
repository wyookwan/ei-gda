(() => {
  const root = document.getElementById('suiteTree');
  if (!root) return;
  const search = document.getElementById('suiteTreeSearch');
  const nodes = [...root.querySelectorAll('.tree-node')];
  const suites = nodes.filter(node => node.dataset.level === 'suite');
  const labels = new Map(nodes.map(node => [node, `${node.querySelector(':scope > summary .tree-label').textContent} ${node.dataset.evidenceSearch || ''}`.toLocaleLowerCase()]));
  const children = new Map(nodes.map(node => [node, [...node.querySelectorAll(':scope > .tree-children > .tree-node')]]));
  let savedOpen = null;
  function filter() {
    const query = search.value.trim().toLocaleLowerCase();
    if (query && savedOpen === null) savedOpen = new Set(nodes.filter(node => node.open));
    let visibleItems = 0;
    function visit(node, parentMatch) {
      const ownMatch = !!query && labels.get(node).includes(query);
      const inherited = parentMatch || ownMatch;
      const childResults = children.get(node).map(child => visit(child, inherited));
      const visible = !query || inherited || childResults.some(Boolean);
      node.hidden = !visible;
      if (query) node.open = visible && !parentMatch;
      else if (savedOpen !== null) node.open = savedOpen.has(node);
      if (visible && node.dataset.level === 'item') visibleItems++;
      return visible;
    }
    suites.forEach(node => visit(node, false));
    const count = suites.filter(node => !node.hidden).length;
    document.getElementById('suiteTreeStatus').textContent = `${count} Test Suites · ${visibleItems} รายการประเมิน${query ? 'ที่ตรงกับคำค้น' : ' (นับรวมรายการที่ใช้ร่วมกันระหว่าง Suites)'}`;
    document.getElementById('suiteTreeEmpty').hidden = !query || count > 0;
    if (!query) savedOpen = null;
  }
  search.addEventListener('input', filter);
  document.getElementById('expandSuiteTree').addEventListener('click', () => nodes.forEach(node => { if (!node.hidden) node.open = true; }));
  document.getElementById('collapseSuiteTree').addEventListener('click', () => nodes.forEach(node => { node.open = false; }));
  filter();
})();
