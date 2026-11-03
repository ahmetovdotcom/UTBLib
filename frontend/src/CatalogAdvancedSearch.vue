<script setup lang="ts">
import {computed,ref,watch,nextTick,onBeforeUnmount} from 'vue';
import {fieldName,subName} from './ru';
import type {SearchCondition} from './catalogSearch';
type FieldOption={key:string;tag:string;code:string|null;label:string;parent_label:string;local:boolean;configured:boolean;count:number};
type Term={value:string;count:number};
const props=defineProps<{open:boolean;conditions:SearchCondition[];match:'all'|'any';typeId:number;api:(path:string)=>Promise<any>;busy:boolean;error:string}>();
const emit=defineEmits<{close:[];apply:[conditions:SearchCondition[],match:'all'|'any']}>();
const dialog=ref<HTMLDialogElement|null>(null),valueInput=ref<HTMLInputElement|null>(null);
const fields=ref<FieldOption[]>([]),fieldQuery=ref(''),showAll=ref(false),selectedField=ref('245$b');
const terms=ref<Term[]>([]),query=ref(''),offset=ref(0),total=ref(0),loading=ref(false),loadingFields=ref(false);
const valuesError=ref(''),fieldsError=ref(''),selectionError=ref('');
const chosen=ref<SearchCondition[]>([]),mode=ref<'all'|'any'>('any');
const manualOpen=ref(false),manualValue=ref(''),manualOperator=ref<SearchCondition['operator']>('contains');
let optionsRequest=0,valuesRequest=0,timer:ReturnType<typeof setTimeout>|undefined,returnFocus:HTMLElement|null=null;
const key=(s:string)=>s.trim().toLocaleLowerCase();
function label(f:FieldOption){return f.local?f.label:f.code?subName(f.tag,f.code,f.label):fieldName(f.tag,f.label);}
const selected=computed(()=>fields.value.find(f=>f.key===selectedField.value));
function fieldLabel(code:string){const f=fields.value.find(f=>f.key===code);const [tag,sf]=code.split('$');return f?label(f):sf?subName(tag,sf,code):fieldName(tag,code);}
const visibleFields=computed(()=>{
 const q=key(fieldQuery.value);
 return fields.value.filter(f=>(showAll.value||((f.code||Number(f.tag)<10)&&(f.configured||f.count>0))||f.key===selectedField.value)&&(!q||`${label(f)} ${f.key}`.toLocaleLowerCase().includes(q)))
  .sort((a,b)=>Number(b.configured)-Number(a.configured)||a.key.localeCompare(b.key));
});
const names={equals:'Точное значение',contains:'Содержит',starts_with:'Начинается с'};
function isChosen(term:Term){return chosen.value.some(c=>c.field===selectedField.value&&c.operator==='equals'&&key(c.value)===key(term.value));}
function add(condition:SearchCondition){
 selectionError.value='';
 if(chosen.value.some(c=>c.field===condition.field&&c.operator===condition.operator&&key(c.value)===key(condition.value)))return;
 if(chosen.value.length>=8){selectionError.value='Можно выбрать до 8 значений или условий. Уберите одно из выбранных.';return;}
 if(condition.value.length>20000){selectionError.value='Значение слишком длинное. Используйте поиск по фрагменту текста.';return;}
 chosen.value.push({...condition,value:condition.value.trim()});
}
function toggle(term:Term){
 if(isChosen(term))chosen.value=chosen.value.filter(c=>!(c.field===selectedField.value&&c.operator==='equals'&&key(c.value)===key(term.value)));
 else add({field:selectedField.value,operator:'equals',value:term.value});
}
function addManual(){if(!manualValue.value.trim()){selectionError.value='Введите текст условия.';return;}add({field:selectedField.value,operator:manualOperator.value,value:manualValue.value});}
function clear(){chosen.value=[];selectionError.value='';}
function close(){if(!props.busy)emit('close');}
async function loadFields(){
 const id=++optionsRequest;loadingFields.value=true;fieldsError.value='';
 try{const result=await props.api('/catalog-search/options'+(props.typeId?'?type_id='+props.typeId:''));if(id===optionsRequest)fields.value=result.fields;}
 catch(e){if(id===optionsRequest)fieldsError.value=e instanceof Error?e.message:String(e);}
 finally{if(id===optionsRequest){loadingFields.value=false;await nextTick();const list=dialog.value?.querySelector<HTMLElement>('.search-fields-list');const row=list?.querySelector<HTMLElement>('[aria-pressed=true]');if(list&&row)list.scrollTop+=row.getBoundingClientRect().top-list.getBoundingClientRect().top-(list.clientHeight-row.clientHeight)/2;}}
}
async function loadValues(start=0){
 clearTimeout(timer);const id=++valuesRequest;loading.value=true;valuesError.value='';terms.value=[];offset.value=start;total.value=0;
 const params=new URLSearchParams({field:selectedField.value,q:query.value.trim(),offset:String(start),limit:'50'});
 if(props.typeId)params.set('type_id',String(props.typeId));
 try{const result=await props.api('/catalog-search/values?'+params);if(id===valuesRequest){terms.value=result.items;total.value=result.total;}}
 catch(e){if(id===valuesRequest)valuesError.value=e instanceof Error?e.message:String(e);}
 finally{if(id===valuesRequest)loading.value=false;}
}
watch(query,()=>{
 if(!props.open)return;
 ++valuesRequest;terms.value=[];total.value=0;loading.value=true;clearTimeout(timer);
 timer=setTimeout(()=>void loadValues(),250);
});
function selectField(f:FieldOption){selectedField.value=f.key;query.value='';manualValue.value='';selectionError.value='';void loadValues();}
watch(()=>props.open,async open=>{
 if(!open){clearTimeout(timer);++optionsRequest;++valuesRequest;dialog.value?.close();returnFocus?.focus();return;}
 returnFocus=document.activeElement as HTMLElement;
 chosen.value=props.conditions.map(c=>({...c}));mode.value=chosen.value.length?props.match:'any';
 selectedField.value=chosen.value[0]?.field||'245$b';fieldQuery.value='';query.value='';showAll.value=false;manualValue.value='';manualOpen.value=false;selectionError.value='';
 await nextTick();dialog.value?.showModal();valueInput.value?.focus();
 void loadFields();void loadValues();
},{immediate:true});
onBeforeUnmount(()=>{clearTimeout(timer);++optionsRequest;++valuesRequest;dialog.value?.close();});
</script>
<template>
<Teleport to="body">
<dialog id="catalog-advanced-search" ref="dialog" class="catalog-search-dialog" aria-labelledby="catalog-search-title" @cancel.prevent="close" @contextmenu.stop>
 <header class="search-dialog-header"><div><h2 id="catalog-search-title">Расширенный поиск</h2><p>Выберите поле и значения, которые встречаются в каталоге.</p></div><button type="button" class="close-search" aria-label="Закрыть расширенный поиск" :disabled="busy" @click="close">×</button></header>
 <div class="search-dialog-body">
  <p v-if="error" class="search-error" role="alert">{{error}}</p>
  <div class="search-dictionary-layout">
   <section class="search-values-panel" aria-label="Значения выбранного поля">
    <div class="search-panel-heading"><h3>{{fieldLabel(selectedField)}}</h3><small>{{selectedField}}<template v-if="selected&&!selected.code&&Number(selected.tag)>=10"> · любое подполе</template></small></div>
    <label class="search-values-query">Найти значение<input ref="valueInput" v-model="query" type="search" maxlength="300" placeholder="Например, монография" @keydown.enter.prevent="loadValues()"></label>
    <p v-if="loading" class="search-state" role="status">Загрузка значений…</p>
    <p v-else-if="valuesError" class="search-error" role="alert">{{valuesError}} <button type="button" @click="loadValues(offset)">Повторить</button></p>
    <div v-else class="search-terms-scroll">
     <table class="search-terms-table"><thead><tr><th><span class="sr-only">Выбрать</span></th><th>Значение</th><th>Записей</th></tr></thead><tbody>
      <tr v-for="term in terms" :key="term.value" :class="{selected:isChosen(term)}"><td><input type="checkbox" :checked="isChosen(term)" :aria-label="'Выбрать значение '+term.value" :disabled="busy" @change="toggle(term)"></td><td><button class="term-choice" type="button" :title="term.value" :aria-pressed="isChosen(term)" :disabled="busy" @click="toggle(term)">{{term.value}}</button></td><td class="term-count">{{term.count.toLocaleString('ru-RU')}}</td></tr>
     </tbody></table>
     <p v-if="!terms.length" class="search-state">{{query?'Совпадающих значений нет. Измените текст поиска.':'В этом поле пока нет заполненных значений.'}}</p>
    </div>
    <nav class="search-values-pages" aria-label="Страницы значений"><small>{{total?'Значения '+(offset+1)+'–'+Math.min(offset+50,total)+' из '+total:'Нет значений'}}</small><button type="button" :disabled="loading||offset===0" @click="loadValues(Math.max(0,offset-50))">← Назад</button><button type="button" :disabled="loading||offset+50>=total" @click="loadValues(offset+50)">Далее →</button></nav>
    <p class="search-note">Количество — число карточек{{typeId?' выбранного типа':' во всём каталоге'}}, без остальных фильтров. Повторы одного значения внутри карточки считаются один раз.</p>
    <button type="button" class="manual-search-toggle" :aria-expanded="manualOpen" @click="manualOpen=!manualOpen">{{manualOpen?'Скрыть поиск по тексту':'Добавить условие по тексту…'}}</button>
    <div v-if="manualOpen" class="manual-search"><label>Условие<select v-model="manualOperator"><option value="contains">Содержит</option><option value="equals">Точное значение</option><option value="starts_with">Начинается с</option></select></label><label>Текст условия<input v-model="manualValue" maxlength="300" placeholder="Например, монография" @keydown.enter.prevent="addManual"></label><button type="button" :disabled="busy" @click="addManual">Добавить условие</button></div>
   </section>
   <aside class="search-fields-panel">
    <section class="search-fields-box" aria-label="Поля каталога"><div class="search-panel-heading"><h3>Поля каталога</h3><small>{{visibleFields.length}}</small></div><label class="search-field-query"><span class="sr-only">Найти поле</span><input v-model="fieldQuery" type="search" placeholder="Название или код поля"></label><label class="search-all-fields"><input v-model="showAll" type="checkbox">Показать все поля</label>
     <p v-if="loadingFields" class="search-state" role="status">Загрузка полей…</p><p v-else-if="fieldsError" class="search-error" role="alert">{{fieldsError}} <button type="button" @click="loadFields">Повторить</button></p>
     <div v-else class="search-fields-list"><button v-for="f in visibleFields" :key="f.key" type="button" :aria-pressed="selectedField===f.key" :class="{selected:selectedField===f.key}" @click="selectField(f)"><span>{{label(f)}}<small>{{f.key}}<template v-if="!f.code&&Number(f.tag)>=10"> · любое подполе</template></small></span><small>{{f.count.toLocaleString('ru-RU')}}</small></button><p v-if="!visibleFields.length" class="search-state">Поля не найдены.</p></div>
    </section>
    <section class="search-selected-box" aria-label="Отобранные значения"><div class="search-panel-heading"><h3>Отобранные значения</h3><small>{{chosen.length}} / 8</small></div><div class="search-selected-list"><p v-if="!chosen.length" class="search-state">Отметьте нужные значения в таблице слева.</p><div v-for="(c,i) in chosen" :key="i" class="search-selected-term"><div><small>{{fieldLabel(c.field)}} · {{names[c.operator]}}</small><p :title="c.value">{{c.value}}</p></div><button type="button" :aria-label="'Убрать выбранное значение '+(i+1)" :disabled="busy" @click="chosen.splice(i,1);selectionError=''">×</button></div></div><div v-if="chosen.length" class="search-selection-controls"><label>Показать записи<select v-model="mode" aria-label="Объединение выбранных значений"><option value="any">С любым значением (ИЛИ)</option><option value="all">Со всеми значениями (И)</option></select></label><button type="button" :disabled="busy" @click="clear">Очистить выбор</button></div></section>
   </aside>
  </div>
  <p v-if="selectionError" class="search-error" role="alert">{{selectionError}}</p>
 </div>
 <footer class="search-dialog-footer"><small>Поиск без учёта регистра. Общий поиск и тип документа также учитываются.</small><button type="button" :disabled="busy" @click="close">Отмена</button><button type="button" class="primary" :disabled="busy||!chosen.length" @click="emit('apply',chosen.map(c=>({...c})),mode)">{{busy?'Поиск…':'Показать записи'}}</button></footer>
</dialog>
</Teleport>
</template>
<style scoped>
.catalog-search-dialog{width:min(1140px,calc(100vw - 32px));max-width:none;max-height:calc(100dvh - 32px);padding:0;border:1px solid #dce5ee;border-radius:18px;color:#19334b;background:#fff;box-shadow:0 24px 70px #0b263b38;overflow:hidden}.catalog-search-dialog[open]{display:flex;flex-direction:column}.catalog-search-dialog::backdrop{background:#10263c77}.catalog-search-dialog *{box-sizing:border-box}.search-dialog-header{display:flex;justify-content:space-between;gap:16px;padding:22px 26px 18px;border-bottom:1px solid #e1e8ef;flex-shrink:0}.search-dialog-header h2{font-size:24px;margin:0;color:#082b45}.search-dialog-header p{font-size:14px;color:#6b7e92;margin:6px 0 0}.catalog-search-dialog button,.catalog-search-dialog input,.catalog-search-dialog select{font:inherit;color:inherit}.catalog-search-dialog button{background:#fff;border:1px solid #cedae5;border-radius:9px;padding:9px 13px;cursor:pointer}.catalog-search-dialog button:disabled{opacity:.5;cursor:default}.catalog-search-dialog :focus-visible{outline:2px solid #00858c;outline-offset:2px}.catalog-search-dialog input:not([type=checkbox]),.catalog-search-dialog select{width:100%;padding:10px 12px;border:1px solid #cad7e3;border-radius:9px;background:white;min-width:0}.catalog-search-dialog input[type=checkbox]{accent-color:#087b83;width:17px;height:17px;flex-shrink:0;cursor:pointer}.catalog-search-dialog label{font-size:13px;font-weight:600}.search-dialog-header .close-search{height:36px;width:36px;padding:0;font-size:24px}.search-dialog-body{padding:20px 26px;overflow:auto;overscroll-behavior:contain}.search-dictionary-layout{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(300px,1fr);gap:20px;align-items:start}.search-values-panel,.search-fields-box,.search-selected-box{border:1px solid #dce5ee;border-radius:12px;overflow:hidden;min-width:0}.search-panel-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;background:#f5f8fb;padding:14px 16px;border-bottom:1px solid #e1e8ef}.search-panel-heading h3{font-size:15px;margin:0;overflow-wrap:anywhere}.search-panel-heading small{font-size:11px;color:#6b7e92;text-align:right;flex-shrink:0}.search-values-query{display:block;padding:14px 16px}.search-values-query input{margin-top:7px}.search-terms-scroll{height:370px;overflow:auto;overscroll-behavior:contain}.search-terms-table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:14px}.search-terms-table th{position:sticky;top:0;background:#f4f6f9;color:#65778b;font-size:12px;font-weight:600;padding:10px 6px;text-align:left;border-bottom:1px solid #dce5ee;z-index:1}.search-terms-table th:first-child{width:40px}.search-terms-table th:last-child{width:78px;text-align:right;padding-right:16px}.search-terms-table td{padding:0 6px;border-bottom:1px solid #edf1f5;vertical-align:middle}.search-terms-table td:first-child{padding-left:14px}.search-terms-table tr:hover{background:#f5fafb}.search-terms-table tr.selected{background:#e7f4f4}.search-terms-table .term-choice{border:0;background:none;border-radius:0;box-shadow:none;text-align:left;padding:11px 0;width:100%;overflow-wrap:anywhere;font-weight:400;font-size:14px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.term-count{text-align:right;font-variant-numeric:tabular-nums;padding-right:16px!important;font-weight:600}.search-values-pages{padding:12px;display:flex;align-items:center;gap:8px;border-top:1px solid #e1e8ef}.search-values-pages small{margin-right:auto;color:#6b7e92;font-size:12px}.search-values-pages button{font-size:12px;padding:7px 10px}.search-note{font-size:12px;line-height:1.6;color:#6b7e92;margin:0;padding:0 16px 12px}.search-values-panel>.manual-search-toggle{margin:0 16px 14px;font-size:12px;border:0;color:#087b83;padding:0}.manual-search{border-top:1px solid #e1e8ef;padding:14px 16px;display:grid;gap:10px}.manual-search label{display:grid;gap:5px}.manual-search button{justify-self:start;font-size:12px}.search-fields-panel{display:grid;gap:16px;min-width:0}.search-field-query{display:block;padding:12px}.search-all-fields{display:flex;flex-direction:row;justify-content:flex-start;align-items:center;gap:8px;margin:0 12px 10px;font-weight:400!important;font-size:12px!important}.search-fields-list{height:225px;overflow:auto;overscroll-behavior:contain;border-top:1px solid #edf1f5}.search-fields-list button{width:100%;border:0;border-bottom:1px solid #edf1f5;border-radius:0;box-shadow:none;display:flex;align-items:center;justify-content:space-between;gap:12px;text-align:left;font-size:13px;padding:10px 14px}.search-fields-list button>span{min-width:0;overflow-wrap:anywhere}.search-fields-list button small{color:#6b7e92;font-size:11px}.search-fields-list button>span small{display:block;margin-top:3px}.search-fields-list button.selected{background:#e7f4f4;box-shadow:inset 3px 0 #087b83;color:#075c64}.search-fields-list button:hover{background:#f2f8f9}.search-selected-list{max-height:175px;overflow:auto;overscroll-behavior:contain}.search-selected-term{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 14px;border-bottom:1px solid #edf1f5}.search-selected-term>div{min-width:0}.search-selected-term small{font-size:11px;color:#6b7e92}.search-selected-term p{font-size:13px;font-weight:600;margin:4px 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.search-selected-term button{padding:0;width:25px;height:25px;flex-shrink:0;border:0;font-size:20px}.search-selection-controls{display:grid;gap:8px;padding:12px;border-top:1px solid #e1e8ef}.search-selection-controls label{display:grid;gap:6px}.search-selection-controls button{font-size:12px;justify-self:start;padding:0;border:0;color:#6b7e92}.search-state{padding:18px 16px;font-size:13px;line-height:1.6;color:#6b7e92;margin:0}.search-values-panel>p.search-state{height:370px}.search-error{margin:0 0 12px;padding:12px;background:#fff2ef;border:1px solid #f2cec6;border-radius:8px;color:#aa483b;font-size:13px;line-height:1.5}.search-dialog-footer{padding:16px 26px;border-top:1px solid #e1e8ef;display:flex;align-items:center;gap:12px;background:#f8fafc;flex-shrink:0}.search-dialog-footer small{margin-right:auto;max-width:540px;color:#6b7e92;font-size:12px;line-height:1.6}.search-dialog-footer button{white-space:nowrap;font-size:14px;font-weight:600}.search-dialog-footer .primary{background:#082b45;border-color:#082b45;color:#fff}
@media(max-width:760px){.search-dictionary-layout{grid-template-columns:1fr}.search-fields-panel{grid-row:1}.search-fields-list{height:150px}.search-selected-list{max-height:120px}.search-terms-scroll{height:240px}.search-dialog-body{padding:14px}.search-dialog-header{padding:16px}.search-dialog-header h2{font-size:20px}.search-dialog-footer{padding:12px 14px;flex-wrap:wrap}.search-dialog-footer small{width:100%;max-width:none}.search-dialog-footer button:first-of-type{margin-left:auto}.search-values-panel>p.search-state{height:240px}.search-values-pages{flex-wrap:wrap}.search-panel-heading{padding:12px}}
</style>
