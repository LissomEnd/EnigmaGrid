const $=id=>document.getElementById(id);
const fmt=n=>new Intl.NumberFormat().format(n||0);
const esc=x=>String(x??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
async function refresh(){
 const s=await fetch('/api/public/status',{cache:'no-store'}).then(r=>r.json());
 $('pct').textContent=(s.progress_pct||0).toFixed(4)+'%';
 $('done').textContent=fmt(s.completed_units);$('online').textContent=fmt(s.online_devices);
 $('pending').textContent=fmt(s.pending_validations);$('cpuOnline').textContent=fmt(s.online_cpu_devices);
 $('gpuOnline').textContent=fmt(s.online_gpu_devices);$('fill').style.width=Math.min(100,s.progress_pct||0)+'%';
 $('progressText').textContent=fmt(s.completed_units)+' of '+fmt(s.total_units)+' unique work units verified';
 $('leaders').innerHTML=(s.leaderboard||[]).map(x=>'<tr><td>'+esc(x.display_name)+'</td><td>'+fmt(x.units)+'</td><td>'+fmt(x.jobs)+'</td><td>'+fmt(Math.round(x.compute_seconds))+'</td></tr>').join('');
 $('campaigns').innerHTML=(s.campaigns||[]).map(x=>'<p><b>'+esc(x.name)+'</b> · '+esc(x.version)+' · '+esc(x.status)+'</p>').join('');
}
function deviceHtml(d){
 const st=d.settings||{},caps=d.capabilities||[],gpu=caps.includes('cuda')||caps.includes('gpu');
 const status=d.quarantined?'<span class="warn">quarantined</span>':(d.enabled?'<span class="ok">enabled</span>':'disabled');
 return '<div class="device"><b>'+esc(d.label)+'</b> · '+status+' · trust '+Number(d.trust_score||0).toFixed(2)+
 '<p class="muted">'+caps.map(esc).join(', ')+' · valid '+fmt(d.valid_jobs)+' · invalid '+fmt(d.invalid_jobs)+'</p>'+
 '<label>CPU contribution: <b id="cv-'+d.id+'">'+st.cpu_percent+'%</b></label>'+
 '<input data-kind="cpu" data-device="'+d.id+'" type="range" min="0" max="100" step="5" value="'+st.cpu_percent+'" id="cpu-'+d.id+'">'+
 '<label>GPU contribution: <b id="gv-'+d.id+'">'+st.gpu_percent+'%</b></label>'+
 '<input data-kind="gpu" data-device="'+d.id+'" type="range" min="0" max="100" step="5" value="'+st.gpu_percent+'" id="gpu-'+d.id+'" '+(gpu?'':'disabled')+'>'+
 '<p><button data-action="save" data-device="'+d.id+'">Save limits</button></p></div>';
}
async function loadMe(){
 const token=$('dash').value.trim();if(!token)return;sessionStorage.setItem('enigmaDashboardToken',token);
 const r=await fetch('/api/me',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dashboard_token:token})});
 if(!r.ok){$('me').textContent='Invalid dashboard token';return}
 const x=await r.json(),st=x.stats||{};
 $('me').innerHTML='<p><b>'+esc(x.display_name)+'</b></p><p>'+fmt(st.units)+' verified units · '+fmt(x.pending_units)+' pending units · '+fmt(st.jobs)+' verified jobs · '+fmt(Math.round(st.compute_seconds))+' compute seconds</p>'+
 (x.devices||[]).map(deviceHtml).join('');
}
async function saveDevice(id){
 const token=$('dash').value.trim(),cpu=Number($('cpu-'+id).value),gpuEl=$('gpu-'+id),gpu=gpuEl.disabled?0:Number(gpuEl.value);
 const body={dashboard_token:token,device_id:id,settings:{cpu_percent:cpu,gpu_percent:gpu,allow_cpu:cpu>0,allow_gpu:gpu>0}};
 const r=await fetch('/api/me/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(r.ok)await loadMe();else alert('Could not save device limits');
}
$('loadBtn').addEventListener('click',loadMe);
$('me').addEventListener('input',e=>{
 const t=e.target;if(!(t instanceof HTMLInputElement)||!t.dataset.kind)return;
 const prefix=t.dataset.kind==='cpu'?'cv-':'gv-';$(prefix+t.dataset.device).textContent=t.value+'%';
});
$('me').addEventListener('click',e=>{
 const b=e.target.closest('button[data-action="save"]');if(b)saveDevice(b.dataset.device);
});
$('dash').value=sessionStorage.getItem('enigmaDashboardToken')||'';if($('dash').value)loadMe();
refresh();setInterval(refresh,5000);
