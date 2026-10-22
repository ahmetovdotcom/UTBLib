<script setup lang="ts">
import CopyForms from './CopyForms.vue';
import {authStorage} from "./authStorage";
import {ref,watch,onMounted,nextTick} from 'vue';
const props=defineProps<{canEdit:boolean,recordId:number,title:string,api:(path:string,method?:string,body?:unknown)=>Promise<any>}>();
const copies=ref<any[]>([]),total=ref(0),active=ref(0),onLoan=ref(0),matched=ref(0),offset=ref(0),query=ref(''),busy=ref(false),error=ref(''),notice=ref('');
const existingDialog=ref<HTMLDialogElement|null>(null),copyDialog=ref<HTMLDialogElement|null>(null),draft=ref<any>(null),copyDraft=ref<any>(null),history=ref<any[]>([]);
const pending=ref<any>(null);
const availabilityLabels:Record<string,string>={available:'В библиотеке',on_loan:'На руках',reserved:'Забронирован',withdrawn:'Списан',cancelled:'Отменён',lost:'Утрачен',repair:'В ремонте',processing:'На обработке',transfer:'В перемещении',display:'На выставке',reserve_stock:'Резервный фонд',unavailable:'Недоступен'};
function issuedDate(value:string){return new Date(/[Zz]|[+-]\d\d:\d\d$/.test(value)?value:value+'Z').toLocaleDateString('ru-RU',{timeZone:'Asia/Almaty'});}
function lockReason(c:any){return c.availability==='on_loan'?'Сначала оформите возврат: экземпляр находится у читателя.':c.availability==='reserved'?'Экземпляр забронирован. Изменение реквизитов недоступно.':'Экземпляр списан или отменён.';}
function today(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
async function load(){const id=props.recordId;const c=await props.api(`/records/${id}/copies?offset=${offset.value}&q=${encodeURIComponent(query.value)}`);if(id!==props.recordId)return;copies.value=c.items;total.value=c.total;active.value=c.active;onLoan.value=c.on_loan||0;matched.value=c.matched;}
async function run(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn();}catch(e){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}}
async function openExisting(){draft.value={request_key:crypto.randomUUID(),inventory_number:'',barcode:'',sigla:'',unit_price:'',currency:'KZT',received_on:'',source:'',checked_on:'',note:''};error.value='';await nextTick();existingDialog.value?.showModal();}
function forget(){authStorage.removeItem('pending-existing-copy');pending.value=null;}
async function postExisting(operation:any){
 authStorage.setItem('pending-existing-copy',JSON.stringify(operation));pending.value=operation;
 let saved:any;
 try{saved=await props.api(`/records/${operation.record_id}/copies`,'POST',operation.body);}catch(e){const status=(e as any).status;if(status>=400&&status<500)forget();throw e;}
 forget();existingDialog.value?.close();draft.value=null;notice.value=`Экземпляр ${saved.inventory_number} добавлен в имеющийся фонд. Поступление не создавалось.`;offset.value=0;await load();
}
async function submitExisting(){await run(async()=>{await postExisting({record_id:props.recordId,body:{...draft.value,unit_price:draft.value.unit_price===''?null:draft.value.unit_price,received_on:draft.value.received_on||null,checked_on:draft.value.checked_on||null}});});}
async function retry(){await run(async()=>{await postExisting(pending.value);});}
async function openCopy(c:any){copyDraft.value={...c};history.value=[];error.value='';await nextTick();copyDialog.value?.showModal();}
async function saveCopy(){await run(async()=>{const c=copyDraft.value;await props.api('/copies/'+c.id,'PUT',{version:c.version,inventory_number:c.inventory_number,barcode:c.barcode,sigla:c.sigla,checked_on:c.checked_on||null,note:c.note});copyDialog.value?.close();copyDraft.value=null;notice.value='Данные экземпляра сохранены. Сведения о поступлении не изменены.';await load();});}
async function showHistory(){history.value=await props.api('/copies/'+copyDraft.value.id+'/history');}
function onUnload(e:BeforeUnloadEvent){if(draft.value||copyDraft.value){e.preventDefault();e.returnValue='';}}
onMounted(()=>{try{pending.value=JSON.parse(authStorage.getItem('pending-existing-copy')||'null');}catch{}run(load);});
watch(()=>props.recordId,()=>{offset.value=0;query.value='';run(load);});
// Native dialogs prevent navigation under an open form; pending operations survive a page reload.
import {onUnmounted} from 'vue';
onMounted(()=>window.addEventListener('beforeunload',onUnload));onUnmounted(()=>window.removeEventListener('beforeunload',onUnload));
</script>
<template>
<section class="holdings card">
 <div class="page-heading"><div><h2>Экземпляры</h2><p><strong>На учёте: {{active}} · На руках: {{onLoan}} · Всего в истории: {{total}}</strong></p></div><button v-if="canEdit" class="primary" :disabled="busy||!!pending" @click="openExisting">＋ Создать экземпляр</button></div>
 <p class="profile-note">Выданные книги остаются на учёте библиотеки. Доступность каждого экземпляра показана отдельно; экземпляр на руках нельзя выдать повторно.</p>
 <CopyForms :record-id="recordId" :api="api" />
 <p class="profile-note">Здесь добавляются экземпляры уже имеющегося фонда — без накладной и без создания поступления. Новые партии оформляйте в разделе «Поступления» бокового меню.</p>
 <div v-if="pending&&canEdit" class="pending-note"><strong>Есть незавершённое создание экземпляра.</strong><p>Ответ мог потеряться. Повтор отправит ту же операцию и не создаст дубликат.</p><button :disabled="busy" @click="retry">Проверить и восстановить экземпляр</button></div>
 <p v-if="error" role="alert" class="inline-error">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
  <form class="holdings-search" @submit.prevent="offset=0;run(load)"><input v-model="query" placeholder="Инвентарный номер или штрихкод" aria-label="Поиск экземпляров"><button :disabled="busy">Найти экземпляр</button><button type="button" :disabled="busy" @click="run(load)">Обновить статусы</button></form>
  <div class="table-wrap"><table><thead><tr><th>Инвентарный номер</th><th>Доступность / выдача</th><th>Штрихкод</th><th>Сигла</th><th>Цена</th><th>Дата поступления</th><th>Источник / накладная</th><th>Проверка</th><th>Примечание</th><th></th></tr></thead><tbody><tr v-for="c in copies" :key="c.id"><td>{{c.inventory_number}}</td><td><span class="copy-state" :class="c.availability">{{availabilityLabels[c.availability]||'Статус не определён'}}</span><div v-if="c.loan" class="copy-loan"><strong>{{c.loan.reader_name}}</strong><small class="block">Билет {{c.loan.ticket_number}}</small><small class="block">Выдан: {{issuedDate(c.loan.issued_at)}}</small><small class="block">Вернуть до: {{issuedDate(c.loan.due_at)}}</small></div></td><td>{{c.barcode}}</td><td>{{c.sigla||'—'}}</td><td>{{c.unit_price===null?'Не указана':c.unit_price+' '+c.currency}}</td><td>{{c.received_on||'—'}}</td><td>{{c.source}}<small v-if="c.acquisition_id" class="block">{{c.invoice||'Без накладной'}} · Поступление №{{c.acquisition_id}}</small><small v-else class="block">Имеющийся фонд · без поступления</small></td><td>{{c.checked_on||'Не проверен'}}</td><td>{{c.note||'—'}}</td><td><button v-if="canEdit" :disabled="busy||!c.can_edit" :title="c.can_edit?'Изменить реквизиты экземпляра':lockReason(c)" :aria-label="'Изменить экземпляр '+c.id" @click="openCopy(c)">Изменить</button><small v-if="!c.can_edit" class="block">{{lockReason(c)}}</small></td></tr></tbody></table></div>
  <p v-if="!total">Экземпляры ещё не зарегистрированы. Для импортированных записей они не создаются автоматически.</p>
  <div class="table-footer"><span>Найдено: {{matched}}</span><div><button :disabled="busy||offset===0" @click="offset-=50;run(load)">Предыдущие экземпляры</button><button :disabled="busy||offset+copies.length>=matched" @click="offset+=50;run(load)">Следующие экземпляры</button></div></div>

</section>
<dialog ref="existingDialog" class="modal card acquisition-dialog" aria-labelledby="existing-title" @cancel="busy?$event.preventDefault():draft=null" @close="draft=null">
<form v-if="draft" @submit.prevent="submitExisting"><h2 id="existing-title">Создать экземпляр</h2><p>{{title}} · Имеющийся фонд. Этот экземпляр не попадёт в статистику новых поступлений.</p>
<fieldset :disabled="busy||!!pending" class="plain-fieldset acquisition-grid">
<label>Инвентарный номер<input v-model="draft.inventory_number" maxlength="100" placeholder="Автоматически, если не указан"></label>
<label>Штрихкод<input v-model="draft.barcode" maxlength="100" placeholder="Автоматически, если не указан"></label>
<label>Сигла хранения<input v-model="draft.sigla" maxlength="255"></label>
<label>Цена приобретения<input v-model="draft.unit_price" type="number" min="0" max="999999999999.99" step="0.01" placeholder="Не указана"></label>
<label>Валюта<select v-model="draft.currency"><option>KZT</option><option>RUB</option><option>USD</option><option>EUR</option></select></label>
<label>Дата поступления, если известна<input v-model="draft.received_on" type="date"></label>
<label>Источник, если известен<input v-model="draft.source" maxlength="255"></label>
<label>Дата проверки<input v-model="draft.checked_on" type="date" :max="today()"></label>
<label>Примечание<textarea v-model="draft.note" maxlength="4000"></textarea></label>
</fieldset><p v-if="error" role="alert" class="inline-error">{{error}}</p>
<div class="modal-actions"><button type="button" :disabled="busy" @click="existingDialog?.close()">Отмена</button><button v-if="pending" type="button" :disabled="busy" @click="retry">Повторить подтверждение</button><button v-else class="primary" :disabled="busy">Создать экземпляр</button></div></form>
</dialog>
<dialog ref="copyDialog" class="modal card" aria-labelledby="copy-title" @cancel="busy?$event.preventDefault():copyDraft=null" @close="copyDraft=null">
 <form v-if="copyDraft" @submit.prevent="saveCopy"><h2 id="copy-title">Экземпляр №{{copyDraft.id}}</h2><p v-if="copyDraft.acquisition_id">{{copyDraft.source}} · {{copyDraft.received_on}} · Накладная {{copyDraft.invoice||'не указана'}}</p><p v-else>Имеющийся фонд · без поступления. {{copyDraft.source}} {{copyDraft.received_on||''}}</p><p>Цена приобретения: {{copyDraft.unit_price===null?'не указана':copyDraft.unit_price+' '+copyDraft.currency}}. Цена сохранена при регистрации экземпляра.</p><fieldset :disabled="busy" class="plain-fieldset acquisition-grid"><label>Инвентарный номер<input v-model="copyDraft.inventory_number" maxlength="100" required></label><label>Штрихкод<input v-model="copyDraft.barcode" maxlength="100" required></label><label>Сигла хранения<input v-model="copyDraft.sigla" maxlength="255"></label><label>Дата проверки<input type="date" v-model="copyDraft.checked_on" :max="today()"><small>Пустая дата — экземпляр не проверен.</small></label><label>Примечание<textarea v-model="copyDraft.note" maxlength="4000"></textarea></label></fieldset><button type="button" :disabled="busy" @click="run(showHistory)">История изменений</button><ul><li v-for="h in history">{{h.created_at}} · версия {{h.after.version}}<details><summary>Что изменилось</summary><pre>{{JSON.stringify({до:h.before,после:h.after},null,2)}}</pre></details></li></ul><p v-if="error" class="inline-error" role="alert">{{error}}</p><div class="modal-actions"><button type="button" :disabled="busy" @click="copyDialog?.close()">Отмена</button><button class="primary" :disabled="busy">Сохранить экземпляр</button></div></form>
</dialog>
</template>

<style scoped>
.copy-state{display:inline-block;padding:5px 10px;border:1px solid #dce5ef;border-radius:20px;background:#f2f5f8;white-space:nowrap;font-size:12px}.copy-state.on_loan{background:#fff4df;color:#895c13;border-color:#ecd59f}.copy-state.available{background:#eaf8f1;color:#287554;border-color:#bce4cf}.copy-state.reserved{background:#edf3ff;color:#365b91;border-color:#c7d8f0}.copy-loan{margin-top:12px;min-width:170px}.copy-loan strong{font-size:12px}.holdings-search{flex-wrap:wrap}
</style>
