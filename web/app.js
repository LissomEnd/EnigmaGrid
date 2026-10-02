const $=id=>document.getElementById(id);
const fmt=n=>new Intl.NumberFormat().format(Number(n)||0);
const esc=x=>String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const age=s=>{const n=Number(s)||0;if(n<60)return Math.round(n)+' s';if(n<3600)return Math.round(n/60)+' min';return Math.round(n/3600)+' h'};
function live(ok,text){$('liveText').textContent=text;$('liveDot').style.background=ok?'#62d99b':'#ff6b7a';$('liveDot').style.boxShadow='0 0 15px '+(ok?'#62d99b66':'#ff6b7a66')}
async function refresh(){
 try{
  const r=await fetch('/api/public/status',{cache:'no-store'});
  if(!r.ok)throw new Error('status '+r.status);
  const s=await r.json();live(true,'Coordinator online');
  $('pct').textContent=(Number(s.progress_pct)||0).toFixed(3)+'%';
  $('done').textContent=fmt(s.completed_units);$('online').textContent=fmt(s.online_devices);
  $('pending').textContent=fmt(s.pending_validations);$('cpuOnline').textContent=fmt(s.online_cpu_devices);
  $('gpuOnline').textContent=fmt(s.online_gpu_devices);$('fill').style.width=Math.min(100,Number(s.progress_pct)||0)+'%';
  $('progressText').textContent=fmt(s.completed_units)+' of '+fmt(s.total_units)+' unique work units verified';
  const leaders=s.leaderboard||[];
  $('leaders').innerHTML=leaders.length?leaders.map(x=>'<tr><td>'+esc(x.display_name)+'</td><td>'+fmt(x.units)+'</td><td>'+fmt(x.jobs)+'</td><td>'+age(x.compute_seconds)+'</td></tr>').join(''):'<tr><td colspan="4" class="muted">No verified contributions yet.</td></tr>';
  $('campaigns').innerHTML=(s.campaigns||[]).map(x=>'<div class="campaign"><div><b>'+esc(x.name)+'</b><div class="muted">'+esc(x.version)+'</div></div><div class="state">'+esc(x.status)+'</div></div>').join('');
 }catch(e){live(false,'Coordinator unavailable')}
}
function deviceHtml(d){
 const st=d.settings||{},caps=d.capabilities||[],gpu=caps.includes('cuda')||caps.includes('gpu');
 const state=d.quarantined?'<span class="warn">quarantined</span>':(d.enabled?'<span class="ok">enabled</span>':'<span class="bad">disabled</span>');
 return '<div class="device"><b>'+esc(d.label)+'</b> · '+state+' · trust '+Number(d.trust_score||0).toFixed(2)+
 '<p class="muted">'+caps.map(esc).join(', ')+' · valid '+fmt(d.valid_jobs)+' · invalid '+fmt(d.invalid_jobs)+'</p>'+
 '<label>CPU contribution: <b id="cv-'+d.id+'">'+Number(st.cpu_percent||0)+'%</b></label>'+
 '<input data-kind="cpu" data-device="'+d.id+'" type="range" min="0" max="100" step="5" value="'+Number(st.cpu_percent||0)+'" id="cpu-'+d.id+'">'+
 '<label>GPU contribution: <b id="gv-'+d.id+'">'+Number(st.gpu_percent||0)+'%</b></label>'+
 '<input data-kind="gpu" data-device="'+d.id+'" type="range" min="0" max="100" step="5" value="'+Number(st.gpu_percent||0)+'" id="gpu-'+d.id+'" '+(gpu?'':'disabled')+'>'+
 '<p><button data-action="save" data-device="'+d.id+'">Save limits</button></p></div>';
}
async function loadMe(){
 const token=$('dash').value.trim();if(!token)return;
 sessionStorage.setItem('enigmaDashboardToken',token);$('me').textContent='Loading...';
 try{
  const r=await fetch('/api/me',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dashboard_token:token})});
  if(!r.ok)throw new Error('invalid');
  const x=await r.json(),st=x.stats||{};
  $('me').classList.remove('empty');
  $('me').innerHTML='<p><b>'+esc(x.display_name)+'</b></p><p>'+fmt(st.units)+' verified units · '+fmt(x.pending_units)+' pending · '+fmt(st.jobs)+' jobs · '+age(st.compute_seconds)+' compute</p>'+(x.devices||[]).map(deviceHtml).join('');
 }catch(e){$('me').className='personal error';$('me').textContent='Dashboard token is invalid or the coordinator is unavailable.'}
}
async function saveDevice(id){
 const token=$('dash').value.trim(),cpu=Number($('cpu-'+id).value),gpuEl=$('gpu-'+id),gpu=gpuEl.disabled?0:Number(gpuEl.value);
 const body={dashboard_token:token,device_id:id,settings:{cpu_percent:cpu,gpu_percent:gpu,allow_cpu:cpu>0,allow_gpu:gpu>0}};
 const r=await fetch('/api/me/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(r.ok)await loadMe();else alert('Could not save device limits.');
}
$('loadBtn').addEventListener('click',loadMe);$('dash').addEventListener('keydown',e=>{if(e.key==='Enter')loadMe()});
$('me').addEventListener('input',e=>{const t=e.target;if(!(t instanceof HTMLInputElement)||!t.dataset.kind)return;$( (t.dataset.kind==='cpu'?'cv-':'gv-')+t.dataset.device).textContent=t.value+'%'});
$('me').addEventListener('click',e=>{const b=e.target.closest('button[data-action="save"]');if(b)saveDevice(b.dataset.device)});
$('dash').value=sessionStorage.getItem('enigmaDashboardToken')||'';if($('dash').value)loadMe();
refresh();setInterval(refresh,7000);
