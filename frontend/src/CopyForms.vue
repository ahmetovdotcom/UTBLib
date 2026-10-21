<script setup lang="ts">
import {computed,ref} from 'vue';
import {formBook,formDocument,formLayout,loadFormCopies,type FormBook,type PrintCopy} from './copyForms';
const props=defineProps<{recordId:number;api:(path:string)=>Promise<any>}>();
const dialog=ref<HTMLDialogElement|null>(null),frame=ref<HTMLIFrameElement|null>(null);
const busy=ref(false),error=ref(''),overflow=ref(false),ready=ref(false),copies=ref<PrintCopy[]>([]),book=ref<FormBook|null>(null);
const width=ref(40),height=ref(100),columns=ref(3);
const layout=computed(()=>{try{return {value:formLayout(width.value,height.value,columns.value),error:''};}catch(e){return {value:null,error:(e as Error).message};}});
const documentHtml=computed(()=>book.value&&copies.value.length&&layout.value.value?formDocument(book.value,copies.value,width.value,height.value,columns.value):'');
async function open(){
 dialog.value?.showModal();busy.value=true;error.value='';book.value=null;copies.value=[];ready.value=false;overflow.value=false;
 const id=props.recordId;
 try{const [record,items]=await Promise.all([props.api(`/records/${id}`),loadFormCopies(props.api,id)]);book.value=formBook(record);copies.value=items;}catch(e){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}
}
async function inspect(){ready.value=false;const doc=frame.value?.contentDocument;if(!doc)return;await doc.fonts.ready;overflow.value=Array.from(doc.querySelectorAll<HTMLElement>('.copy-form')).some(el=>el.scrollHeight>el.clientHeight+1||el.scrollWidth>el.clientWidth+1);ready.value=true;}
function print(){if(ready.value&&!overflow.value){frame.value?.contentWindow?.focus();frame.value?.contentWindow?.print();}}
</script>
<template>
<button type="button" @click="open">Печать бланков экземпляров</button>
<dialog ref="dialog" class="modal card copy-forms-dialog" aria-labelledby="copy-forms-title">
<h2 id="copy-forms-title">Бланки экземпляров</h2>
<p>По одному бланку на каждый действующий экземпляр этой книги. Используются сохранённые данные карточки; списанные и отменённые экземпляры исключены.</p>
<div class="acquisition-grid">
<label>Ширина, мм<input v-model.number="width" type="number" min="35" max="190" @input="ready=false"></label>
<label>Высота, мм<input v-model.number="height" type="number" min="70" max="277" @input="ready=false"></label>
<label>Столбцов на A4<input v-model.number="columns" type="number" min="1" max="4" @input="ready=false"></label>
</div>
<p v-if="busy" role="status">Загрузка всех экземпляров…</p>
<p v-if="error||layout.error" class="inline-error" role="alert">{{error||layout.error}}</p>
<p v-if="!busy&&!error&&!copies.length">Нет действующих экземпляров для печати.</p>
<p v-if="copies.length&&layout.value">Бланков: {{copies.length}} · До {{layout.value.perPage}} на листе · Листов: {{Math.ceil(copies.length/layout.value.perPage)}}.</p>
<p>Слева вверху — полочный индекс (090$a), а если он отсутствует — УДК (080$a). Цена берётся из экземпляра; «—» означает, что она не указана.</p>
<p v-if="overflow" role="alert" class="inline-error">Текст не помещается в один из бланков. Увеличьте ширину или высоту.</p>
<p>В окне печати выберите A4, масштаб 100%, отключите колонтитулы браузера.</p>
<div class="modal-actions"><button type="button" @click="dialog?.close()">Закрыть</button><button type="button" class="primary" :disabled="busy||!ready||overflow||!!layout.error||!copies.length" @click="print">Печатать / сохранить PDF</button></div>
<iframe v-if="documentHtml" ref="frame" :srcdoc="documentHtml" title="Предпросмотр бланков экземпляров" @load="inspect"></iframe>
</dialog>
</template>
<style scoped>
.copy-forms-dialog{width:min(1000px,95vw);max-width:95vw}.copy-forms-dialog iframe{width:100%;height:60vh;border:1px solid #cbd5e1;margin-top:16px}.copy-forms-dialog p{margin:12px 0}
</style>
