import {inject,nextTick,onBeforeUnmount,onMounted,watch,type Ref} from 'vue';
import {createRouter,createWebHashHistory,routerKey,type LocationQuery,type LocationQueryRaw,type Router} from 'vue-router';

export const sections:Record<string,{title:string;permissions:string[]}>= {
 catalog:{title:'Каталог',permissions:['catalog.view']},attention:{title:'Требует внимания',permissions:['catalog.view']},
 types:{title:'Настройка ввода',permissions:['settings.edit']},reference:{title:'Справочник полей',permissions:['catalog.view']},
 acquisitions:{title:'Поступления',permissions:['acquisitions.view']},ksu:{title:'КСУ',permissions:['ksu.view']},
 withdrawals:{title:'Списание',permissions:['withdrawals.view']},readers:{title:'Читатели',permissions:['readers.registry.view']},
 circulation:{title:'Книговыдача',permissions:['circulation.issue','circulation.return','circulation.view_any_history','circulation.view_own_history','loans.view_own','reservations.manage','fines.manage','incidents.manage','circulation.settings']},
 visits:{title:'Посещения',permissions:['visits.record','visits.view']},events:{title:'Мероприятия',permissions:['events.view']},
 statistics:{title:'Работа сотрудников',permissions:['statistics.view']},'book-fund':{title:'Книжный фонд',permissions:['statistics.view']},
 'circulation-statistics':{title:'Статистика книговыдачи',permissions:['statistics.view']},attendance:{title:'Посещаемость',permissions:['visits.view']},
 site:{title:'Сайт библиотеки',permissions:['site.manage']},users:{title:'Пользователи и права',permissions:[]}
};
export function allowedSection(name:string,can:(p:string)=>boolean,isAdmin:boolean){return name==='users'?isAdmin:!!sections[name]?.permissions.some(can);}
export function firstSection(can:(p:string)=>boolean,isAdmin:boolean){return Object.keys(sections).find(name=>allowedSection(name,can,isAdmin))||'unavailable';}
export function routeText(query:LocationQuery,key:string){return typeof query[key]==='string'?query[key] as string:'';}
export function routeId(query:LocationQuery,key:string){const s=routeText(query,key);return /^[1-9]\d*$/.test(s)&&Number.isSafeInteger(Number(s))?Number(s):0;}
export function routeTab(query:LocationQuery,choices:string[],fallback:string){const s=routeText(query,'tab');return choices.includes(s)?s:fallback;}

const pending=new Set<Promise<unknown>>();
export function renderTask<T>(task:Promise<T>):Promise<T>{pending.add(task);void task.then(()=>pending.delete(task),()=>pending.delete(task));return task;}
export function makeRouter(){
 // Preserve existing staff bookmarks such as #readers and #circulation.
 if(/^#[a-z-]+$/.test(location.hash))history.replaceState(history.state,'',location.pathname+location.search+'#/'+location.hash.slice(1));
 const router:Router=createRouter({history:createWebHashHistory(),routes:[
  {path:'/',redirect:'/catalog'},
  ...Object.keys(sections).map(name=>({path:'/'+name,name,component:{render:()=>null}})),
  {path:'/unavailable',name:'unavailable',component:{render:()=>null}},
  {path:'/:pathMatch(.*)*',name:'not-found',component:{render:()=>null}}
 ],async scrollBehavior(to,from,saved){
  await nextTick();while(pending.size){await Promise.allSettled([...pending]);await nextTick();}
  if(to.fullPath!==router.currentRoute.value.fullPath)return false;
  return saved||{top:0,left:0};
 }});
 return router;
}

// Only view preferences and filters, only in memory, cleared at sign-out/user switch.
// No reader cards, MARC drafts, credentials or API responses are stored here.
const memory=new Map<string,Record<string,unknown>>();let memoryEpoch=0;
export function clearNavigationMemory(){memory.clear();memoryEpoch++;}
export function usePageMemory(key:string,refs:Record<string,Ref<any>>){
 const epoch=memoryEpoch,saved=memory.get(key);
 if(saved)for(const [name,r] of Object.entries(refs))if(name in saved)r.value=JSON.parse(JSON.stringify(saved[name]));
 watch(()=>Object.fromEntries(Object.entries(refs).map(([k,v])=>[k,v.value])),value=>{
  if(epoch===memoryEpoch)memory.set(key,JSON.parse(JSON.stringify(value)));
 },{deep:true,flush:'sync'});
}

/** URL-first navigation. Restoration is serial: a late request cannot replace a newer route. */
export function usePageRoute(section:string,apply:(query:LocationQuery)=>Promise<void>|void,initialize:()=>Promise<void>|void=()=>{}){
 const router=inject(routerKey,null);let mounted=false,disposed=false,chain=Promise.resolve();
 function refresh(){
  if(!mounted||disposed||router&&router.currentRoute.value.name!==section)return Promise.resolve();
  const path=router?.currentRoute.value.fullPath;
  chain=chain.then(async()=>{
   if(disposed||router&&(router.currentRoute.value.name!==section||router.currentRoute.value.fullPath!==path))return;
   await apply(router?.currentRoute.value.query||{});
  });
  // Errors belong in the page's existing error UI; keep the queue usable afterwards.
  const task=renderTask(chain);chain=chain.catch(()=>{});return task;
 }
 const stop=router?watch(()=>router.currentRoute.value.fullPath,()=>{if(mounted)void refresh().catch(console.error);}):()=>{};
 onMounted(()=>{void renderTask(Promise.resolve().then(initialize).then(()=>{mounted=true;return refresh();})).catch(console.error);});
 onBeforeUnmount(()=>{disposed=true;stop();});
 function go(query:LocationQueryRaw={},replace=false){
  if(disposed)return true;
  if(!router)return false;
  void router[replace?'replace':'push']({name:section,query});return true;
 }
 return {go,refresh,router};
}

export function useNavigationGuard(section:string,dirty:()=>boolean,busy:()=>boolean=()=>false,sameDocument?:(to:LocationQuery,from:LocationQuery)=>boolean){
 const router=inject(routerKey,null);
 const remove=router?.beforeEach((to,from)=>{
  if(from.name!==section)return;
  if(to.name===section&&sameDocument?.(to.query,from.query))return;
  if(busy()&&dirty())return false;
  if(dirty()&&!window.confirm('Есть несохранённые изменения. Перейти без сохранения?'))return false;
 });
 const unload=(event:BeforeUnloadEvent)=>{if(router?.currentRoute.value.name===section&&dirty()){event.preventDefault();event.returnValue='';}};
 onMounted(()=>window.addEventListener('beforeunload',unload));
 onBeforeUnmount(()=>{remove?.();window.removeEventListener('beforeunload',unload);});
}
