async function validateCode(input){
  const code=input.value.trim().toUpperCase();
  input.value=code;
  const small=input.parentElement.querySelector('small');
  if(!code){small.textContent='';small.className='';return false}
  const form=input.closest('form');
  const all=[...form.querySelectorAll('.student-code')].filter(i=>i!==input&&i.value.trim().toUpperCase()===code);
  if(all.length){small.textContent='❌ Código repetido en esta reserva';small.className='err';return false}
  try{
    const r=await fetch('/api/student?code='+encodeURIComponent(code));
    const data=await r.json();
    if(data.ok){small.textContent='✓ '+data.name;small.className='ok';return true}
    small.textContent='❌ Código no registrado';small.className='err';return false
  }catch(e){small.textContent='No se pudo validar';small.className='err';return false}
}

function prepareCancel(form){
  const reason=window.prompt('Motivo de cancelación (opcional):','');
  if(reason===null)return false;
  if(!window.confirm('¿Confirmas cancelar esta reserva? El registro se conservará en el historial.'))return false;
  form.querySelector('input[name="reason"]').value=reason.trim();
  return true;
}

function showVivaLoader(link){
  const overlay=document.getElementById('viva-loader');
  if(!overlay){window.location.href=link.href;return}
  const icon=link.dataset.icon||'✦';
  const activity=link.dataset.activity||'';
  const label=link.dataset.label||'';
  const iconNode=document.getElementById('loader-icon');
  const copy=document.getElementById('loader-copy');
  iconNode.textContent=icon;
  const loaderClass={
    futbol:'football-loader',
    voley:'volleyball-loader',
    imac:'tech-loader',
    windows:'tech-loader',
    diseno:'design-loader'
  }[activity]||'generic-loader';
  iconNode.className='loader-activity-icon '+loaderClass;
  copy.textContent=label?'Preparando '+label+'...':'Preparando tu experiencia...';
  overlay.classList.add('show');
  overlay.setAttribute('aria-hidden','false');
  window.setTimeout(()=>{window.location.href=link.href},720);
}

function wireExperienceLinks(){
  document.querySelectorAll('.activity-card,.activity-tab').forEach(link=>{
    link.addEventListener('click',e=>{
      if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;
      e.preventDefault();
      showVivaLoader(link);
    });
  });
}

function wireHeroParallax(){
  const hero=document.querySelector('.viva-home-hero');
  if(!hero||!window.matchMedia('(pointer:fine)').matches)return;
  const left=hero.querySelector('.hero-side-left');
  const right=hero.querySelector('.hero-side-right');
  if(!left||!right)return;
  hero.addEventListener('pointermove',e=>{
    const r=hero.getBoundingClientRect();
    const x=((e.clientX-r.left)/r.width-.5)*12;
    const y=((e.clientY-r.top)/r.height-.5)*8;
    left.style.transform=`translate3d(${x}px,${y}px,0)`;
    right.style.transform=`translate3d(${-x}px,${-y}px,0)`;
  });
  hero.addEventListener('pointerleave',()=>{
    left.style.transform='translate3d(0,0,0)';
    right.style.transform='translate3d(0,0,0)';
  });
}

function roundedRect(ctx,x,y,w,h,r){
  const rr=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+rr,y);ctx.arcTo(x+w,y,x+w,y+h,rr);ctx.arcTo(x+w,y+h,x,y+h,rr);ctx.arcTo(x,y+h,x,y,rr);ctx.arcTo(x,y,x+w,y,rr);ctx.closePath()
}

function drawBar(canvasId,obj){
  const c=document.getElementById(canvasId);if(!c||!obj)return;
  const ctx=c.getContext('2d'),labels=Object.keys(obj),vals=Object.values(obj).map(Number);
  const css=getComputedStyle(document.documentElement),orange=css.getPropertyValue('--orange').trim()||'#f97316',muted=css.getPropertyValue('--muted').trim()||'#6b7280',line=css.getPropertyValue('--line').trim()||'#ece7e2';
  const dpr=window.devicePixelRatio||1,W=Math.max(320,c.clientWidth||320),H=220;c.width=W*dpr;c.height=H*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
  const pad={l:36,r:12,t:18,b:52},plotW=W-pad.l-pad.r,plotH=H-pad.t-pad.b,max=Math.max(1,...vals);
  ctx.strokeStyle=line;ctx.lineWidth=1;ctx.font='11px Segoe UI';ctx.fillStyle=muted;ctx.textAlign='right';
  for(let i=0;i<=4;i++){const y=pad.t+plotH-(plotH*i/4);ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(W-pad.r,y);ctx.stroke();ctx.fillText(String(Math.round(max*i/4)),pad.l-7,y+4)}
  const barW=plotW/Math.max(1,labels.length),actual=Math.max(10,Math.min(44,barW*.58));ctx.textAlign='center';
  labels.forEach((lab,i)=>{const val=vals[i],h=(val/max)*(plotH-5),x=pad.l+i*barW+(barW-actual)/2,y=pad.t+plotH-h;ctx.fillStyle=orange;roundedRect(ctx,x,y,actual,h||2,7);ctx.fill();ctx.fillStyle='#4b5563';ctx.font='10px Segoe UI';const short=lab.length>12?lab.slice(0,11)+'…':lab;ctx.fillText(short,x+actual/2,H-20);if(val>0){ctx.fillStyle='#8a4514';ctx.font='bold 11px Segoe UI';ctx.fillText(String(val),x+actual/2,Math.max(12,y-5))}})
}

function drawCharts(){
  if(!window.DASH_DATA)return;
  drawBar('chartDays',window.DASH_DATA.days);
  drawBar('chartHours',window.DASH_DATA.hours);
  drawBar('chartActivities',window.DASH_DATA.activities);
}

function debounce(fn,ms){let t;return()=>{clearTimeout(t);t=setTimeout(fn,ms)}}

function refreshAdminSlots(){
  const activity=document.getElementById('admin-activity');
  const slot=document.getElementById('admin-slot');
  if(!activity||!slot||!window.ACTIVITY_META)return;
  const meta=window.ACTIVITY_META[activity.value];
  if(!meta)return;
  const current=slot.value;
  slot.innerHTML='';
  meta.slots.forEach(s=>{const o=document.createElement('option');o.value=s;o.textContent=s;slot.appendChild(o)});
  if(meta.slots.includes(current))slot.value=current;
}

function wireReservationValidation(){
  document.querySelectorAll('.student-code').forEach(i=>{
    i.addEventListener('blur',()=>validateCode(i));
    i.addEventListener('input',()=>{clearTimeout(i._t);i._t=setTimeout(()=>validateCode(i),350)});
  });
  document.querySelectorAll('form.reserve-card').forEach(form=>{
    form.addEventListener('submit',async e=>{
      const required=[...form.querySelectorAll('.student-code')].filter(i=>i.hasAttribute('required'));
      if(!required.length)return;
      e.preventDefault();
      const results=await Promise.all(required.map(validateCode));
      if(results.some(v=>!v)){required.find((_,idx)=>!results[idx])?.focus();return}
      form.submit();
    });
  });
}

document.addEventListener('DOMContentLoaded',()=>{
  wireExperienceLinks();
  wireHeroParallax();
  wireReservationValidation();
  const adminActivity=document.getElementById('admin-activity');
  if(adminActivity){adminActivity.addEventListener('change',refreshAdminSlots);refreshAdminSlots()}
  drawCharts();
  window.addEventListener('resize',debounce(drawCharts,180));
});
