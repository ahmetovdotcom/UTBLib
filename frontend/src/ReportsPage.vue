<script setup lang="ts">
import {computed, onBeforeUnmount, ref, watch} from 'vue';
import KsuTableView from './KsuTableView.vue';
import {fieldName,subName} from './ru';
import {usePageMemory, usePageRoute} from './navigation';

type FieldSpec={key:string;label:string;type:string;scope:string;operators:string[]};
type Column={key:string;label:string};
type Filter={key:string;operator:string;value:string;end:string};
type Definition={source:string;layout:string;columns:Column[];filters:Filter[];group_by:string;sort:string;descending:boolean;title:string};
type Saved={id:number;name:string;version:number;definition:Definition};
type Result={columns:Column[];rows:Record<string,string|number|null>[];total:number;totals:{titles:number;quantity:number;unpriced:number;amounts:Record<string,string>};generated_at:string};
const props=defineProps<{api:(path:string,method?:string,body?:unknown)=>Promise<any>;csrf:string}>();
const emit=defineEmits<{record:[id:number]}>();
const exampleKeys=['number','inventory','author','title','subtitle','language','place','publisher','year','udc','sigla','price','quantity','amount'];
const initial=():Definition=>({source:'copies',layout:'titles',columns:exampleKeys.map(key=>({key,label:''})),filters:[],group_by:'primary_specialty',sort:'title',descending:false,title:'Отчёт по библиотечному фонду'});
const definition=ref<Definition>(initial()), selected=ref(0), templateName=ref(''), search=ref(''), page=ref(1), hadPreview=ref(false);
usePageMemory('reports',{definition,selected,templateName,page,hadPreview});
const fields=ref<FieldSpec[]>([]),sources=ref<{key:string;label:string}[]>([]),groups=ref<string[]>([]),templates=ref<Saved[]>([]);
const result=ref<Result|null>(null),busy=ref(false),loading=ref(true),error=ref(''),notice=ref(''),snapshot=ref('');
let alive=true,sequence=0;onBeforeUnmount(()=>{alive=false;sequence++;});
const byKey=computed(()=>Object.fromEntries(fields.value.map(f=>[f.key,f])));
const selectedTemplate=computed(()=>templates.value.find(t=>t.id===selected.value));
const summaryKeys=computed(()=>[definition.value.group_by,'number','quantity','titles','amount','unpriced']);
const permittedFields=computed(()=>fields.value.filter(f=>definition.value.layout!=='summary'||summaryKeys.value.includes(f.key)));
const availableFields=computed(()=>permittedFields.value.filter(f=>!definition.value.columns.some(c=>c.key===f.key)&&(!search.value||`${f.label} ${f.key}`.toLocaleLowerCase().includes(search.value.toLocaleLowerCase()))).slice(0,80));
const filterFields=computed(()=>fields.value.filter(f=>f.scope!=='result'&&(!f.key.startsWith('marc:')||definition.value.columns.some(c=>c.key===f.key))));
const stale=computed(()=>!!result.value&&snapshot.value!==JSON.stringify(definition.value));
const templateChanged=computed(()=>!!selectedTemplate.value&&(JSON.stringify(selectedTemplate.value.definition)!==JSON.stringify(definition.value)||selectedTemplate.value.name!==templateName.value));
const ops:Record<string,string>={contains:'Содержит',equals:'Равно',starts_with:'Начинается с',empty:'Не заполнено',not_empty:'Заполнено',gte:'Не меньше / не раньше',lte:'Не больше / не позже',between:'В диапазоне'};
function label(key:string){return byKey.value[key]?.label||key;}
function fail(e:unknown){error.value=e instanceof Error?e.message:'Не удалось выполнить действие.';}
function addColumn(key:string){if(definition.value.columns.length<40)definition.value.columns.push({key,label:key.startsWith('marc:')?label(key):''});}
function move(index:number,offset:number){const columns=definition.value.columns;[columns[index],columns[index+offset]]=[columns[index+offset],columns[index]];}
function layoutChanged(){
 if(definition.value.layout==='summary'){
  definition.value.columns=[definition.value.group_by,'titles','quantity','amount','unpriced'].map(key=>({key,label:''}));definition.value.sort=definition.value.group_by;
 }else {definition.value.columns=exampleKeys.map(key=>({key,label:''}));definition.value.sort='title';}
}
function groupChanged(){if(definition.value.layout==='summary')layoutChanged();}
function filterChanged(f:Filter){f.operator=byKey.value[f.key]?.operators[0]||'contains';f.value='';f.end='';}
function addFilter(){definition.value.filters.push({key:'title',operator:'contains',value:'',end:''});}
async function preview(next=1){
 if(busy.value)return;
 busy.value=true;error.value='';notice.value='';const seq=++sequence;
 const request=JSON.parse(JSON.stringify(definition.value));
 try{const data=await props.api('/reports/preview','POST',{definition:request,page:next,page_size:50});if(alive&&seq===sequence){result.value=data;hadPreview.value=true;page.value=next;snapshot.value=JSON.stringify(request);}}
 catch(e){fail(e);}finally{if(alive)busy.value=false;}
}
async function loadTemplates(){templates.value=await props.api('/reports/templates');}
async function saveTemplate(copy=false){
 if(!templateName.value.trim()){error.value='Укажите название шаблона.';return;}
 busy.value=true;error.value='';notice.value='';
 try{
  const current=copy?undefined:selectedTemplate.value;
  const saved=await props.api('/reports/templates'+(current?'/'+current.id:''),current?'PUT':'POST',{name:templateName.value.trim(),definition:definition.value,version:current?.version??null});
  await loadTemplates();selected.value=saved.id;notice.value='Шаблон сохранён. Он доступен в вашей учётной записи.';
 }catch(e){fail(e);}finally{busy.value=false;}
}
async function deleteTemplate(){
 const current=selectedTemplate.value;if(!current||!window.confirm(`Удалить шаблон «${current.name}»? Данные библиотеки сохранятся.`))return;
 busy.value=true;error.value='';
 try{await props.api(`/reports/templates/${current.id}?version=${current.version}`,'DELETE');selected.value=0;await loadTemplates();notice.value='Шаблон удалён.';}catch(e){fail(e);}finally{busy.value=false;}
}
function chooseTemplate(){
 const current=selectedTemplate.value;if(!current)return;
 definition.value=JSON.parse(JSON.stringify(current.definition));templateName.value=current.name;result.value=null;hadPreview.value=false;page.value=1;error.value='';notice.value='';
}
function reset(){selected.value=0;templateName.value='';definition.value=initial();result.value=null;hadPreview.value=false;error.value='';notice.value='';}
async function exportExcel(){
 busy.value=true;error.value='';notice.value='';
 try{
  const response=await fetch('/api/reports/export',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':props.csrf},body:JSON.stringify(definition.value)});
  if(!response.ok){const data=await response.json();throw Error(typeof data.detail==='string'?data.detail:'Проверьте настройки отчёта.');}
  const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download='Отчёт библиотеки.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  notice.value='В Excel выгружены все строки по текущим настройкам. Итоги и условия отбора — на втором листе.';
 }catch(e){fail(e);}finally{busy.value=false;}
}
function columnWidth(key:string){return ({number:65,title:360,subtitle:260,author:220,inventory:200,primary_specialty:300,specialties:320,quantity:130,titles:130,unpriced:150,price:170,amount:180} as Record<string,number>)[key]||180;}
const money=(value:string)=>Number(value).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2});
function format(value:string|number|null,key:string){if(value===null||value==='')return '—';if((key==='price'||key==='amount')&&/^\d+(\.\d+)?$/.test(String(value)))return money(String(value));return String(value);}
watch(()=>definition.value.columns.map(c=>c.key),keys=>{if(!keys.includes(definition.value.sort))definition.value.sort=keys.find(k=>k!=='number')||'';});
usePageRoute('reports',()=>{},async()=>{
 try{const [options,saved]=await Promise.all([props.api('/reports/fields'),props.api('/reports/templates')]);if(!alive)return;fields.value=options.fields.map((f:FieldSpec)=>{if(!f.key.startsWith('marc:'))return f;const [tag,code]=f.key.slice(5).split('$');return {...f,label:`${tag}$${code} · ${fieldName(tag)} · ${subName(tag,code,f.label.split(' · ').slice(1).join(' · '))}`};});sources.value=options.sources;groups.value=options.groups;templates.value=saved;if(hadPreview.value)await preview(page.value);}
 catch(e){fail(e);}finally{loading.value=false;}
});
</script>

<template>
<section class="reports-page">
 <header class="report-heading"><div><p class="eyebrow">КОНСТРУКТОР ОТЧЁТОВ</p><h1>Отчёт по вашим условиям</h1><p>Выберите данные, условия отбора и столбцы. Сохраните шаблон, чтобы использовать его снова.</p></div><button type="button" @click="reset" :disabled="busy||loading">Новый отчёт</button></header>
 <p v-if="error" role="alert" class="report-error">{{error}}</p><p v-if="notice" role="status" class="report-notice">{{notice}}</p>
 <p v-if="loading" role="status">Загружаем настройки…</p>
 <template v-else>
 <fieldset class="report-settings" :disabled="busy">
  <section class="report-card templates"><div><h2>Мои шаблоны</h2><p>Сохраняются настройки, а данные каждый раз берутся из текущей базы.</p></div>
   <label>Открыть шаблон<select v-model="selected" @change="chooseTemplate"><option :value="0">Новый / несохранённый</option><option v-for="t in templates" :key="t.id" :value="t.id">{{t.name}}</option></select></label>
   <label>Название шаблона<input v-model="templateName" maxlength="120" placeholder="Например: книги на казахском языке"></label>
   <div class="report-actions"><button @click="saveTemplate(false)">{{selectedTemplate?'Сохранить изменения':'Сохранить шаблон'}}</button><button v-if="selectedTemplate" @click="saveTemplate(true)">Сохранить как новый</button><button v-if="selectedTemplate" @click="deleteTemplate">Удалить шаблон</button></div>
   <small v-if="templateChanged">В шаблоне есть несохранённые изменения.</small>
  </section>
  <section class="report-card"><h2>1. Данные и вид таблицы</h2><div class="report-controls">
   <label>Название отчёта<input v-model="definition.title" maxlength="160"></label>
   <label>Источник<select v-model="definition.source"><option v-for="source in sources" :value="source.key" :key="source.key">{{source.label}}</option></select></label>
   <label>Одна строка — это<select v-model="definition.layout" @change="layoutChanged"><option value="titles">Наименование книги</option><option value="copies">Экземпляр</option><option value="summary">Группа (сводная таблица)</option></select></label>
   <label v-if="definition.layout==='summary'">Группировать по<select v-model="definition.group_by" @change="groupChanged"><option v-for="key in groups" :key="key" :value="key">{{label(key)}}</option></select></label>
  </div><p class="report-hint">{{definition.source==='receipts'?'Поступления по КСУ включают списанные экземпляры, но не отменённые. Год КСУ и дата регистрации — отдельные поля.':'В количестве и стоимости учитываются действующие экземпляры, в том числе выданные читателям.'}} {{definition.source==='catalog'?'Записи без экземпляров также попадут в отчёт, если нет условий по экземплярам.':''}}</p>
  </section>
  <section class="report-card"><div class="report-section-title"><h2>2. Условия отбора <span>{{definition.filters.length}}</span></h2><button @click="addFilter" :disabled="definition.filters.length>=20">+ Добавить условие</button></div>
   <p v-if="!definition.filters.length">Без условий — все данные выбранного источника.</p><p v-else class="report-hint">Должны выполняться все условия. Условия по экземплярам проверяются для одного и того же экземпляра.</p>
   <div v-for="(f,index) in definition.filters" :key="index" class="report-filter">
    <label>Поле<select v-model="f.key" @change="filterChanged(f)"><option v-for="field in filterFields" :key="field.key" :value="field.key">{{field.label}}</option></select></label>
    <label>Условие<select v-model="f.operator"><option v-for="op in byKey[f.key]?.operators||[]" :key="op" :value="op">{{ops[op]}}</option></select></label>
    <label v-if="!['empty','not_empty'].includes(f.operator)">Значение<select v-if="byKey[f.key]?.type==='boolean'" v-model="f.value"><option value="">Выберите</option><option value="true">Да</option><option value="false">Нет</option></select><input v-else v-model="f.value" :type="byKey[f.key]?.type==='date'?'date':'text'" maxlength="500" :placeholder="byKey[f.key]?.type==='money'?'Например: 1500':'Введите значение'"></label>
    <label v-if="f.operator==='between'">До<input v-model="f.end" :type="byKey[f.key]?.type==='date'?'date':'text'" maxlength="500"></label>
    <button @click="definition.filters.splice(index,1)" :aria-label="`Удалить условие ${index+1}`">Удалить</button>
   </div>
  </section>
  <section class="report-card"><h2>3. Столбцы и порядок</h2><div class="report-columns">
   <div class="available-fields"><label>Найти поле<input v-model="search" placeholder="Название поля или код MARC, например 245"></label><p class="report-hint">Нажмите на поле, чтобы добавить столбец. Для отбора по дополнительному полю MARC сначала добавьте его сюда.</p><div class="field-list"><button v-for="f in availableFields" :key="f.key" @click="addColumn(f.key)" :disabled="definition.columns.length>=40">+ {{f.label}}</button><p v-if="!availableFields.length">Подходящих полей нет.</p></div></div>
   <div><p class="report-hint">Выбрано {{definition.columns.length}} из 40. Названия заголовков можно менять.</p><ol class="selected-fields"><li v-for="(column,index) in definition.columns" :key="column.key"><label><span>{{label(column.key)}}</span><input v-model="column.label" :placeholder="label(column.key)" maxlength="160" :aria-label="`Заголовок: ${label(column.key)}`"></label><div><button @click="move(index,-1)" :disabled="index===0" :aria-label="`Выше: ${label(column.key)}`">↑</button><button @click="move(index,1)" :disabled="index===definition.columns.length-1" :aria-label="`Ниже: ${label(column.key)}`">↓</button><button @click="definition.columns.splice(index,1)" :disabled="definition.columns.length===1" :aria-label="`Убрать: ${label(column.key)}`">×</button></div></li></ol></div>
  </div><div class="report-controls sort-controls"><label>Сортировать по<select v-model="definition.sort"><option value="">Без сортировки</option><option v-for="c in definition.columns" :key="c.key" :value="c.key">{{c.label||label(c.key)}}</option></select></label><label>Порядок<select v-model="definition.descending"><option :value="false">По возрастанию</option><option :value="true">По убыванию</option></select></label></div>
  </section>
 </fieldset>
 <div class="report-run"><button class="primary" @click="preview(1)" :disabled="busy">{{busy?'Подождите…':'Сформировать отчёт'}}</button><button @click="exportExcel" :disabled="busy||!result||stale">Скачать Excel · все строки</button><span v-if="stale" role="status">Настройки изменились. Сформируйте отчёт заново.</span></div>
 <template v-if="result">
  <section class="report-totals" aria-label="Итоги всей выборки"><div><strong>{{result.totals.titles.toLocaleString('ru-RU')}}</strong><span>наименований</span></div><div><strong>{{result.totals.quantity.toLocaleString('ru-RU')}}</strong><span>экземпляров</span></div><div v-for="(amount,currency) in result.totals.amounts" :key="currency"><strong>{{money(amount)}} {{currency}}</strong><span>сумма известных цен</span></div><div v-if="result.totals.unpriced"><strong>{{result.totals.unpriced}}</strong><span>экземпляров без цены · сумма неполная</span></div></section>
  <p class="report-hint">Итоги по всей выборке. Данные на {{new Date(result.generated_at).toLocaleString('ru-RU')}}. При выгрузке Excel данные обновляются. {{definition.layout==='summary'?'Наименования могут встречаться в нескольких группах; общий итог считает каждое один раз.':''}}</p>
  <KsuTableView :title="definition.title" :frozen-columns="1"><table class="ksu-grid report-table" :style="{width:result.columns.reduce((total,c)=>total+columnWidth(c.key),0)+'px'}"><thead><tr><th v-for="c in result.columns" :key="c.key" :style="{width:columnWidth(c.key)+'px',minWidth:columnWidth(c.key)+'px',maxWidth:columnWidth(c.key)+'px'}" scope="col">{{c.label}}</th></tr></thead><tbody><tr v-for="(row,index) in result.rows" :key="index"><td v-for="c in result.columns" :key="c.key"><button v-if="c.key==='title'&&row._record_id" class="record-link" @click="emit('record',Number(row._record_id))">{{format(row[c.key],c.key)}}</button><span v-else>{{format(row[c.key],c.key)}}</span></td></tr><tr v-if="!result.rows.length"><td :colspan="result.columns.length">По этим условиям ничего не найдено. Измените отбор и сформируйте отчёт снова.</td></tr></tbody></table></KsuTableView>
  <div class="report-pagination"><span>Строк: {{result.total}} · страница {{page}} из {{Math.max(1,Math.ceil(result.total/50))}}</span><button @click="preview(page-1)" :disabled="busy||stale||page<=1">Назад</button><button @click="preview(page+1)" :disabled="busy||stale||page*50>=result.total">Далее</button></div>
 </template>
 <section v-else class="report-empty"><h2>Здесь появится ваш отчёт</h2><p>В начальную таблицу включены описание книг, инвентарные номера, количество и стоимость. Настройте её и нажмите «Сформировать отчёт».</p></section>
 </template>
</section>
</template>

<style scoped>
.reports-page{padding:28px;max-width:1600px;margin:auto;color:#183747}.report-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:24px}.report-heading h1{font-size:28px;margin:6px 0 10px}.report-heading p,.report-card p{line-height:1.5;margin:6px 0 12px}.eyebrow{font-size:11px;letter-spacing:.15em;color:#087e88;font-weight:750}.report-settings{border:0;padding:0;margin:0;min-width:0}.report-card{background:#fff;border:1px solid #d7e2e6;border-radius:14px;padding:22px;margin-bottom:18px;min-width:0}.report-card h2{font-size:18px;margin:0 0 16px}.report-card h2 span{color:#70828b;font-size:14px}.report-controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px}label{display:flex;flex-direction:column;gap:7px;font-size:13px;font-weight:650;min-width:0}input,select{font:inherit;font-weight:400;width:100%;box-sizing:border-box;min-width:0;border:1px solid #becfd6;border-radius:7px;padding:10px;background:#fff;color:#183747}button{border:1px solid #b9cdd3;border-radius:7px;background:white;color:#163b4a;padding:9px 14px;cursor:pointer;font:inherit;font-size:13px}button:hover:not(:disabled){background:#eaf5f5;border-color:#12818a}button:disabled{opacity:.5;cursor:not-allowed}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #49bbc4;outline-offset:2px}.primary{background:#087e88;color:white;border-color:#087e88;font-weight:700}.primary:hover:not(:disabled){background:#07636b;color:white}.report-hint{color:#58717c;font-size:13px;line-height:1.5}.templates{display:grid;grid-template-columns:1fr 1fr;gap:14px}.templates>div:first-child,.templates>.report-actions{grid-column:1/-1}.templates h2{margin-bottom:4px}.report-actions,.report-run,.report-pagination{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.report-section-title{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}.report-section-title h2{margin:0}.report-filter{display:flex;align-items:flex-end;gap:10px;margin:12px 0;flex-wrap:wrap}.report-filter label{flex:1;min-width:150px}.report-filter label:first-child{flex:2}.report-columns{display:grid;grid-template-columns:minmax(230px,1fr) minmax(300px,1.4fr);gap:26px}.field-list{display:flex;flex-direction:column;gap:7px;max-height:500px;overflow:auto;padding:4px}.field-list button{text-align:left;overflow-wrap:anywhere}.selected-fields{margin:0;padding:0;list-style:none;max-height:590px;overflow:auto}.selected-fields li{display:flex;gap:10px;align-items:center;border-bottom:1px solid #e5ecef;padding:10px 4px}.selected-fields label{flex:1}.selected-fields label span{font-size:11px;color:#5c7480;font-weight:500}.selected-fields li>div{display:flex;gap:3px}.selected-fields button{padding:7px 9px}.sort-controls{margin-top:22px;max-width:700px}.report-run{position:sticky;bottom:0;z-index:4;background:#f1f7f8f5;padding:16px;border:1px solid #cadde1;border-radius:10px;margin:18px 0}.report-totals{display:flex;gap:12px;flex-wrap:wrap;margin:24px 0 10px}.report-totals>div{background:white;border:1px solid #d5e2e5;padding:16px 22px;border-radius:10px;display:flex;flex-direction:column;gap:6px}.report-totals strong{font-size:23px}.report-totals span{font-size:12px;color:#59717a}.report-table{font-size:13px;table-layout:fixed}.reports-page .report-table :is(th,td){padding:12px;vertical-align:top}.report-table td{min-width:0;max-width:380px;white-space:pre-wrap;overflow-wrap:anywhere}.record-link{border:0;background:transparent;color:#006c7b;text-align:left;text-decoration:underline;padding:0}.report-pagination{justify-content:flex-end;margin:16px 0}.report-pagination>span{margin-right:auto;font-size:13px}.report-empty{text-align:center;padding:40px;border:1px dashed #bccfd6;border-radius:14px;color:#5b7580}.report-error,.report-notice{padding:14px 18px;border-radius:9px;overflow-wrap:anywhere}.report-error{background:#fff0ec;color:#9c3025}.report-notice{background:#e7f5ef;color:#185e46}@media(max-width:800px){.reports-page{padding:16px}.report-columns,.templates{grid-template-columns:1fr}.report-heading{flex-direction:column}.report-card{padding:16px}.report-heading h1{font-size:23px}.report-run{position:static}.selected-fields{max-height:420px}.field-list{max-height:240px}}
</style>
