<script setup lang="ts">
import {authStorage} from "./authStorage";
import {onMounted,ref,nextTick} from 'vue';
import AcquisitionCreate from './AcquisitionCreate.vue';
const props=defineProps<{canEdit:boolean,canCancel:boolean,api:(path:string,method?:string,body?:unknown)=>Promise<any>}>();
const creator=ref<InstanceType<typeof AcquisitionCreate>|null>(null),cancelDialog=ref<HTMLDialogElement|null>(null),historyDialog=ref<HTMLDialogElement|null>(null),cancelDraft=ref<any>(null),changes=ref<any[]>([]),pendingCancel=ref<any>(null);
const requestedReceipt=ref<number|null>(null);
const receipts=ref<any[]>([]),total=ref(0),offset=ref(0),busy=ref(false),error=ref('');
async function load(nextOffset=offset.value){
 if(busy.value)return;
 busy.value=true;error.value='';
 try{
  const result=await props.api(`/acquisitions?offset=${nextOffset}&limit=20`);
  if(requestedReceipt.value){receipts.value=[await props.api('/acquisitions/'+requestedReceipt.value)];total.value=1;offset.value=0;}else{receipts.value=result.items;total.value=result.total;offset.value=nextOffset;}
 }catch(e){error.value=e instanceof Error?e.message:String(e);}
 finally{busy.value=false;}
}
async function openReceipt(id:number){requestedReceipt.value=props.canEdit?null:id;if(props.canEdit){await creator.value?.openEdit(id);}else{try{receipts.value=[await props.api('/acquisitions/'+id)];total.value=1;offset.value=0;}catch(e){error.value=String(e);}}}
defineExpose({openReceipt});
async function openCancel(r:any){cancelDraft.value={id:r.id,version:r.version,request_key:crypto.randomUUID(),reason:''};await nextTick();cancelDialog.value?.showModal();}
async function cancelReceipt(operation:any){if(busy.value)return;busy.value=true;error.value='';pendingCancel.value=operation;authStorage.setItem('pending-receipt-cancel',JSON.stringify(operation));try{const {id,...body}=operation;await props.api('/acquisitions/'+id+'/cancel','POST',body);authStorage.removeItem('pending-receipt-cancel');pendingCancel.value=null;cancelDialog.value?.close();cancelDraft.value=null;}catch(e){if((e as any).status>=400&&(e as any).status<500){authStorage.removeItem('pending-receipt-cancel');pendingCancel.value=null;}error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}if(!error.value)await load();}
async function history(id:number){try{changes.value=await props.api('/acquisitions/'+id+'/history');await nextTick();historyDialog.value?.showModal();}catch(e){error.value=String(e);}}
onMounted(()=>{try{pendingCancel.value=JSON.parse(authStorage.getItem('pending-receipt-cancel')||'null');}catch{}load();});
</script>
<template>
<section class="acquisitions-page">
 <div class="page-heading"><div><div class="eyebrow">УЧЁТ ФОНДА</div><h1>Поступления</h1><p>Все зарегистрированные партии книг и других документов.</p></div><button :disabled="busy" @click="load()">Обновить список</button></div>
 <AcquisitionCreate v-if="canEdit" ref="creator" :api="api" @created="load(0)" />
 <div v-if="pendingCancel&&canCancel" class="pending-note"><p>Не получено подтверждение отмены. Повтор не создаст другую операцию.</p><button :disabled="busy" @click="cancelReceipt(pendingCancel)">Проверить отмену</button></div>
 <p v-if="error" role="alert" class="inline-error">{{error}}</p>
 <div class="card holdings" :aria-busy="busy">
  <p><strong>Всего поступлений: {{total}}</strong></p>
  <p v-if="busy" role="status">Загрузка поступлений…</p>
  <article v-for="r in receipts" :key="r.id" class="receipt-card">
   <h2>Поступление №{{r.id}} · {{r.received_on}}</h2>
   <p><strong>{{r.status==='cancelled'?'Отменено · исключено из действующих итогов':'Зарегистрировано'}}</strong> · Версия {{r.version}}</p><div class="record-actions"><button v-if="r.status==='posted'&&canEdit" :disabled="busy||!!pendingCancel" @click="creator?.openEdit(r.id)">Изменить поступление</button><button v-if="r.status==='posted'&&canCancel" class="danger-link" :disabled="busy||!!pendingCancel" @click="openCancel(r)">Удалить поступление</button><button @click="history(r.id)">История изменений</button></div>
   <p>{{r.source}} · Накладная: {{r.invoice||'не указана'}}</p><p v-if="r.note">{{r.note}}</p>
   <div class="table-wrap"><table><thead><tr><th>Документ</th><th>Количество</th><th>Цена одного экземпляра</th><th>Сумма</th><th>Сигла при поступлении</th></tr></thead>
    <tbody><tr v-for="line in r.lines" :key="line.id"><td>{{line.title}} <small class="block">Запись №{{line.record_id}}</small></td><td>{{line.quantity}}</td><td>{{line.unit_price===null?'Не указана':line.unit_price+' '+line.currency}}</td><td>{{line.amount===null?'Не определена':line.amount+' '+line.currency}}</td><td>{{line.sigla||'—'}}</td></tr></tbody>
   </table></div>
   <p><strong>Всего в партии: {{r.quantity}} экз.</strong><span v-for="(amount,currency) in r.totals" :key="currency"> · {{amount}} {{currency}}</span><span v-if="r.unpriced_count"> · Без цены: {{r.unpriced_count}} экз.</span></p>
  </article>
  <div v-if="!busy&&!error&&!total" class="empty"><h2>Поступлений пока нет</h2><p>Нажмите «Новое поступление», выберите книги и укажите сведения о партии.</p></div>
  <div class="table-footer"><span>{{total?'Показаны поступления '+(offset+1)+'–'+(offset+receipts.length):'Нет поступлений'}}</span><div><button :disabled="busy||offset===0" @click="load(offset-20)">Предыдущие поступления</button><button :disabled="busy||offset+receipts.length>=total" @click="load(offset+20)">Следующие поступления</button></div></div>
 </div>
</section>
<dialog ref="cancelDialog" class="modal card" aria-labelledby="cancel-receipt-title" @cancel="busy?$event.preventDefault():cancelDraft=null"><form v-if="cancelDraft" @submit.prevent="cancelReceipt(cancelDraft)"><h2 id="cancel-receipt-title">Удалить поступление №{{cancelDraft.id}}?</h2><p>Поступление получит статус «Отменено». Его экземпляры будут исключены из действующего фонда. История и инвентарные номера сохранятся.</p><label>Причина отмены<textarea v-model="cancelDraft.reason" required maxlength="4000" :disabled="busy||!!pendingCancel"></textarea></label><p v-if="error" role="alert">{{error}}</p><div class="modal-actions"><button type="button" :disabled="busy" @click="cancelDialog?.close()">Назад</button><button class="danger-button" :disabled="busy||!!pendingCancel">Подтвердить отмену поступления</button></div></form></dialog>
<dialog ref="historyDialog" class="modal card acquisition-dialog" aria-label="История поступления"><h2>История поступления</h2><p v-if="!changes.length">Исправлений и отмен ещё не было.</p><article v-for="h in changes" :key="h.id"><h3>{{h.action==='cancel'?'Отмена':'Исправление'}} · {{h.created_at}}</h3><p>{{h.reason}}</p><details><summary>До и после</summary><pre>{{JSON.stringify({до:h.before,после:h.after},null,2)}}</pre></details></article><button @click="historyDialog?.close()">Закрыть</button></dialog>
</template>
