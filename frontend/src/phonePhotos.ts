import {ref} from 'vue';
export type Api=(path:string,method?:string,body?:unknown)=>Promise<any>;
export type TransferStatus={id:string;target_id:string;label:string;paired:boolean;phone_online:boolean;accepting:boolean;expires_at:number;photos:{id:string;name:string}[]};
export type BookPhoto={name:string;url:string;remoteId?:string};
const storageKey='book-photo-desktop-session';
function saved(){try{return sessionStorage.getItem(storageKey)||'';}catch{return '';}}
function save(id:string){try{id?sessionStorage.setItem(storageKey,id):sessionStorage.removeItem(storageKey);}catch{}}
const session=ref<{id:string;qr?:string;link?:string}|null>(null);
let operations:Promise<unknown>=Promise.resolve();
function serial<T>(fn:()=>Promise<T>):Promise<T>{const result=operations.then(fn,fn);operations=result.catch(()=>{});return result;}
export function newPhotoId():string{
 // getRandomValues also works on a LAN HTTP address used for local testing.
 const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
 const h=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
 return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`;
}
export function phoneReceiver(api:Api,label:()=>string,onPhotos:(items:BookPhoto[],ids:Set<string>)=>void){
 const status=ref<TransferStatus|null>(null),error=ref(''),connecting=ref(false);
 let targetId=newPhotoId(),roomId='',dead=false,timer:ReturnType<typeof setTimeout>|undefined;
 let paused=false,polling:Promise<void>|null=null;
 const loaded=new Map<string,BookPhoto>();
 const root=()=>'/photo-transfer/sessions/'+roomId;
 function forget(){save('');session.value=null;status.value=null;roomId='';loaded.clear();}
 async function collect(data:TransferStatus,expected:string){
  if(dead||expected!==targetId)return;
  status.value=data;
  const ids=new Set(data.photos.map(p=>p.id));
  for(const id of loaded.keys())if(!ids.has(id))loaded.delete(id);
  for(const p of data.photos){
   if(loaded.has(p.id))continue;
   let value;try{value=await api(root()+'/photos/'+p.id);}catch(e){if((e as any)?.status===404)continue;throw e;}
   if(dead||expected!==targetId)return;
   if(value.target_id===expected)loaded.set(p.id,{name:p.name,url:value.url,remoteId:p.id});
  }
  if(!dead&&expected===targetId)onPhotos([...loaded.values()],ids);
 }
 async function update(){
  const expected=targetId;
  try{
   const data:TransferStatus=await api(root()+'/heartbeat','POST',{target_id:expected,label:label().slice(0,240)});
   if(dead||expected!==targetId)return;
   await collect(data,expected);error.value='';
  }catch(e){
   if(dead||expected!==targetId)return;
   error.value=e instanceof Error?e.message:String(e);
   if([401,403,404,409].includes((e as any)?.status)){status.value=null;roomId='';}
  }
 }
 async function poll(){
  if(dead||paused||!roomId||polling)return;
  polling=update();await polling;polling=null;
  if(!dead&&!paused&&roomId)timer=setTimeout(poll,2000);
 }
 async function activate(){
  if(dead||!session.value)return;
  paused=true;clearTimeout(timer);await polling;
  if(dead||!session.value)return;
  roomId=session.value.id;
  status.value=await api(root()+'/target','POST',{target_id:targetId,label:label().slice(0,240)});
  if(dead){await api(root()+'/gate','POST',{target_id:targetId,accepting:false}).catch(()=>{});return;}
  paused=false;void poll();
 }
 async function resume(){
  await serial(async()=>{
   if(dead)return;
   const id=session.value?.id||saved();if(!id)return;
   try{await api('/photo-transfer/sessions/'+id);if(dead)return;session.value??={id};await activate();}
   catch(e){if([401,403,404].includes((e as any)?.status))forget();else error.value=e instanceof Error?e.message:String(e);}
  });
 }
 async function connect(){
  connecting.value=true;error.value='';
  try{await serial(async()=>{
   if(dead)return;
   // A consumed/lost pairing link is never reconstructed from a stored secret.
   if(session.value){
    try{
     const existing=await api('/photo-transfer/sessions/'+session.value.id);
     if(existing.paired||session.value.qr){await activate();return;}
     await api('/photo-transfer/sessions/'+session.value.id,'DELETE');forget();
    }catch(e){if([401,403,404].includes((e as any)?.status))forget();else throw e;}
   }
   if(!session.value){const created=await api('/photo-transfer/sessions','POST',{origin:location.origin});session.value={id:created.id,qr:created.qr,link:created.link};save(created.id);}
   await activate();
  });}catch(e){error.value=e instanceof Error?e.message:String(e);}finally{connecting.value=false;}
 }
 async function disconnect(){
  await serial(async()=>{paused=true;clearTimeout(timer);await polling;const id=roomId||session.value?.id;if(id)await api('/photo-transfer/sessions/'+id,'DELETE');clearTimeout(timer);forget();});
 }
 async function gate(accepting:boolean){
  if(!roomId)return;
  paused=true;clearTimeout(timer);await polling;
  const data=await api(root()+'/gate','POST',{target_id:targetId,accepting});
  await collect(data,targetId);
  paused=!accepting;if(accepting&&!dead)void poll();
 }
 async function remove(id:string){if(roomId){await api(root()+'/photos/'+id,'DELETE');loaded.delete(id);}}
 async function restart(){
  await serial(async()=>{paused=true;clearTimeout(timer);await polling;targetId=newPhotoId();loaded.clear();if(roomId)await activate();});
 }
 function dispose(){dead=true;clearTimeout(timer);const id=roomId,target=targetId;loaded.clear();
  if(id)void serial(()=>api('/photo-transfer/sessions/'+id+'/gate','POST',{target_id:target,accepting:false}).catch(()=>{}));
 }
 return {status,error,connecting,session,resume,connect,disconnect,gate,remove,restart,dispose};
}
