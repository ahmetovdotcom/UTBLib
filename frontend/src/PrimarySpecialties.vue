<script setup lang="ts">
import {computed} from 'vue';
import {specialtyChoices,primarySpecialty,type RecordData} from './catalog';
const props=defineProps<{record:RecordData,readonly?:boolean}>();
const emit=defineEmits<{select:[value:string]}>();
const choices=computed(()=>specialtyChoices(props.record));
const selected=computed(()=>primarySpecialty(props.record));
</script>
<template>
<fieldset class="card primary-specialties" :disabled="readonly">
 <legend>Основная специальность для КСУ</legend>
 <p>Выберите одну из специальностей книги. Остальные будут дополнительными и не увеличат количество и сумму в КСУ.</p>
 <label v-for="value in choices" :key="value" :class="{chosen:selected===value}">
  <input type="radio" name="primary-specialty" :value="value" :checked="selected===value" @change="emit('select',value)">
  <span>{{value}}</span><strong>{{selected===value?'Основная':'Дополнительная'}}</strong>
 </label>
 <p v-if="!choices.length">Сначала заполните поле «Специальность» в рабочем листе.</p>
 <p v-else-if="!selected" class="pending-note">Основная специальность пока не выбрана. При включении в КСУ книга попадёт в отдельную колонку.</p>
 <small>Выбор сохраняется вместе с карточкой. Распределение во всех связанных КСУ обновляется автоматически. Дополнительные специальности не увеличивают итог.</small>
</fieldset>
</template>
<style scoped>
.primary-specialties{padding:18px 22px;margin:18px 0;border:1px solid #d5e2ec;min-width:0}.primary-specialties legend{font-weight:700;padding:0 6px}.primary-specialties p{margin:0 0 12px}.primary-specialties label{display:flex;gap:12px;align-items:center;padding:10px;border:1px solid #d5e2ec;border-radius:8px;margin:8px 0}.primary-specialties input{width:auto;flex-shrink:0}.primary-specialties span{flex:1;overflow-wrap:anywhere}.primary-specialties strong{font-size:12px;color:#567080}.primary-specialties .chosen{border-color:#078180;background:#f0fafa}.primary-specialties small{display:block;line-height:1.5;color:#567080}
</style>
