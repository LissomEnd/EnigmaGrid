const $=id=>document.getElementById(id);
let privateRequest=0;
let loadedToken='';
const fmt=n=>new Intl.NumberFormat().format(Number(n)||0);
const esc=x=>String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const age=s=>{const n=Number(s)||0;if(n<60)return Math.round(n)+' s';if(n<3600)return Math.round(n/60)+' min';return Math.round(n/3600)+' h'};
function live(ok,text){$('liveText').textContent=text;$('liveDot').className='dot '+(ok?'online':'offline')}
async function refresh(){
 try{
  const r=await fetch('/api/public/status',{cache:'no-store',signal:AbortSignal.timeout(15000)});
  if(!r.ok)throw new Error('status '+r.status);
  const s=await r.json();live(true,'Coordinator online');
  $('downloadLink').hidden=!s.registration_open;
  const researchPaused=(s.campaigns||[]).some(c=>c.status==='paused') && !(s.campaigns||[]).some(c=>c.status==='running');
  $('launchState').textContent=researchPaused?'Research validation in progress. New work is paused while the next search method is tested. Existing results and credits are preserved; no reinstall is needed.':(s.registration_open?'Public registration is open.':'Public registration is closed while the release is being prepared or maintained.');
  $('pct').textContent=(Number(s.progress_pct)||0).toFixed(3)+'%';
  $('done').textContent=fmt(s.completed_units);$('online').textContent=fmt(s.online_devices);
  $('pending').textContent=fmt(s.pending_validations);$('cpuOnline').textContent=fmt(s.online_cpu_devices);
  $('gpuOnline').textContent=fmt(s.online_gpu_devices);$('searchProgress').value=Math.min(100,Number(s.progress_pct)||0);
  $('progressText').textContent=fmt(s.completed_units)+' of '+fmt(s.total_units)+' unique work units completed · '+fmt(s.verified_units??s.completed_units)+' independently verified · '+fmt(s.accepted_trusted_units)+' accepted with sampling';
  const leaders=s.leaderboard||[];
  $('leaders').innerHTML=leaders.length?leaders.map(x=>'<tr><td>'+esc(x.display_name)+'</td><td>'+fmt(x.units)+'</td><td>'+fmt(x.jobs)+'</td><td>'+age(x.compute_seconds)+'</td></tr>').join(''):'<tr><td colspan="4" class="muted">No credited contributions yet.</td></tr>';
  $('campaigns').innerHTML=(s.campaigns||[]).filter(x=>x.status!=='archived').map(x=>'<div class="campaign"><div><b>'+esc(x.name)+'</b><div class="muted">'+esc(x.version)+'</div></div><div class="state">'+esc(x.status)+'</div></div>').join('');
 }catch(e){live(false,'Connection lost · figures may be outdated');$('launchState').textContent='Connection unavailable. Registration status could not be confirmed.'}
}
function deviceHtml(d){
 const safeId=esc(d.id);
 const st=d.settings||{},caps=d.capabilities||[],gpu=caps.some(x=>['opencl','gpu','cuda'].includes(x));
 const state=d.quarantined?'<span class="warn">quarantined</span>':(d.enabled?'<span class="ok">enabled</span>':'<span class="bad">disabled</span>');
 return '<div class="device"><b>'+esc(d.label)+'</b> · '+state+' · trust '+Number(d.trust_score||0).toFixed(2)+
 '<p class="muted">'+caps.map(esc).join(', ')+' · valid '+fmt(d.valid_jobs)+' · invalid '+fmt(d.invalid_jobs)+'</p>'+
 '<label for="cpu-'+safeId+'">CPU contribution: <b id="cv-'+safeId+'">'+Number(st.cpu_percent||0)+'%</b></label>'+
 '<input data-kind="cpu" data-device="'+safeId+'" type="range" min="0" max="100" step="5" value="'+Number(st.cpu_percent||0)+'" id="cpu-'+safeId+'">'+
 '<label for="gpu-'+safeId+'">GPU contribution: <b id="gv-'+safeId+'">'+Number(st.gpu_percent||0)+'%</b></label>'+
 '<input data-kind="gpu" data-device="'+safeId+'" type="range" min="0" max="100" step="5" value="'+Number(st.gpu_percent||0)+'" id="gpu-'+safeId+'" '+(gpu?'':'disabled')+'>'+
 '<p class="small muted">CPU sets a thread budget; GPU sets a work/rest budget. Changes apply to the next job. Setting both to zero stops new computation; use Pause in the app to pause the current job.</p>'+
 (gpu?'':'<p class="small muted">No qualified GPU was reported. CPU contribution is available.</p>')+
 '<p><button data-action="save" data-device="'+safeId+'">Save limits</button></p><p id="saved-'+safeId+'" role="status" class="small"></p></div>';
}
async function loadMe(){
 const token=$('dash').value.trim();if(!token){$('me').textContent='Paste your private dashboard token first.';return;}
 const request=++privateRequest;
 loadedToken='';$('accountActions').hidden=true;$('accountMessage').textContent='';
 $('me').textContent='Loading...';$('loadBtn').disabled=true;
 try{
  const r=await fetch('/api/me',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dashboard_token:token}),signal:AbortSignal.timeout(15000)});
  if(!r.ok)throw new Error('invalid');
  const x=await r.json(),st=x.stats||{};
  if(request!==privateRequest)return;
  loadedToken=token;$('me').className='personal';$('accountActions').hidden=false;
  $('me').innerHTML='<p><b>'+esc(x.display_name)+'</b></p><p>'+fmt(st.credited_units??st.units)+' credited units ('+fmt(st.verified_units??st.units)+' independently verified, '+fmt(st.accepted_trusted_units)+' accepted with sampling) · '+fmt(x.pending_units)+' pending · '+fmt(st.credited_jobs??st.jobs)+' jobs · '+age(st.compute_seconds)+' compute</p>'+(x.devices||[]).map(deviceHtml).join('');
 }catch(e){if(request===privateRequest){$('me').className='personal error';$('me').textContent='Dashboard token is invalid or the coordinator is unavailable.';$('accountActions').hidden=true;}}
 finally{if(request===privateRequest)$('loadBtn').disabled=false;}
}
async function saveDevice(id){
 const token=$('dash').value.trim();if(!loadedToken||token!==loadedToken)return;
 const request=privateRequest,cpuEl=$('cpu-'+id),cpu=Number(cpuEl.value),gpuEl=$('gpu-'+id),gpuDisabled=gpuEl.disabled,gpu=gpuDisabled?0:Number(gpuEl.value);
 const button=$('me').querySelector('button[data-device="'+CSS.escape(id)+'"]');
 if(button.disabled)return;button.disabled=true;cpuEl.disabled=true;gpuEl.disabled=true;$('saved-'+id).textContent='Saving limits…';
 const body={dashboard_token:token,device_id:id,settings:{cpu_percent:cpu,gpu_percent:gpu,allow_cpu:cpu>0,allow_gpu:gpu>0}};
 try{
  const r=await fetch('/api/me/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
  if(!r.ok)throw new Error('save failed');
  if(request===privateRequest)$('saved-'+id).textContent='Limits saved. They apply to the next job.';
 }catch(e){if(request===privateRequest)$('saved-'+id).textContent='Save was not confirmed. Check your connection and retry.';}
 finally{if(request===privateRequest){button.disabled=false;cpuEl.disabled=false;gpuEl.disabled=gpuDisabled;}}
}
$('loadBtn').addEventListener('click',loadMe);$('dash').addEventListener('keydown',e=>{if(e.key==='Enter')loadMe()});
$('me').addEventListener('input',e=>{const t=e.target;if(!(t instanceof HTMLInputElement)||!t.dataset.kind)return;$( (t.dataset.kind==='cpu'?'cv-':'gv-')+t.dataset.device).textContent=t.value+'%'});
$('me').addEventListener('click',e=>{const b=e.target.closest('button[data-action="save"]');if(b)saveDevice(b.dataset.device)});
function clearLegacyToken(){try{sessionStorage.removeItem('enigmaDashboardToken');}catch{}}
function forget(clearToken=true){ ++privateRequest;loadedToken='';$('loadBtn').disabled=false;if(clearToken)$('dash').value='';$('me').textContent='No private dashboard loaded.';$('me').className='personal empty';$('accountActions').hidden=true;$('deleteConfirm').value='';$('accountMessage').textContent='';clearLegacyToken(); }
$('dash').addEventListener('input',()=>forget(false));
$('forgetBtn').addEventListener('click',forget);
$('deleteBtn').addEventListener('click',async()=>{
 const request=privateRequest,token=$('dash').value.trim();if(!loadedToken||token!==loadedToken)return;
 if($('deleteConfirm').value!=='DELETE'){ $('accountMessage').textContent='Type DELETE exactly to confirm.';return; }
 $('deleteBtn').disabled=true;
 try{
  const r=await fetch('/api/me/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dashboard_token:token,confirm:'DELETE'}),signal:AbortSignal.timeout(15000)});
  if(!r.ok)throw new Error('deletion failed');if(request===privateRequest){forget();$('me').textContent='Account deleted. You can now uninstall the app.';}
 }catch(e){if(request===privateRequest)$('accountMessage').textContent='Deletion was not confirmed. Check the connection and try again.';}
 finally{$('deleteBtn').disabled=false;}
});
clearLegacyToken();
async function poll(){await refresh();setTimeout(poll,15000);}poll();
