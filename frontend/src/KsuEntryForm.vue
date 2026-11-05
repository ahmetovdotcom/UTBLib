<script setup lang="ts">
import {ref,onMounted} from 'vue';
const props=defineProps<{entry:any,api:(path:string,method?:string,body?:unknown)=>Promise<any>}>();
const emit=defineEmits<{saved:[entry:any],close:[]}>();
const dialog=ref<HTMLDialogElement|null>(null),busy=ref(false),error=ref('');
const draft=ref({...props.entry,request_key:crypto.randomUUID(),reason:''});
async function save(){if(busy.value)return;busy.value=true;error.value='';try{
 const d=draft.value;const fields={number:Number(d.number),year:Number(d.year),registered_on:d.registered_on,document_on:d.document_on||null,source:d.source,invoice:d.invoice,note:d.note};
 const result=await props.api(d.id?'/ksu/entries/'+d.id:'/ksu/entries',d.id?'PUT':'POST',d.id?{...fields,version:d.version,reason:d.reason}:{...fields,request_key:d.request_key});emit('saved',result);
}catch(e){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}}
onMounted(()=>dialog.value?.showModal());
</script>
<template>
<dialog ref="dialog" class="modal card acquisition-dialog" aria-labelledby="ksu-entry-title" @cancel="busy?$event.preventDefault():emit('close')">
 <form @submit.prevent="save"><h2 id="ksu-entry-title">{{draft.id?'Изменить КСУ':'Создать КСУ'}}</h2>
 <p>Номер КСУ: <strong>{{draft.number||'…'}}/{{draft.year}}</strong>. Количество, суммы и распределение заполняются по экземплярам и карточкам книг.</p>
 <fieldset :disabled="busy" class="plain-fieldset acquisition-grid">
  <label>Номер<input v-model.number="draft.number" type="number" min="1" max="2147483647" step="1" required></label>
  <label>Год<input v-model.number="draft.year" type="number" min="1900" max="9999" step="1" required></label>
  <label>Дата регистрации КСУ<input v-model="draft.registered_on" type="date" required></label>
  <label>Источник поступления<input v-model="draft.source" maxlength="255"></label>
  <label>Накладная / документ<input v-model="draft.invoice" maxlength="255"></label>
  <label>Дата документа<input v-model="draft.document_on" type="date"></label>
  <label>Примечание<textarea v-model="draft.note" maxlength="4000"></textarea></label>
  <label v-if="draft.id">Причина изменения<textarea v-model="draft.reason" maxlength="4000" required></textarea></label>
 </fieldset>
 <p v-if="error" role="alert" class="inline-error">{{error}}</p>
 <div class="modal-actions"><button type="button" :disabled="busy" @click="emit('close')">Отмена</button><button class="primary" :disabled="busy">{{draft.id?'Сохранить КСУ':'Создать КСУ'}}</button></div></form>
</dialog>
</template>
