(() => {
  const root=document.getElementById('suiteAdminWorkspace');if(!root)return;
  const tabs=[...root.querySelectorAll('[data-admin-tab]')];
  function activate(name){
    tabs.forEach(button=>{const active=button.dataset.adminTab===name;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
    root.querySelectorAll('[data-admin-panel]').forEach(panel=>{panel.hidden=panel.dataset.adminPanel!==name;});
  }
  tabs.forEach((button,index)=>{
    const name=button.dataset.adminTab;button.id='admin-tab-'+name;button.setAttribute('aria-controls','admin-panel-'+name);
    const panel=root.querySelector(`[data-admin-panel="${name}"]`);panel.id='admin-panel-'+name;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',button.id);
    button.addEventListener('click',()=>activate(name));
    button.addEventListener('keydown',event=>{let next;if(event.key==='ArrowRight')next=(index+1)%tabs.length;if(event.key==='ArrowLeft')next=(index+tabs.length-1)%tabs.length;if(event.key==='Home')next=0;if(event.key==='End')next=tabs.length-1;if(next!==undefined){event.preventDefault();tabs[next].click();tabs[next].focus();}});
  });
  const select=document.getElementById('adminSuiteSelect');
  function showSuite(){root.querySelectorAll('[data-suite-edit-id]').forEach(form=>{form.hidden=form.dataset.suiteEditId!==select.value;});}
  select.addEventListener('change',showSuite);
  root.querySelectorAll('[data-mapping-search]').forEach(input=>input.addEventListener('input',()=>{
    const query=input.value.trim().toLocaleLowerCase();
    input.nextElementSibling.querySelectorAll('[data-mapping-row]').forEach(row=>{row.hidden=!row.dataset.search.toLocaleLowerCase().includes(query);});
  }));
  activate('edit');showSuite();
})();
