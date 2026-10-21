<script setup lang="ts">
import {authStorage} from "./authStorage";
import {ref,nextTick,onMounted,onUnmounted} from 'vue';
const props=defineProps<{api:(path:string,method?:string,body?:unknown)=>Promise<any>}>();
const emit=defineEmits<{created:[]}>();
const receiptDialog=ref<HTMLDialogElement|null>(null),draft=ref<any>(null),busy=ref(false),error=ref(''),notice=ref('');
const editingId=ref<number|null>(null);
const search=ref(''),found=ref<any[]>([]),pending=ref<any>(null);
function today(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
function titleOf(r:any){return r.marc.fields.filter((f:any)=>f.tag==='245').flatMap((f:any)=>f.subfields||[]).filter((s:any)=>['a','b'].includes(s.code)).map((s:any)=>s.value).join(' ')||'Без заглавия';}
async function run(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn();}catch(e){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}}
function line(record_id:number,title:string){return {record_id,title,quantity:1,unit_price:'',currency:'KZT',sigla:'',note:''};}
async function openReceipt(){editingId.value=null;draft.value={request_key:crypto.randomUUID(),invoice:'',source:'',received_on:today(),document_on:null,note:'',lines:[]};found.value=[];search.value='';error.value='';await nextTick();receiptDialog.value?.showModal();}
async function openEdit(id:number){await run(async()=>{const r=await props.api('/acquisitions/'+id);editingId.value=id;draft.value={request_key:crypto.randomUUID(),version:r.version,reason:'',invoice:r.invoice,source:r.source,received_on:r.received_on,document_on:r.document_on||null,note:r.note,lines:r.lines.map((l:any)=>({...l,unit_price:l.unit_price??'',original_quantity:l.quantity,cancel_copy_ids:[],copies:r.copies.filter((c:any)=>c.line_id===l.id&&c.status==='active')}))};found.value=[];search.value='';await nextTick();receiptDialog.value?.showModal();});}
defineExpose({openEdit});
async function findRecords(){found.value=await props.api('/records?limit=20&q='+encodeURIComponent(search.value));}
function addTitle(r:any){draft.value.lines.push(line(r.id,titleOf(r)));found.value=[];search.value='';}
function remember(operation:any){authStorage.setItem('pending-acquisition',JSON.stringify(operation));pending.value=operation;}
function forget(){authStorage.removeItem('pending-acquisition');pending.value=null;}
async function postReceipt(body:any,path='/acquisitions',method='POST'){
 remember({body,path,method});
 let saved:any;
 try{saved=await props.api(path,method,body);}catch(e){const status=(e as any).status;if(status>=400&&status<500)forget();throw e;}
 forget();receiptDialog.value?.close();draft.value=null;notice.value=`Поступление №${saved.id} сохранено: ${saved.quantity} экземпляров.`;emit('created');
}
async function submitReceipt(){await run(async()=>{const body={...draft.value,document_on:draft.value.document_on||null,lines:draft.value.lines.map((l:any)=>({...(editingId.value?{id:l.id||null,cancel_copy_ids:l.quantity<l.original_quantity?l.cancel_copy_ids:[]}:{}),record_id:l.record_id,quantity:l.quantity,unit_price:l.unit_price===''?null:l.unit_price,currency:l.currency,sigla:l.sigla,note:l.note}))};await postReceipt(body,editingId.value?'/acquisitions/'+editingId.value:'/acquisitions',editingId.value?'PUT':'POST');});}
async function retry(){await run(async()=>{const p=pending.value;await postReceipt(p.body||p,p.path||'/acquisitions',p.method||'POST');});}
function onUnload(e:BeforeUnloadEvent){if(draft.value){e.preventDefault();e.returnValue='';}}
onMounted(()=>{try{pending.value=JSON.parse(authStorage.getItem('pending-acquisition')||'null');}catch{}window.addEventListener('beforeunload',onUnload);});
onUnmounted(()=>window.removeEventListener('beforeunload',onUnload));
</script>
<template>
<button class="primary" :disabled="busy||!!pending" @click="openReceipt">＋ Новое поступление</button>
<div v-if="pending" class="pending-note"><p>Есть незавершённое подтверждение поступления. Повтор не создаст дубликат.</p><button :disabled="busy" @click="retry">Проверить и восстановить поступление</button></div>
<p v-if="error&&!draft" role="alert" class="inline-error">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
<dialog ref="receiptDialog" class="modal card acquisition-dialog" aria-labelledby="receipt-title" @cancel="busy?$event.preventDefault():draft=null" @close="draft=null">
 <form v-if="draft" @submit.prevent="submitReceipt"><h2 id="receipt-title">{{editingId?'Изменить поступление №'+editingId:'Новое поступление'}}</h2><p>Одна накладная может включать несколько названий книг. При исправлении сохраняются номера существующих экземпляров; увеличение количества добавляет только недостающие.</p>
 <fieldset :disabled="busy||!!pending" class="plain-fieldset"><label v-if="editingId">Причина исправления<input v-model="draft.reason" required maxlength="4000"></label><div class="acquisition-grid"><label>Накладная<input v-model="draft.invoice" maxlength="255" placeholder="Номер и название документа"></label><label>Дата поступления<input type="date" v-model="draft.received_on" required></label><label>Дата накладной (если указана)<input type="date" v-model="draft.document_on"></label><label>Источник поступления<input v-model="draft.source" maxlength="255" required placeholder="Например, УТБ"></label><label>Примечание к поступлению<input v-model="draft.note" maxlength="4000"></label></div>
 <section class="receipt-line" v-for="(l,i) in draft.lines" :key="i"><h3>{{l.title}} <small>Запись №{{l.record_id}}</small></h3><div class="acquisition-grid"><label>Количество экземпляров<input type="number" :min="l.id?0:1" max="10000" step="1" v-model.number="l.quantity" required></label><label>Цена одного экземпляра<input type="number" min="0" max="999999999999.99" step="0.01" v-model="l.unit_price" placeholder="Не указана"></label><label>Валюта<select v-model="l.currency"><option>KZT</option><option>RUB</option><option>USD</option><option>EUR</option></select></label><label>Сигла хранения<input v-model="l.sigla" maxlength="255"></label><label>Примечание к экземплярам<input v-model="l.note" maxlength="4000"></label></div><div v-if="l.id&&l.quantity<l.original_quantity" class="pending-note"><p>Выберите {{l.original_quantity-l.quantity}} экземпляров для отмены:</p><label v-for="c in l.copies" :key="c.id" class="check-label"><input type="checkbox" v-model="l.cancel_copy_ids" :value="c.id">{{c.inventory_number}} · {{c.sigla||'—'}}</label></div><button v-if="!l.id" type="button" @click="draft.lines.splice(i,1)">Убрать строку из новой партии</button></section>
 <div class="receipt-line"><label>Выбрать книгу из каталога<input v-model="search" placeholder="Название, автор или ISBN"></label><button type="button" @click="run(findRecords)">Найти книгу</button><ul class="title-results"><li v-for="r in found"><button type="button" @click="addTitle(r)">{{titleOf(r)}} · №{{r.id}}</button></li></ul></div>
 <p><strong>Количество в партии: {{draft.lines.reduce((n:number,l:any)=>n+Number(l.quantity||0),0)}} экземпляров.</strong> Номера и штрихкоды будут назначены автоматически; их можно изменить в экземпляре.</p></fieldset>
 <p v-if="error" class="inline-error" role="alert">{{error}}</p><p v-if="pending">Ответ не получен. Повторите ту же операцию кнопкой ниже.</p>
 <div class="modal-actions"><button type="button" :disabled="busy" @click="receiptDialog?.close()">Отмена</button><button v-if="pending" type="button" class="primary" :disabled="busy" @click="retry">Повторить подтверждение</button><button v-else class="primary" :disabled="busy||!draft.lines.length">{{editingId?'Сохранить исправление':'Зарегистрировать поступление'}}</button></div></form>
</dialog>
</template>
