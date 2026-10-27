<script setup lang="ts">
import {computed, nextTick, onMounted, ref, watch} from 'vue';
import {authStorage} from './authStorage';
import type {DT} from './catalog';
import {fieldName, subName} from './ru';

type FieldOption = {key:string, tag:string, code:string|null, label:string, parent_label:string, local:boolean, configured:boolean};
type Issue = {field:string, kind:'missing'|'vocabulary', values:string[], allow_edit:boolean};
type Row = {id:number, type_id:number, title:string, author:string, udc:string, issues:Issue[]};
type Report = {items:Row[], total:number, scanned:number, offset:number, limit:number, counts:{missing:number,vocabulary:number}};
const props=defineProps<{api:(path:string,method?:string,body?:unknown)=>Promise<any>,types:DT[]}>();
const emit=defineEmits<{record:[id:number]}>();
const fields=ref<FieldOption[]>([]), selected=ref<string[]>([]), checks=ref<string[]>(['missing','vocabulary']);
const typeId=ref(0), query=ref(''), fieldQuery=ref(''), offset=ref(0), visibleCount=ref(100);
const busy=ref(false), loadingOptions=ref(false), ready=ref(false), error=ref(''), data=ref<Report|null>(null), applied=ref('');
const storageKey='catalog-attention-filters';
const settings=()=>({fields:selected.value,checks:checks.value,type_id:typeId.value,q:query.value.trim()});
const stale=computed(()=>!!data.value&&applied.value!==JSON.stringify(settings()));
const byKey=computed(()=>new Map(fields.value.map(f=>[f.key,f])));
function label(f:FieldOption){return f.local?f.label:f.code?subName(f.tag,f.code,f.label):fieldName(f.tag,f.label);}
function fieldLabel(key:string){const f=byKey.value.get(key);return f?label(f):key;}
const filtered=computed(()=>{
 const q=fieldQuery.value.trim().toLocaleLowerCase();
 return fields.value.filter(f=>!q||`${f.key} ${label(f)} ${f.parent_label}`.toLocaleLowerCase().includes(q))
  .sort((a,b)=>Number(b.configured)-Number(a.configured)||a.key.localeCompare(b.key));
});
watch(fieldQuery,()=>visibleCount.value=100);
function remember(){try{authStorage.setItem(storageKey,JSON.stringify({...settings(),offset:offset.value}));}catch{/* Filters may be used even when browser storage is unavailable. */}}
function toggle(key:string){selected.value=selected.value.includes(key)?selected.value.filter(k=>k!==key):[...selected.value,key];}
let optionsRequest=0;
async function loadOptions(){
 const request=++optionsRequest;loadingOptions.value=true;error.value='';
 try{
  const result=await props.api('/catalog-attention/options'+(typeId.value?'?type_id='+typeId.value:''));
  if(request!==optionsRequest)return;
  fields.value=result.fields;const keys=new Set(fields.value.map(f=>f.key));selected.value=selected.value.filter(k=>keys.has(k));
 }catch(e){if(request===optionsRequest)error.value=e instanceof Error?e.message:String(e);}
 finally{if(request===optionsRequest)loadingOptions.value=false;}
}
watch(typeId,async()=>{if(!ready.value)return;data.value=null;offset.value=0;await loadOptions();remember();});
async function load(start=0){
 if(busy.value||loadingOptions.value||!selected.value.length||!checks.value.length)return;
 busy.value=true;error.value='';offset.value=start;remember();
 const snapshot=JSON.stringify(settings());const q=new URLSearchParams({q:query.value.trim(),offset:String(start),limit:'50'});
 selected.value.forEach(f=>q.append('fields',f));checks.value.forEach(c=>q.append('checks',c));
 if(typeId.value)q.set('type_id',String(typeId.value));
 try{
  let result:Report=await props.api('/catalog-attention?'+q);
  // After corrections the last page may have disappeared; return to a valid page.
  if(result.total>0&&start>=result.total){offset.value=Math.floor((result.total-1)/50)*50;q.set('offset',String(offset.value));result=await props.api('/catalog-attention?'+q);}
  else if(!result.total)offset.value=0;
  data.value=result;applied.value=snapshot;remember();
 }catch(e){data.value=null;error.value=e instanceof Error?e.message:String(e);}
 finally{busy.value=false;}
}
async function changePage(delta:number){await load(Math.max(0,offset.value+delta));await nextTick();document.getElementById('attention-results')?.scrollIntoView({block:'start'});}
function open(id:number){remember();emit('record',id);}
onMounted(async()=>{
 try{
  const saved=JSON.parse(authStorage.getItem(storageKey)||'null');
  if(saved){
   selected.value=Array.isArray(saved.fields)?saved.fields.filter((k:unknown)=>typeof k==='string').slice(0,100):[];
   checks.value=Array.isArray(saved.checks)?saved.checks.filter((k:unknown)=>k==='missing'||k==='vocabulary'):['missing','vocabulary'];
   typeId.value=props.types.some(t=>t.id===saved.type_id)?saved.type_id:0;
   query.value=typeof saved.q==='string'?saved.q.slice(0,200):'';
   offset.value=Number.isInteger(saved.offset)&&saved.offset>=0?saved.offset:0;
  }
 }catch{/* Ignore an outdated or invalid saved filter. */}
 await loadOptions();ready.value=true;
 if(selected.value.length&&checks.value.length&&!error.value)await load(offset.value);
});
</script>

<template>
<section class="attention-page" :aria-busy="busy||loadingOptions">
 <div class="page-heading"><div><div class="eyebrow">КАТАЛОГИЗАЦИЯ И КЛАССИФИКАЦИЯ</div><h1>Требует внимания</h1><p>Найдите записи с незаполненными полями и значениями, которые нужно проверить.</p></div></div>
 <form class="card attention-filters" @submit.prevent="load(0)">
  <fieldset :disabled="busy" class="plain-fieldset">
   <div class="attention-scope"><label>Тип документа<select v-model="typeId"><option :value="0">Все типы документов</option><option v-for="t in types" :key="t.id" :value="t.id">{{t.name}}</option></select></label><label>Поиск по данным книги<input v-model="query" maxlength="200" placeholder="Заглавие, автор или другое значение"></label></div>
   <h2>Поля для проверки</h2><p class="muted">Выберите поля или отдельные строки. Например, «952$j · Специальность». Запись попадёт в результат, если найдена хотя бы одна из выбранных проблем.</p>
   <label class="attention-field-search">Найти поле<input v-model="fieldQuery" placeholder="Название или код поля: специальность, ISBN, 952…" type="search"></label>
   <div class="attention-field-picker" role="group" aria-label="Поля каталога для проверки">
    <label v-for="f in filtered.slice(0,visibleCount)" :key="f.key" class="attention-field-choice"><input type="checkbox" :checked="selected.includes(f.key)" :disabled="loadingOptions||(!selected.includes(f.key)&&selected.length>=100)" @change="toggle(f.key)"><span><span class="attention-code">{{f.key}}</span> {{label(f)}}<small v-if="!f.code&&Number(f.tag)>=10">Поле целиком · любое заполненное подполе</small></span></label>
    <p v-if="!filtered.length">{{loadingOptions?'Загрузка полей…':'Таких полей не найдено.'}}</p>
    <button v-if="filtered.length>visibleCount" type="button" @click="visibleCount+=100">Показать ещё поля ({{filtered.length-visibleCount}})</button>
   </div>
   <div v-if="selected.length" class="attention-selected" aria-label="Выбранные поля"><button v-for="key in selected" :key="key" type="button" :aria-label="'Убрать поле '+key+' '+fieldLabel(key)" @click="toggle(key)">{{key}} · {{fieldLabel(key)}} <span aria-hidden="true">×</span></button><button class="attention-clear" type="button" @click="selected=[]">Снять выбор</button></div>
   <p class="muted">Выбрано полей: {{selected.length}} из 100 доступных для одной проверки.</p>
   <fieldset class="attention-checks"><legend>Что искать</legend><label class="check-label"><input type="checkbox" v-model="checks" value="missing">Не заполнено</label><label class="check-label"><input type="checkbox" v-model="checks" value="vocabulary">Значение вне справочника</label></fieldset>
   <details class="attention-rules"><summary>Как проверяются значения</summary><ul><li>Отсутствующее, пустое поле и значение из одних пробелов считаются незаполненными. Если поле повторяется, достаточно одного непустого значения.</li><li>Значения сверяются со справочником своего типа документа. Проверяются все непустые значения, в том числе импортированные.</li><li>При включённом автодобавлении значения вне списка не считаются проблемой. Если разрешено только редактирование, они показываются с пояснением.</li><li>Поля без справочника и имена операторов не проверяются на совпадение со списком. Проверка не определяет смысловую правильность описания книги.</li></ul></details>
   <div class="attention-submit"><button class="primary" :disabled="busy||loadingOptions||!selected.length||!checks.length">{{busy?'Проверяю каталог…':'Проверить записи'}}</button><span v-if="!selected.length" class="muted">Выберите хотя бы одно поле.</span><span v-else-if="!checks.length" class="muted">Выберите, что искать.</span></div>
  </fieldset>
 </form>
 <p v-if="error" class="inline-error" role="alert">{{error}}</p>
 <p v-if="stale" class="pending-note" role="status">Условия изменены. Нажмите «Проверить записи», чтобы обновить результат.</p>
 <template v-if="data">
  <div class="attention-stats" aria-live="polite"><div class="card"><span>Проверено записей</span><strong>{{data.scanned.toLocaleString('ru-RU')}}</strong></div><div class="card"><span>Требуют внимания</span><strong>{{data.total.toLocaleString('ru-RU')}}</strong></div><div class="card"><span>С незаполненными полями</span><strong>{{data.counts.missing.toLocaleString('ru-RU')}}</strong></div><div class="card"><span>Со значениями вне списка</span><strong>{{data.counts.vocabulary.toLocaleString('ru-RU')}}</strong></div></div>
  <section id="attention-results" class="card attention-results" aria-label="Результаты проверки">
   <div class="attention-result-heading"><h2>Записи для проверки</h2><p class="muted">Одна запись показывается один раз, со всеми найденными проблемами. После исправления вернитесь к этому списку — он пересчитается.</p></div>
   <div class="table-footer" role="navigation" aria-label="Страницы проблемных записей сверху"><span>{{data.total?'Записи '+(offset+1)+'–'+Math.min(offset+50,data.total)+' из '+data.total:'Записей нет'}}</span><div><button type="button" :disabled="busy||stale||offset===0" @click="changePage(-50)">← Назад</button><button type="button" :disabled="busy||stale||offset+50>=data.total" @click="changePage(50)">Далее →</button></div></div>
   <div v-if="data.items.length" class="table-wrap attention-result-table"><table><thead><tr><th>Документ</th><th>Тип / УДК</th><th>Что требует внимания</th><th><span class="sr-only">Действие</span></th></tr></thead><tbody><tr v-for="r in data.items" :key="r.id"><td><button type="button" class="record-title" @click="open(r.id)">{{r.title}}</button><small>{{r.author||'Автор не указан'}} · № {{r.id}}</small></td><td>{{types.find(t=>t.id===r.type_id)?.name}}<small>УДК: {{r.udc||'—'}}</small></td><td><ul class="attention-issues"><li v-for="(issue,i) in r.issues" :key="i"><span :class="['attention-badge',issue.kind]">{{issue.kind==='missing'?'Не заполнено':'Вне справочника'}}</span> <b>{{issue.field}} · {{fieldLabel(issue.field)}}</b><ul v-if="issue.values.length"><li v-for="v in issue.values" :key="v">«{{v}}»</li></ul><small v-if="issue.kind==='vocabulary'&&issue.allow_edit">Ручное редактирование разрешено. Проверьте, подходит ли это значение.</small></li></ul></td><td><button type="button" @click="open(r.id)">Открыть запись</button></td></tr></tbody></table></div>
   <div v-else class="empty"><h3>По выбранным условиям проблем не найдено</h3><p>Можно выбрать другие поля или изменить тип проверки.</p></div>
   <div class="table-footer attention-bottom" role="navigation" aria-label="Страницы проблемных записей снизу"><span>{{data.total?'Записи '+(offset+1)+'–'+Math.min(offset+50,data.total)+' из '+data.total:'Записей нет'}}</span><div><button type="button" :disabled="busy||stale||offset===0" @click="changePage(-50)">← Назад</button><button type="button" :disabled="busy||stale||offset+50>=data.total" @click="changePage(50)">Далее →</button></div></div>
  </section>
 </template>
</section>
</template>

<style scoped>
.attention-filters{padding:24px;margin-bottom:24px}.attention-scope{display:grid;grid-template-columns:minmax(180px,1fr) 2fr;gap:20px}.attention-scope label,.attention-field-search{display:flex;flex-direction:column;gap:8px}.attention-filters h2{margin-top:24px;font-size:20px}.attention-field-search{margin:16px 0}.attention-field-picker{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px 16px;max-height:280px;overflow:auto;padding:12px;border:1px solid #dce3ed;border-radius:14px;background:#f8fafc}.attention-field-choice{display:flex;align-items:flex-start;gap:10px;padding:8px;border-radius:8px;cursor:pointer}.attention-field-choice:hover{background:#edf4f5}.attention-field-choice input{margin-top:4px;flex:none}.attention-field-choice small{display:block;color:#64748b}.attention-code{font-family:monospace;color:#0f766e}.attention-selected{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.attention-selected button{font-size:13px;padding:7px 10px;background:#eff8f7;color:#115e59;border-color:#b8dcd7}.attention-selected .attention-clear{background:white;color:#475569}.attention-checks{display:flex;flex-wrap:wrap;gap:12px 28px;border:0;padding:12px 0}.attention-checks legend{font-weight:700}.attention-rules{margin:12px 0 20px;color:#64748b}.attention-rules li{margin:6px 0}.attention-submit{display:flex;align-items:center;flex-wrap:wrap;gap:16px}.attention-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:24px}.attention-stats .card{padding:22px}.attention-stats span{color:#64748b}.attention-stats strong{display:block;font-size:30px;color:#062747;margin-top:12px}.attention-results{display:flex;flex-direction:column;overflow:hidden;scroll-margin-top:24px}.attention-result-heading{padding:20px 24px 0}.attention-result-heading h2{font-size:20px}.attention-result-table td{vertical-align:top;overflow-wrap:anywhere}.attention-result-table td:first-child{min-width:210px}.attention-result-table small{display:block;margin-top:6px;color:#64748b}.attention-issues{list-style:none;margin:0;padding:0;min-width:260px}.attention-issues>li+li{margin-top:14px}.attention-issues ul{padding-left:20px;margin:6px 0}.attention-badge{display:inline-block;padding:3px 8px;border-radius:8px;font-size:12px;font-weight:600;margin-bottom:5px}.attention-badge.missing{background:#fff3dd;color:#80591a}.attention-badge.vocabulary{background:#fce9e7;color:#a33629}.attention-result-table{order:1}.attention-results .empty{order:1}.attention-bottom{order:2}@media(max-width:1000px){.attention-stats{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:650px){.attention-scope,.attention-field-picker,.attention-stats{grid-template-columns:1fr}.attention-filters{padding:16px}}
</style>
