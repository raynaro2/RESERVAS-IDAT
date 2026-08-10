function maxForSport(){const s=document.getElementById('sport');return s&&s.value==='voley'?12:8}
function minForSport(){const s=document.getElementById('sport');return s&&s.value==='voley'?8:5}
function refreshFields(){const max=maxForSport(),min=minForSport();document.querySelectorAll('.code-row').forEach((r,i)=>{r.style.display=i<max?'block':'none';r.querySelector('label').textContent='Código '+(i+1)+(i<min?' *':'')})}
async function validateCode(input){
  const code=input.value.trim().toUpperCase();input.value=code;
  const small=input.parentElement.querySelector('small');
  if(!code){small.textContent='';small.className='';return}
  const all=[...document.querySelectorAll('.student-code')].filter(i=>i!==input&&i.value.trim().toUpperCase()===code&&i.closest('.code-row').style.display!=='none');
  if(all.length){small.textContent='❌ Código repetido en esta reserva';small.className='err';return}
  try{
    const r=await fetch('/api/student?code='+encodeURIComponent(code));const data=await r.json();
    if(data.ok){small.textContent='✓ '+data.name;small.className='ok'}else{small.textContent='❌ Código no registrado';small.className='err'}
  }catch(e){small.textContent='No se pudo validar';small.className='err'}
}
function prepareCancel(form){
  const reason=window.prompt('Motivo de cancelación (opcional):','');
  if(reason===null)return false;
  if(!window.confirm('¿Confirmas cancelar esta reserva? El registro se conservará en el historial.'))return false;
  form.querySelector('input[name="reason"]').value=reason.trim();return true;
}
function roundedRect(ctx,x,y,w,h,r){const rr=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+rr,y);ctx.arcTo(x+w,y,x+w,y+h,rr);ctx.arcTo(x+w,y+h,x,y+h,rr);ctx.arcTo(x,y+h,x,y,rr);ctx.arcTo(x,y,x+w,y,rr);ctx.closePath()}
function drawBar(canvasId,obj){
  const c=document.getElementById(canvasId);if(!c||!obj)return;
  const ctx=c.getContext('2d'),labels=Object.keys(obj),vals=Object.values(obj).map(Number);
  const css=getComputedStyle(document.documentElement),orange=css.getPropertyValue('--orange').trim()||'#f97316',muted=css.getPropertyValue('--muted').trim()||'#6b7280',line=css.getPropertyValue('--line').trim()||'#ece7e2';
  const dpr=window.devicePixelRatio||1,W=Math.max(320,c.clientWidth||320),H=220;c.width=W*dpr;c.height=H*dpr;ctx.scale(dpr,dpr);ctx.clearRect(0,0,W,H);
  const pad={l:34,r:12,t:18,b:42},plotW=W-pad.l-pad.r,plotH=H-pad.t-pad.b,max=Math.max(1,...vals);
  ctx.strokeStyle=line;ctx.lineWidth=1;ctx.font='11px Segoe UI';ctx.fillStyle=muted;ctx.textAlign='right';
  for(let i=0;i<=4;i++){const y=pad.t+plotH-(plotH*i/4);ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(W-pad.r,y);ctx.stroke();ctx.fillText(String(Math.round(max*i/4)),pad.l-7,y+4)}
  const barW=plotW/Math.max(1,labels.length),actual=Math.max(10,barW*.58);ctx.textAlign='center';
  labels.forEach((lab,i)=>{const val=vals[i],h=(val/max)*(plotH-5),x=pad.l+i*barW+(barW-actual)/2,y=pad.t+plotH-h;ctx.fillStyle=orange;roundedRect(ctx,x,y,actual,h||2,6);ctx.fill();ctx.fillStyle='#4b5563';ctx.font='10px Segoe UI';ctx.fillText(lab,x+actual/2,H-18);if(val>0){ctx.fillStyle='#8a4514';ctx.font='bold 11px Segoe UI';ctx.fillText(String(val),x+actual/2,Math.max(12,y-5))}})
}
function drawCharts(){if(!window.DASH_DATA)return;drawBar('chartDays',window.DASH_DATA.days);drawBar('chartHours',window.DASH_DATA.hours);drawBar('chartSports',window.DASH_DATA.sports)}
function debounce(fn,ms){let t;return()=>{clearTimeout(t);t=setTimeout(fn,ms)}}
document.addEventListener('DOMContentLoaded',()=>{
  const sport=document.getElementById('sport');if(sport){sport.addEventListener('change',refreshFields);refreshFields()}
  document.querySelectorAll('.student-code').forEach(i=>{i.addEventListener('blur',()=>validateCode(i));i.addEventListener('input',()=>{clearTimeout(i._t);i._t=setTimeout(()=>validateCode(i),350)})});
  drawCharts();window.addEventListener('resize',debounce(drawCharts,180));
});
