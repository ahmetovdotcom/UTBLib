<script setup lang="ts">
import {computed,useId} from 'vue';
import VocabularyInput from './VocabularyInput.vue';
const props=defineProps<{draft:any,entries:any[],fieldOptions:{sigla:string[],source:string[]},creating?:boolean}>();
const inputId=useId();
const siglas=computed(()=>props.fieldOptions.sigla.map((value,id)=>({id,value,label:''})));
const sources=computed(()=>props.fieldOptions.source.map((value,id)=>({id,value,label:''})));
const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Almaty',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
</script>
<template>
<label>Инвентарный номер<input v-model="draft.inventory_number" maxlength="100" :required="!creating" :placeholder="creating?'Автоматически, если не указан':''"></label>
<label>Штрихкод<input v-model="draft.barcode" maxlength="100" :required="!creating" :placeholder="creating?'Автоматически, если не указан':''"></label>
<label>КСУ<select v-model="draft.ksu_entry_id"><option :value="null">Без КСУ</option><option v-for="e in entries" :key="e.id" :value="e.id">{{e.label}} · {{e.source||'Источник не указан'}}{{e.invoice?' · '+e.invoice:''}}</option></select><small>КСУ создаётся в разделе «КСУ». Экземпляр включается в её отчёты после сохранения.</small></label>
<div class="copy-choice-field"><label :for="inputId+'-sigla'">Сигла хранения</label><VocabularyInput v-model="draft.sigla" :input-id="inputId+'-sigla'" ariaLabel="Сигла хранения" :maxlength="255" :entries="siglas" :settings="{auto_add:true}" within-dialog placeholder="Выберите из справочника или введите новое" /></div>
<label>Цена приобретения<input v-model="draft.unit_price" type="number" min="0" max="999999999999.99" step="0.01" placeholder="Не указана"><small>Пустое поле — цена неизвестна. 0 — безвозмездное поступление.</small></label>
<label>Валюта<input v-model="draft.currency" maxlength="3" pattern="[A-Z]{3}" required list="copy-currencies"><datalist id="copy-currencies"><option value="KZT"/><option value="RUB"/><option value="USD"/><option value="EUR"/></datalist></label>
<label>Дата поступления<input v-model="draft.received_on" type="date"></label>
<div class="copy-choice-field"><label :for="inputId+'-source'">Источник поступления</label><VocabularyInput v-model="draft.source" :input-id="inputId+'-source'" ariaLabel="Источник поступления" :maxlength="255" :entries="sources" :settings="{auto_add:true}" within-dialog placeholder="Выберите из справочника или введите новое" /></div>
<label>Накладная / документ<input v-model="draft.invoice" maxlength="255"></label>
<label>Дата проверки<input v-model="draft.checked_on" type="date" :max="today"><small>Пустая дата — экземпляр не проверен.</small></label>
<label>Примечание<textarea v-model="draft.note" maxlength="4000"></textarea></label>
</template>
<style scoped>
.copy-choice-field{display:flex;flex-direction:column;gap:6px}.copy-choice-field>label{margin:0}
</style>
