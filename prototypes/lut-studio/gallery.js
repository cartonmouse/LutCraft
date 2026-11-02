'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const icons = () => window.lucide?.createIcons();
  const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let data = null, selected = null, busy = false, loadVersion = 0, storyRenderedFor = null;
  const state = {strength:100,category:'all',query:'',limit:48};
  const filtered = () => (data?.items || []).filter(item => (state.category==='all'||item.category===state.category) &&
    [item.label,item.collection,item.sample?.name||'',...item.tags].join(' ').toLocaleLowerCase().includes(state.query.toLocaleLowerCase().trim()));
  const preview = (item, strength=state.strength) => item.sample ? item.previews[item.sample.id]?.[String(strength)] : null;
  function setImage(id, url, alt) { const el=$(id); if(el.getAttribute('src')!==url){el.parentElement.classList.remove('image-error');el.src=url;} el.alt=alt; }
  function updateControls() {
    document.querySelectorAll('[data-strength]').forEach(b=>{b.setAttribute('aria-pressed',String(Number(b.dataset.strength)===state.strength));b.disabled=busy;});
    document.querySelectorAll('[data-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category===state.category)));
  }
  function renderGrid() {
    if(!data)return;
    updateControls();
    const items=filtered();
    $('edition').textContent=`已上架 ${data.items.length} 款`;
    $('result-count').textContent=`${items.length} 款风格`;
    $('style-grid').innerHTML=items.slice(0,state.limit).map(item=>{
      const sample=preview(item,100),ready=item.availability==='ready'||!item.availability;
      const visual=sample?`<img src="${escape(sample.thumbnail_url)}" alt="${escape(item.sample.name+' · '+item.label+' 100%')}" loading="lazy" decoding="async">`:
        `<span class="style-placeholder"><i data-lucide="image" aria-hidden="true"></i><span>样片待配置</span>${ready?'':'<small>照片适配待确认</small>'}</span>`;
      return `<article class="style-card"><button class="style-open" data-style="${escape(item.id)}" aria-label="查看 ${escape(item.label)} 详情"><div class="style-image">${visual}<span class="card-arrow"><i data-lucide="arrow-up-right" aria-hidden="true"></i></span></div><span class="style-copy"><span class="style-title"><strong>${escape(item.label)}</strong><span class="style-category">${item.category==='mono'?'黑白':'彩色'}</span></span><span class="style-sub">${escape(item.sample?.name||item.collection)}${item.tags.length?`<span class="separator">/</span>${escape(item.tags.join(' · '))}`:''}</span></span></button></article>`;
    }).join('');
    $('load-more').hidden=items.length<=state.limit;
    $('empty-state').hidden=!!items.length;$('retry').hidden=true;$('clear-filters').hidden=!!items.length;
    if(!items.length){$('empty-title').textContent='没有找到这个风格';$('empty-description').textContent='试试其他名称、品牌，或清除筛选看看全部风格。';}
    icons();
  }
  function clearApplied() { $('applied-result').hidden=true;$('apply-status').textContent=''; }
  function renderDetail() {
    if(!selected)return;
    const item=data.items.find(r=>r.id===selected);
    const sample=preview(item),ready=item.availability==='ready'||!item.availability;
    if(storyRenderedFor!==item.id){
      storyRenderedFor=item.id;
      const story=item.story;
      $('detail-story').hidden=!story;$('detail-examples').hidden=!story?.examples?.length;
      $('story-headline').textContent=story?.headline||'';
      $('story-description').textContent=story?.description||'';
      $('story-traits').innerHTML=(story?.traits||[]).map(t=>`<li>${escape(t)}</li>`).join('');
      $('story-examples').innerHTML=(story?.examples||[]).map(e=>`<figure><div class="story-image"><img src="${escape(e.url)}" alt="${escape(item.label+' · '+e.title+' · 100% 效果')}" loading="lazy" decoding="async"></div><figcaption><h4>${escape(e.title)}</h4><p>${escape(e.caption)}</p></figcaption></figure>`).join('');
    }
    $('detail-title').textContent=item.label;$('detail-brand').textContent=item.collection;
    $('detail-tags').textContent=item.tags.join(' · ');
    $('detail-result-label').textContent=`${item.label} · ${state.strength}%`;
    $('apply-choice').textContent=`${item.label} · ${state.strength}% 强度`;
    $('sample-comparison').hidden=!sample;
    $('detail-placeholder').hidden=!!sample;
    $('detail-placeholder').textContent=ready?'样片待配置，可以先用于自己的照片。':item.availability_note||'已收录，照片适配待确认。';
    $('detail-strength').hidden=!ready;
    $('use-style').hidden=!ready;
    if(!ready)$('apply-panel').hidden=true;
    $('detail-sample').textContent=sample?`${item.sample.name} · ${item.sample.kind==='ai-generated'?'AI 生成样片':'样片'}`:'样片待配置';
    if(sample){
      setImage('detail-original',item.sample.original_url,item.sample.name+'原图');
      setImage('detail-result',sample.url,`${item.sample.name}应用 ${item.label} ${state.strength}% 的效果`);
    }
    const list=filtered(),index=list.findIndex(r=>r.id===selected);
    $('previous-style').disabled=busy||index<=0;$('next-style').disabled=busy||index<0||index>=list.length-1;
    $('photo-file').disabled=busy;$('apply-submit').disabled=busy||!$('photo-file').files.length;
    $('apply-submit').textContent=busy?'正在处理…':'应用并保存';
    updateControls();
  }
  function choose(id) {
    if(busy)return;
    selected=id;clearApplied();$('apply-panel').hidden=true;$('photo-file').value='';
    renderDetail();if(!$('style-dialog').open)$('style-dialog').showModal();
    $('style-dialog').scrollTop=0;
  }
  function changeSetting(button) {
    if(busy)return;
    if(button.dataset.strength){state.strength=Number(button.dataset.strength);clearApplied();}
    else if(button.dataset.category){state.category=button.dataset.category;state.limit=48;}
    renderGrid();renderDetail();
  }
  async function load() {
    const version=++loadVersion;$('style-grid').setAttribute('aria-busy','true');$('retry').hidden=true;
    try {
      const response=await fetch('/api/styles');const value=await response.json();
      if(version!==loadVersion)return;
      if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'无法读取风格预览。');
      if(value.status!=='ready')throw new Error('样片预览尚未准备好，请稍后重新加载。');
      data=value;renderGrid();
    } catch(error) {
      $('empty-state').hidden=false;$('empty-title').textContent='暂时无法载入图库';$('empty-description').textContent=error.message;
      $('result-count').textContent='图库未载入';$('retry').hidden=false;$('clear-filters').hidden=true;
    } finally { $('style-grid').setAttribute('aria-busy','false'); }
  }
  document.addEventListener('click',event=>{
    const b=event.target.closest('button');if(!b)return;
    if(b.dataset.strength||b.dataset.category)changeSetting(b);
    else if(b.dataset.style)choose(b.dataset.style);
  });
  $('style-search').addEventListener('input',event=>{state.query=event.target.value;state.limit=48;renderGrid();});
  $('clear-filters').addEventListener('click',()=>{state.query='';state.category='all';state.limit=48;$('style-search').value='';renderGrid();});
  $('load-more').addEventListener('click',()=>{state.limit+=48;renderGrid();});
  $('retry').addEventListener('click',load);
  $('close-detail').addEventListener('click',()=>$('style-dialog').close());
  for(const [id,delta] of [['previous-style',-1],['next-style',1]])$(id).addEventListener('click',()=>{const list=filtered(),i=list.findIndex(r=>r.id===selected);if(list[i+delta])choose(list[i+delta].id);});
  $('style-dialog').addEventListener('keydown',event=>{
    if(busy||event.target.matches('input'))return;
    if(event.key==='ArrowLeft'){event.preventDefault();$('previous-style').click();}
    if(event.key==='ArrowRight'){event.preventDefault();$('next-style').click();}
  });
  $('use-style').addEventListener('click',()=>{$('apply-panel').hidden=false;$('photo-file').focus();});
  $('photo-file').addEventListener('change',()=>{
    clearApplied();const file=$('photo-file').files[0];
    if(file&&file.size>10*1024*1024){$('apply-status').dataset.state='error';$('apply-status').textContent='照片超过 10 MB，请选择较小的 JPEG 或 PNG。';$('photo-file').value='';}
    renderDetail();
  });
  $('apply-form').addEventListener('submit',async event=>{
    event.preventDefault();const file=$('photo-file').files[0];if(!file||busy)return;
    const item=data.items.find(r=>r.id===selected),strength=state.strength;
    busy=true;renderDetail();$('apply-status').dataset.state='busy';$('apply-status').textContent='正在从原图应用风格并保存，请稍候…';
    try {
      const query=new URLSearchParams({build_id:data.id,lut_id:item.id,strength:String(strength/100)});
      const response=await fetch('/api/styles/apply?'+query,{method:'POST',headers:{'Content-Type':'application/octet-stream','x-lut-preview-token':data.token,'x-photo-name':encodeURIComponent(file.name)},body:file});
      const value=await response.json();
      if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'照片处理失败，请重新选择 JPEG 或 PNG 后重试。');
      setImage('own-original',value.original_url,'你的原图');setImage('own-result',value.result_url,`你的照片 · ${item.label} ${strength}%`);
      $('own-result-label').textContent=`${item.label} · ${strength}%`;
      $('download-result').href=value.result_url;$('download-result').download=`${item.id}-${strength}.${value.result_url.endsWith('.png')?'png':'jpg'}`;
      $('saved-result-link').href=value.url;$('applied-result').hidden=false;
      $('apply-status').dataset.state='success';$('apply-status').textContent=`已保存 · ${value.width} × ${value.height}，原图同时保留。`;
      $('page-status').textContent='你的照片已处理并保存，可在“我的结果”中查看。';
    } catch(error) {$('apply-status').dataset.state='error';$('apply-status').textContent=error.message||'连接中断，请重试。';}
    finally {busy=false;renderDetail();}
  });
  document.addEventListener('error',event=>{if(event.target.tagName==='IMG')event.target.parentElement.classList.add('image-error');},true);
  document.addEventListener('load',event=>{if(event.target.tagName==='IMG')event.target.parentElement.classList.remove('image-error');},true);
  icons();load();
})();
