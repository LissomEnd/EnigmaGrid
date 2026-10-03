// Exercise the actual dashboard's asynchronous account boundary without real credentials.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const elements=new Map(),pending=[];
let publicPayload={registration_open:true};
function element(id){
 if(!elements.has(id))elements.set(id,{value:'',textContent:'',innerHTML:'',disabled:false,hidden:false,className:'',events:{},
  addEventListener(name,fn){this.events[name]=fn;},querySelector(){return element('save-button');}});
 return elements.get(id);
}
const context=vm.createContext({document:{getElementById:element},Intl,Number,String,Error,AbortSignal,
 CSS:{escape:x=>x},HTMLInputElement:class {},sessionStorage:{removeItem(){throw Error('Storage blocked');}},
 setTimeout(){},fetch(url,options){
  if(url==='/api/public/status')return Promise.resolve({ok:true,json:async()=>publicPayload});
  return new Promise(resolve=>pending.push({url,options,resolve}));
 }});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8'),context);
const execute=code=>vm.runInContext(code,context);
const respond=(request,body,ok=true)=>request.resolve({ok,json:async()=>body});
const account={display_name:'Volunteer',stats:{},devices:[]};
async function load(token='TEST-TOKEN'){
 element('dash').value=token;const task=execute('loadMe()');respond(pending.shift(),account);await task;
}
(async()=>{
 publicPayload={registration_open:true,campaigns:[{status:'paused'}]};
 await execute('refresh()');assert.match(element('launchState').textContent,/New work is paused/);
 publicPayload={registration_open:true,campaigns:[{status:'running'}]};
 await execute('refresh()');assert.match(element('launchState').textContent,/registration is open/);
 await load();assert.equal(element('accountActions').hidden,false);
 const first=execute('loadMe()');const delayed=pending.shift();
 execute('forget()');respond(delayed,account);await first;
 assert.equal(element('me').textContent,'No private dashboard loaded.');
 assert.equal(element('accountActions').hidden,true);
 await load();element('dash').value='DIFFERENT';element('dash').events.input();
 assert.equal(element('accountActions').hidden,true);
 await execute("saveDevice('d1')");assert.equal(pending.length,0);
 await load();element('cpu-d1').value='25';element('gpu-d1').value='40';
 const save=execute("saveDevice('d1')");const saveRequest=pending.shift();
 assert.equal(element('save-button').disabled,true);
 assert.equal(element('cpu-d1').disabled,true);
 await execute("saveDevice('d1')");assert.equal(pending.length,0);
 respond(saveRequest,{});await save;
 assert.match(element('saved-d1').textContent,/Limits saved/);
 assert.equal(element('save-button').disabled,false);
 const delayedSave=execute("saveDevice('d1')");const request=pending.shift();
 execute('forget()');respond(request,{});await delayedSave;
 assert.equal(element('me').textContent,'No private dashboard loaded.');
 await load();element('deleteConfirm').value='DELETE';
 const deletion=element('deleteBtn').events.click();const deletionRequest=pending.shift();
 element('dash').value='NEW-ACCOUNT';element('dash').events.input();
 respond(deletionRequest,{});await deletion;
 assert.equal(element('dash').value,'NEW-ACCOUNT');
 assert.equal(element('me').textContent,'No private dashboard loaded.');
 const html=execute(`deviceHtml({id:'x" onfocus="alert(1)',label:'<img src=x onerror=alert(1)>',settings:{}})`);
 assert.ok(!html.includes('<img'));assert.ok(!html.includes('id="cpu-x" onfocus='));
 console.log('DASHBOARD_ACCOUNT_RACES_SAVE_FEEDBACK_AND_ESCAPING_OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
