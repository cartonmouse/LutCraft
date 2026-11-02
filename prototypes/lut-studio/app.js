'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const icons = () => window.lucide?.createIcons();
  const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const base = new URL('./', location.href);
  const run = new URL(location.href).searchParams.get('run');
  let gallery = null, active = 0, polling = false;
  let manualItems = [], manualToken = '', manualBusy = false, manualRequest = 0;
  const originalPhotos = new Set();
  let historyItems = [], historyNext = null, historyLoading = false, latestId = null;
  const dateFormat = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
  const formatDate = value => dateFormat.format(new Date(value));
  function renderHistory() {
    $('history-list').innerHTML = historyItems.map(item => {
      const selected=item.id===gallery?.id;
      const name=item.names.slice(0,2).join('、')+(item.names.length>2?' 等':'');
      const date=formatDate(item.created_at);
      const luts=item.lut_names.join(' · ');
      return `<a class="history-item${selected?' selected':''}" href="${escape(new URL(item.url,base).href)}" ${selected?'aria-current="page"':''} aria-label="查看 ${escape(date)} 保存的 ${item.photo_count} 张照片"><img src="${escape(new URL(item.cover_url,base).href)}" alt="${escape(item.names[0])}的调色缩略图" loading="lazy" decoding="async"><span class="history-copy"><time datetime="${escape(item.created_at)}">${escape(date)}</time><strong>${escape(name)}</strong><span class="history-luts" title="${escape(luts)}">${item.photo_count} 张照片 · ${escape(luts)}</span><span class="history-badges">${item.id===latestId?'<span>最新</span>':''}${selected?'<span class="viewing">正在查看</span>':''}</span></span><i data-lucide="chevron-right"></i></a>`;
    }).join('');
    icons();
  }
  async function loadHistory(reset=false) {
    if(historyLoading)return;
    if(!reset&&historyNext===null)return;
    historyLoading=true;
    $('history-retry').hidden=true;
    $('history-more').disabled=true;
    $('history-list').setAttribute('aria-busy','true');
    if(reset){historyItems=[];historyNext=null;renderHistory();$('history-more').hidden=true;}
    $('history-message').textContent=historyItems.length?'':'正在读取历史记录…';
    try {
      const offset=reset?0:historyNext;
      const response=await fetch(new URL(`api/history?limit=20&offset=${offset}`,base));
      const data=await response.json();
      if(!response.ok)throw new Error(data.detail||'暂时无法读取历史记录。');
      const known=new Set(historyItems.map(item=>item.id));
      historyItems.push(...data.items.filter(item=>!known.has(item.id)));
      latestId=data.current_id;historyNext=data.next_offset;
      $('history-summary').textContent=`${data.total} 个已完成批次 · 按保存时间排序`;
      $('history-message').textContent=data.unavailable_count?`${data.unavailable_count} 条记录暂时无法读取，其余记录仍可查看。`:data.total?'':'还没有历史记录。完成调色后，结果会自动保存在这里。';
      $('history-more').hidden=historyNext===null;
      renderHistory();
    } catch(error) {
      $('history-message').textContent=error.message;
      $('history-retry').hidden=false;
    } finally {
      historyLoading=false;$('history-more').disabled=false;
      $('history-list').setAttribute('aria-busy','false');
    }
  }
  function imageURL(photo, isOriginal) {return new URL(isOriginal ? photo.original_url : photo.result_url,base).href;}
  function strength(photo) {return `${Math.round(photo.strength*100)}%`;}
  function selectView(button, selected) {
    button.classList.toggle('active',selected);
    button.setAttribute('aria-pressed',String(selected));
  }
  function updateGlobalView() {
    selectView($('original-toggle'),originalPhotos.size===gallery.photos.length);
    selectView($('result-toggle'),originalPhotos.size===0);
  }
  function updatePhoto(index) {
    const photo=gallery.photos[index], original=originalPhotos.has(index);
    const card=$('preview-grid').querySelector(`[data-photo-card="${index}"]`);
    const img=card.querySelector('.photo-preview img');
    img.src=imageURL(photo,original);
    img.alt=`${photo.name} · ${original?'原图':'LUT 效果'}`;
    card.querySelector('.photo-badge').textContent=original?'原图':'LUT 效果';
    selectView(card.querySelector('[data-photo-view="original"]'),original);
    selectView(card.querySelector('[data-photo-view="result"]'),!original);
  }
  function setPhotoView(index, original) {
    if(original)originalPhotos.add(index);else originalPhotos.delete(index);
    updatePhoto(index);updateGlobalView();
    if($('photo-dialog').open && active===index)showLightbox();
  }
  function setAllViews(original) {
    gallery.photos.forEach((_,index)=>{
      if(original)originalPhotos.add(index);else originalPhotos.delete(index);
      updatePhoto(index);
    });
    updateGlobalView();
  }
  function showLightbox() {
    const photo = gallery.photos[active];
    const lightboxOriginal = originalPhotos.has(active);
    $('lightbox-image').src = imageURL(photo,lightboxOriginal);
    $('lightbox-image').alt = `${photo.name} · ${lightboxOriginal?'原图':'LUT 效果'}`;
    $('lightbox-title').textContent = photo.name;
    $('lightbox-lut').textContent = `${photo.lut_name} · ${strength(photo)}`;
    $('lightbox-count').textContent = `${String(active+1).padStart(2,'0')} / ${String(gallery.photos.length).padStart(2,'0')}`;
    $('lightbox-badge').textContent = lightboxOriginal?'原图':'LUT 效果';
    selectView($('lightbox-original'),lightboxOriginal);
    selectView($('lightbox-result'),!lightboxOriginal);
    $('previous-photo').disabled = active===0;
    $('next-photo').disabled = active===gallery.photos.length-1;
    $('previous-photo').hidden = $('next-photo').hidden = gallery.photos.length<2;
  }
  function render() {
    const photos = gallery.photos;
    $('gallery-summary').textContent = `${photos.length} 张照片 · 每张可独立对比，点击图片放大`;
    if(run)$('history-context-label').textContent=`历史批次 · ${formatDate(gallery.created_at)}`;
    $('gallery-status').textContent = '调色完成';
    $('empty-state').hidden = true;
    $('view-switch').hidden = false;
    $('preview-grid').hidden = false;
    $('preview-grid').classList.toggle('single',photos.length===1);
    $('preview-grid').innerHTML = photos.map((photo,index)=>{
      const original=originalPhotos.has(index);
      return `<article class="photo-card" data-photo-card="${index}"><button class="photo-preview" data-photo="${index}" aria-label="放大查看${escape(photo.name)}"><img src="${escape(imageURL(photo,original))}" alt="${escape(photo.name)} · ${original?'原图':'LUT 效果'}"><span class="photo-index">${String(index+1).padStart(2,'0')}</span><span class="photo-badge">${original?'原图':'LUT 效果'}</span><span class="expand-icon"><i data-lucide="maximize-2"></i></span></button><div class="photo-controls"><span>画面对比</span><div class="view-switch compact-switch" role="group" aria-label="${escape(photo.name)}的预览模式"><button data-photo-view="original" class="${original?'active':''}" aria-pressed="${original}">原图</button><button data-photo-view="result" class="${original?'':'active'}" aria-pressed="${!original}">效果图</button></div></div><div class="photo-caption"><div><h2>${escape(photo.name)}</h2><span class="photo-size">${photo.width} × ${photo.height}</span></div><div class="lut-caption"><span class="lut-mark"><i data-lucide="sparkles"></i></span><span>${escape(photo.lut_name)}</span><span class="strength">${strength(photo)}</span></div></div></article>`;
    }).join('');
    updateGlobalView();
    icons();
    $('manual-result').hidden=true;
    const previousPhoto=$('manual-photo').value;
    $('manual-photo').replaceChildren(...photos.map(p=>new Option(p.name,p.id)));
    if(photos.some(p=>p.id===previousPhoto))$('manual-photo').value=previousPhoto;
    loadManual();
  }
  function manualOptions() {
    const selected=$('manual-lut').value,query=$('manual-search').value.trim().toLocaleLowerCase();
    const items=manualItems.filter(p=>p.name.toLocaleLowerCase().includes(query));
    $('manual-lut').replaceChildren(...items.map(p=>new Option(`${p.name}${p.last_status==='failed'?' · 上次失败':p.tested_strengths.length?' · 已生成':''}`,p.id)));
    if(items.some(p=>p.id===selected))$('manual-lut').value=selected;
    if(!items.length)$('manual-lut').append(new Option('没有匹配的 LUT',''));
    manualSelection();
  }
  function manualSelection() {
    const select=$('manual-lut'),item=manualItems.find(p=>p.id===select.value);
    $('manual-prev').disabled=manualBusy||select.selectedIndex<=0;
    $('manual-next').disabled=manualBusy||!item||select.selectedIndex>=select.options.length-1;
    $('manual-apply').disabled=manualBusy||!item||!manualToken;
    $('manual-selected-note').textContent=!item?'可尝试其他名称':item.last_status==='failed'?'上次生成失败，可重试或更换 LUT':item.tested_strengths.length?`已生成强度：${item.tested_strengths.map(s=>Math.round(s*100)+'%').join('、')}`:'这张照片尚未试用此款';
  }
  async function loadManual(preserveStatus=false) {
    if(!gallery||manualBusy)return;
    const request=++manualRequest;
    $('manual-apply').disabled=true;$('manual-retry').hidden=true;
    manualToken='';
    const params=new URLSearchParams({source_run_id:gallery.id,photo_id:$('manual-photo').value});
    try {
      const response=await fetch(new URL(`api/manual/luts?${params}`,base));
      const data=await response.json();if(request!==manualRequest)return;
      if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'暂时无法读取 LUT 列表。');
      if(!data.enabled){$('manual-panel').hidden=true;return;}
      $('manual-panel').hidden=false;
      manualToken=data.token;manualItems=data.items;
      $('manual-progress').textContent=`当前照片已生成 ${data.successful_count} / ${data.count} 款`;
      manualOptions();
      if(preserveStatus||!$('manual-result').hidden)return;
      $('manual-status').dataset.state='';$('manual-status').textContent='选择 LUT 和强度后点击应用。原图与之前的效果都会保留。';
    }catch(error){
      if(request!==manualRequest)return;
      $('manual-status').dataset.state='error';$('manual-status').textContent=error.message;$('manual-retry').hidden=false;
    }
  }
  async function applyManual(event) {
    event.preventDefault();if(manualBusy||!manualToken||!$('manual-lut').value)return;
    const choice={source_run_id:gallery.id,photo_id:$('manual-photo').value,lut_id:$('manual-lut').value,strength:Number($('manual-strength').value)/100};
    const name=manualItems.find(p=>p.id===choice.lut_id).name;
    manualBusy=true;$('manual-fields').disabled=true;$('manual-status').dataset.state='busy';
    $('manual-status').textContent=`正在生成 ${name} · ${Math.round(choice.strength*100)}%…`;$('manual-apply').textContent='正在生成…';
    try{
      const response=await fetch(new URL('api/manual/apply',base),{method:'POST',headers:{'Content-Type':'application/json','X-LUT-Preview-Token':manualToken},body:JSON.stringify(choice)});
      const data=await response.json();
      if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'生成失败，请刷新页面后重试。');
      const photo=data.gallery.photos[0];
      $('manual-result-title').textContent=`${photo.name} · ${photo.lut_name} · ${strength(photo)}`;
      $('manual-before').src=$('manual-before-link').href=imageURL(photo,true);
      $('manual-after').src=$('manual-after-link').href=imageURL(photo,false);
      $('manual-history-link').href=new URL(`?run=${data.run_id}`,base).href;
      $('manual-result').hidden=false;$('manual-status').dataset.state='success';
      $('manual-status').textContent=data.cache_hit?'已载入相同设置的已保存结果，没有重复生成。':'已成功生成。可直接对比原图，或换下一款继续试用。';
    }catch(error){$('manual-status').dataset.state='error';$('manual-status').textContent=`本次未生成：${error.message}`;}
    finally{manualBusy=false;$('manual-fields').disabled=false;$('manual-apply').textContent='应用到这张照片';manualSelection();await loadManual(true);}
  }
  async function load() {
    if(polling || document.hidden || manualBusy) return;
    polling=true;
    try {
      const response=await fetch(new URL(run?`api/previews/${encodeURIComponent(run)}`:'api/preview',base));
      const data=await response.json();
      if(manualBusy)return;
      if(!response.ok)throw new Error(data.detail||'暂时无法读取预览。');
      $('connection-note').hidden=true;
      if(data.gallery && data.gallery.id!==gallery?.id) {
        $('photo-dialog').close();gallery=data.gallery;originalPhotos.clear();active=0;render();
      } else if (!data.gallery) {
        $('gallery-summary').textContent='照片完成调色后，将在这里呈现。';
        $('empty-title').textContent='等待调色结果';
        $('empty-description').textContent='在 Codex 中发送图片和风格要求，完成后即可查看预览。';
      }
    } catch(error) {
      if(gallery) {
        $('connection-note').textContent='连接暂时中断，正在展示已载入的结果。';$('connection-note').hidden=false;
      } else {
        $('empty-title').textContent='暂时无法载入预览';$('empty-description').textContent=error.message;
        $('gallery-summary').textContent='调色结果会在连接恢复后显示。';
      }
    } finally {polling=false;}
  }
  $('original-toggle').addEventListener('click',()=>setAllViews(true));
  $('result-toggle').addEventListener('click',()=>setAllViews(false));
  $('preview-grid').addEventListener('click',event=>{
    const view=event.target.closest('[data-photo-view]');
    if(view){
      setPhotoView(Number(view.closest('[data-photo-card]').dataset.photoCard),view.dataset.photoView==='original');
      return;
    }
    const button=event.target.closest('[data-photo]');if(!button)return;
    active=Number(button.dataset.photo);showLightbox();$('photo-dialog').showModal();
  });
  $('close-lightbox').addEventListener('click',()=>$('photo-dialog').close());
  $('lightbox-original').addEventListener('click',()=>setPhotoView(active,true));
  $('lightbox-result').addEventListener('click',()=>setPhotoView(active,false));
  $('previous-photo').addEventListener('click',()=>{if(active>0){active--;showLightbox();}});
  $('next-photo').addEventListener('click',()=>{if(active<gallery.photos.length-1){active++;showLightbox();}});
  $('photo-dialog').addEventListener('keydown',event=>{
    if(event.key==='ArrowLeft'&&active>0){active--;showLightbox();event.preventDefault();}
    if(event.key==='ArrowRight'&&active<gallery.photos.length-1){active++;showLightbox();event.preventDefault();}
  });
  $('photo-dialog').addEventListener('click',event=>{if(event.target===$('photo-dialog'))$('photo-dialog').close();});
  $('history-button').addEventListener('click',()=>{$('history-dialog').showModal();loadHistory(true);});
  $('close-history').addEventListener('click',()=>$('history-dialog').close());
  $('history-dialog').addEventListener('click',event=>{if(event.target===$('history-dialog'))$('history-dialog').close();});
  $('history-more').addEventListener('click',()=>loadHistory(false));
  $('history-retry').addEventListener('click',()=>loadHistory(historyItems.length===0));
  $('manual-form').addEventListener('submit',applyManual);
  $('manual-search').addEventListener('input',manualOptions);
  $('manual-lut').addEventListener('change',manualSelection);
  $('manual-photo').addEventListener('change',()=>{$('manual-result').hidden=true;loadManual();});
  $('manual-strength').addEventListener('input',()=>{$('manual-strength-value').textContent=$('manual-strength').value+'%';});
  $('manual-prev').addEventListener('click',()=>{const s=$('manual-lut');if(s.selectedIndex>0)s.selectedIndex--;manualSelection();});
  $('manual-next').addEventListener('click',()=>{const s=$('manual-lut');if(s.selectedIndex<s.options.length-1)s.selectedIndex++;manualSelection();});
  $('manual-retry').addEventListener('click',()=>loadManual());
  if(run){$('history-context').hidden=false;$('history-context-label').textContent='正在查看已保存的记录';}
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  window.addEventListener('dragover',event=>event.preventDefault());
  window.addEventListener('drop',event=>event.preventDefault());
  icons();load();
  // Current local gallery follows completed Codex tasks; a run URL stays pinned.
  setInterval(()=>{if(!run||!gallery)load();},5000);
})();
