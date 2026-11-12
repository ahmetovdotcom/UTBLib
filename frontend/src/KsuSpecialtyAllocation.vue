<script setup lang="ts">
import {renderTask} from './navigation';
import {ref,computed,onMounted} from 'vue';
const props=defineProps<{entryId:number,api:(path:string,method?:string,body?:unknown)=>Promise<any>}>();
const emit=defineEmits<{close:[]}>();
const dialog=ref<HTMLDialogElement>(),data=ref<any>(null),busy=ref(false),error=ref(''),query=ref('');
const items=computed(()=>data.value?.items.filter((r:any)=>(r.title+' '+r.record_id).toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase()))||[]);
async function load(){busy.value=true;error.value='';try{data.value=await props.api(`/ksu/entries/${props.entryId}/specialties`);}catch(e){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}}
onMounted(()=>{dialog.value?.showModal();renderTask(load());});
</script>
<template>
<dialog ref="dialog" class="card allocation-dialog" aria-labelledby="allocation-title" @cancel.prevent="!busy&&emit('close')">
 <header><h2 id="allocation-title">Распределение КСУ {{data?.entry.label||''}}</h2><button :disabled="busy" @click="emit('close')" aria-label="Закрыть распределение">✕</button></header>
 <p>Специальности берутся из карточки каталога. Выбрать или изменить основную можно только при заполнении карточки книги. Здесь отображается результат: дополнительные специальности не увеличивают количество и сумму.</p>
 <p v-if="error" role="alert" class="inline-error">{{error}}</p>
  <div class="allocation-search"><input v-model="query" aria-label="Поиск книги в распределении" placeholder="Название или номер записи"><button :disabled="busy" @click="load">Обновить список</button></div>
  <div class="table-wrap"><table class="ksu-grid"><thead><tr><th>Книга</th><th>Экз.</th><th>Основная специальность</th><th>Дополнительные специальности</th></tr></thead><tbody><tr v-for="item in items" :key="item.record_id"><td>{{item.title}}<small>Запись №{{item.record_id}}</small></td><td>{{item.copies}}</td><td>{{item.primary_specialty||'Основная специальность не выбрана'}}</td><td>{{item.additional_specialties.join('; ')||'—'}}</td></tr></tbody></table></div>
  <p v-if="!busy&&!items.length">Книги не найдены.</p>
 <footer><button :disabled="busy" @click="emit('close')">Закрыть</button></footer>
</dialog>
</template>
<style scoped>
.allocation-dialog{width:min(1050px,94vw);max-height:90vh;padding:24px;border:1px solid #d5e2ec;overflow:auto}.allocation-dialog::backdrop{background:#102b4680}.allocation-dialog header{display:flex;justify-content:space-between;gap:16px;align-items:start}.allocation-dialog h2{margin-top:0}.allocation-dialog th,.allocation-dialog td{padding:12px;text-align:left;white-space:normal}.allocation-dialog small{display:block}.allocation-dialog footer{margin-top:20px;text-align:right}.allocation-search{display:flex;gap:12px;margin:16px 0}.allocation-search input{flex:1;min-width:0}
</style>
