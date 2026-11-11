<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue';
import {DEFAULT_FORM_LAYOUT,FORM_PAGE,filterFormCopies,selectedFormCopies,formBook,formDocument,formLayout,loadFormCopies,type FormBook,type PrintCopy} from './copyForms';
const props=defineProps<{recordId:number;api:(path:string)=>Promise<any>}>();
const dialog=ref<HTMLDialogElement|null>(null),frame=ref<HTMLIFrameElement|null>(null),preview=ref<HTMLElement|null>(null);
const busy=ref(false),error=ref(''),overflow=ref(false),ready=ref(false),copies=ref<PrintCopy[]>([]),book=ref<FormBook|null>(null);
const selected=ref(new Set<number>()),query=ref('');
const selectedCopies=computed(()=>selectedFormCopies(copies.value,selected.value));
const filtered=computed(()=>filterFormCopies(copies.value,query.value));
const width=ref(DEFAULT_FORM_LAYOUT.width),height=ref(DEFAULT_FORM_LAYOUT.height),columns=ref(DEFAULT_FORM_LAYOUT.columns),revision=ref(0);
const layout=computed(()=>{try{return {value:formLayout(width.value,height.value,columns.value),error:''};}catch(e){return {value:null,error:(e as Error).message};}});
const documentHtml=computed(()=>book.value&&selectedCopies.value.length&&layout.value.value?formDocument(book.value,selectedCopies.value,width.value,height.value,columns.value):'');
const pages=computed(()=>layout.value.value?Math.ceil(selectedCopies.value.length/layout.value.value.perPage):0);
const previewScale=ref(1),mmToPx=96/25.4;
const documentHeight=computed(()=>pages.value*FORM_PAGE.height+Math.max(0,pages.value-1)*FORM_PAGE.previewGap);
let previewObserver:ResizeObserver|undefined;
function fitPreview(){if(preview.value)previewScale.value=Math.min(1,Math.max(1,preview.value.clientWidth-24)/(FORM_PAGE.width*mmToPx),Math.max(120,window.innerHeight*.6-24)/(FORM_PAGE.height*mmToPx));}
watch(preview,el=>{previewObserver?.disconnect();if(el){previewObserver=new ResizeObserver(fitPreview);previewObserver.observe(el);fitPreview();}},{flush:'post'});
onMounted(()=>window.addEventListener('resize',fitPreview));
watch(documentHtml,()=>{ready.value=false;overflow.value=false;revision.value++;},{flush:'sync'});
let generation=0;
function close(){generation++;busy.value=false;dialog.value?.close();}
watch(()=>props.recordId,()=>{close();book.value=null;copies.value=[];selected.value=new Set();});
onBeforeUnmount(()=>{generation++;previewObserver?.disconnect();window.removeEventListener('resize',fitPreview);});
async function open(){
 const token=++generation;
 dialog.value?.showModal();busy.value=true;error.value='';book.value=null;copies.value=[];selected.value=new Set();query.value='';ready.value=false;overflow.value=false;
 const id=props.recordId;
 try{const [record,items]=await Promise.all([props.api(`/records/${id}`),loadFormCopies(props.api,id)]);if(token!==generation||id!==props.recordId)return;book.value=formBook(record);copies.value=items;selected.value=new Set(items.map(c=>c.id));}catch(e){if(token===generation)error.value=e instanceof Error?e.message:String(e);}finally{if(token===generation)busy.value=false;}
}
function selectCopy(id:number,event:Event){const next=new Set(selected.value);if((event.target as HTMLInputElement).checked)next.add(id);else next.delete(id);selected.value=next;}
function chooseFound(){selected.value=new Set([...selected.value,...filtered.value.map(c=>c.id)]);}
async function inspect(){
 ready.value=false;const doc=frame.value?.contentDocument,version=revision.value;if(!doc)return;
 await doc.fonts.ready;
 if(version!==revision.value||doc!==frame.value?.contentDocument)return;
 overflow.value=Array.from(doc.querySelectorAll<HTMLElement>('.copy-form')).some(el=>el.scrollHeight>el.clientHeight+1||el.scrollWidth>el.clientWidth+1);ready.value=true;
}
function print(){if(ready.value&&!overflow.value&&selectedCopies.value.length&&layout.value.value){frame.value?.contentWindow?.focus();frame.value?.contentWindow?.print();}}
</script>
<template>
<button type="button" @click="open">Печать бланков экземпляров</button>
<dialog ref="dialog" class="modal card copy-forms-dialog" aria-labelledby="copy-forms-title" @cancel="generation++;busy=false">
<h2 id="copy-forms-title">Бланки экземпляров</h2>
<p>Выберите экземпляры для печати — по одному бланку на каждый выбранный экземпляр. Используются сохранённые данные карточки; списанные и отменённые экземпляры исключены.</p>
<div class="acquisition-grid">
<label>Ширина, мм<input v-model.number="width" type="number" min="35" max="200"></label>
<label>Высота, мм<input v-model.number="height" type="number" min="70" max="287"></label>
<label>Столбцов на A4<input v-model.number="columns" type="number" min="1" max="4"></label>
</div>
<p v-if="busy" role="status">Загрузка всех экземпляров…</p>
<p v-if="error||layout.error" class="inline-error" role="alert">{{error||layout.error}}</p>
<p v-if="!busy&&!error&&!copies.length">Нет действующих экземпляров для печати.</p>
<section v-if="copies.length" class="copy-selection" aria-label="Выбор экземпляров для печати">
  <div class="copy-selection-heading"><h3>Экземпляры для печати</h3><strong aria-live="polite">Выбрано {{selectedCopies.length}} из {{copies.length}}</strong></div>
  <input v-model="query" type="search" aria-label="Найти экземпляр для печати" placeholder="Инвентарный номер или штрихкод">
  <div class="copy-selection-actions"><button type="button" @click="selected=new Set(copies.map(c=>c.id))">Выбрать все</button><button type="button" :disabled="!selectedCopies.length" @click="selected=new Set()">Снять выбор</button><button v-if="query.trim()" type="button" :disabled="!filtered.length" @click="chooseFound">Выбрать найденные ({{filtered.length}})</button></div>
  <div class="copy-selection-list"><table><thead><tr><th>Печать</th><th>Инвентарный номер</th><th>Штрихкод</th><th>Цена</th></tr></thead><tbody><tr v-for="copy in filtered" :key="copy.id" :class="{selected:selected.has(copy.id)}"><td><input type="checkbox" :checked="selected.has(copy.id)" :aria-label="'Печатать экземпляр '+copy.inventory_number" @change="selectCopy(copy.id,$event)"></td><td>{{copy.inventory_number||'—'}}</td><td>{{copy.barcode||'—'}}</td><td>{{copy.unit_price===null?'—':Number(copy.unit_price).toFixed(2)}} {{copy.unit_price===null?'':copy.currency}}</td></tr></tbody></table><p v-if="!filtered.length">Экземпляры не найдены.</p></div>
  <p v-if="query.trim()">Поиск меняет список на экране. Выбранные ранее экземпляры остаются в печати.</p>
</section>
<p v-if="copies.length&&!selectedCopies.length" role="status">Выберите хотя бы один экземпляр для печати.</p>
<p v-if="selectedCopies.length&&layout.value" aria-live="polite">Бланков: {{selectedCopies.length}} · До {{layout.value.perPage}} на листе · Листов: {{Math.ceil(selectedCopies.length/layout.value.perPage)}}.</p>
<p>Слева вверху — полочный индекс (090$a), а если он отсутствует — УДК (080$a). Под ним — авторский знак (090$x), если он заполнен в карточке. Цена берётся из экземпляра; «—» означает, что она не указана.</p>
<p v-if="overflow" role="alert" class="inline-error">Текст не помещается в один из бланков. Увеличьте ширину или высоту.</p>
<p>Бланки соприкасаются по общей линии реза. От края бумаги оставлено 5 мм для рамок. В окне печати: A4, масштаб 100%, поля «Нет», колонтитулы выключены.</p>
<div class="modal-actions"><button type="button" @click="close">Закрыть</button><button type="button" class="primary" :disabled="busy||!ready||overflow||!!layout.error||!selectedCopies.length" @click="print">Печатать / сохранить PDF</button></div>
<section v-if="documentHtml" ref="preview" class="copy-forms-preview" aria-label="Предпросмотр листов A4">
 <div class="copy-forms-preview-size" :style="{width:FORM_PAGE.width*mmToPx*previewScale+'px',height:documentHeight*mmToPx*previewScale+'px'}">
  <iframe :key="revision" ref="frame" :srcdoc="documentHtml" :style="{width:FORM_PAGE.width+'mm',height:documentHeight+'mm',transform:`scale(${previewScale})`}" title="Предпросмотр бланков экземпляров" @load="inspect"></iframe>
 </div>
</section>
</dialog>
</template>
<style scoped>
.copy-forms-dialog{width:min(1000px,95vw);max-width:95vw}.copy-forms-preview{max-height:65vh;overflow:auto;margin-top:16px;padding:8px;background:#e5e7eb;border:1px solid #cbd5e1}.copy-forms-preview-size{position:relative;margin:auto;overflow:hidden}.copy-forms-preview iframe{position:absolute;top:0;left:0;border:0;transform-origin:top left}.copy-forms-dialog p{margin:12px 0}.copy-selection{margin-top:18px;padding:16px;border:1px solid #dce5ee;border-radius:12px}.copy-selection-heading{display:flex;justify-content:space-between;align-items:center;gap:12px}.copy-selection-heading h3{margin:0 0 12px}.copy-selection-heading strong{font-size:13px;color:#087b83;white-space:nowrap}.copy-selection input[type=search]{width:100%}.copy-selection-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.copy-selection-actions button{font-size:12px;padding:7px 12px}.copy-selection-list{max-height:260px;overflow:auto;border:1px solid #e4ebf1;border-radius:8px}.copy-selection-list table{width:100%;font-size:13px}.copy-selection-list th{position:sticky;top:0;background:#f1f5f9}.copy-selection-list th,.copy-selection-list td{padding:9px 12px;text-align:left;white-space:nowrap}.copy-selection-list input{width:18px;height:18px;cursor:pointer}.copy-selection-list .selected{background:#f2f9f9}.copy-selection>p{font-size:12px;color:#667b92}
</style>
