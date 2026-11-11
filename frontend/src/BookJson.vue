<script setup lang="ts">
import {nextTick,onUnmounted,ref} from 'vue';
import type {MF} from './catalog';
import {photoValues,type PhotoSelection} from './bookPhotos';
import BookPhotoResults from './BookPhotoResults.vue';

const props=defineProps<{api:(path:string,method?:string,body?:unknown)=>Promise<any>;fields:MF[];typeId:number;disabled?:boolean}>();
const emit=defineEmits<{insert:[selections:PhotoSelection[]]}>();
const dialog=ref<HTMLDialogElement>(),promptArea=ref<HTMLTextAreaElement>();
const loading=ref(false),busy=ref(false),prompt=ref(''),text=ref(''),error=ref(''),copyStatus=ref('');
const showPrompt=ref(false),promptWarnings=ref<string[]>([]),warnings=ref<string[]>([]);
const rows=ref<PhotoSelection[]>([]),checked=ref(false);
let generation=0;
onUnmounted(()=>generation++);

function resetResults(){rows.value=[];warnings.value=[];checked.value=false;error.value='';}
async function loadPrompt(){
 const token=++generation;loading.value=true;error.value='';prompt.value='';copyStatus.value='';promptWarnings.value=[];
 try{
  const data=await props.api('/book-photos/prompt?type_id='+props.typeId);
  if(token===generation){prompt.value=data.prompt;promptWarnings.value=data.warnings;}
 }catch(e){if(token===generation)error.value=e instanceof Error?e.message:String(e);}
 finally{if(token===generation)loading.value=false;}
}
function open(){if(props.disabled)return;resetResults();dialog.value?.showModal();void loadPrompt();}
async function copyPrompt(){
 copyStatus.value='';const token=generation;
 try{
  if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(prompt.value);if(token===generation)copyStatus.value='Задание скопировано. Вставьте его в чат ИИ вместе с фотографиями книги.';return;}
 }catch{/* Use the visible, selectable prompt on HTTP or when clipboard access is denied. */}
 if(token!==generation)return;
 showPrompt.value=true;await nextTick();promptArea.value?.focus();promptArea.value?.select();
 let copied=false;try{copied=document.execCommand('copy');}catch{/* Manual copy below. */}
 copyStatus.value=copied?'Задание скопировано. Вставьте его в чат ИИ вместе с фотографиями книги.':'Текст задания выделен. Нажмите Ctrl+C или ⌘C либо выберите «Копировать» на телефоне.';
}
async function check(){
 if(busy.value||loading.value||!text.value.trim())return;
 resetResults();busy.value=true;const token=generation;
 try{
  const data=await props.api('/book-photos/import-json','POST',{type_id:props.typeId,text:text.value});
  if(token!==generation)return;
  rows.value=data.fields.map((row:any)=>({row,selected:false,mode:row.repeatable&&photoValues(props.fields,row).length?'append':'replace'}));
  warnings.value=data.warnings;checked.value=true;
 }catch(e){if(token===generation)error.value=e instanceof Error?e.message:String(e);}
 finally{if(token===generation)busy.value=false;}
}
function insert(selections:PhotoSelection[]){dialog.value?.close();emit('insert',selections);text.value='';resetResults();}
</script>
<template>
 <button type="button" :disabled="disabled" @click="open">Вставить JSON</button>
 <dialog ref="dialog" class="book-json-dialog" aria-labelledby="book-json-title" @cancel="busy&&$event.preventDefault()">
  <header><div><h2 id="book-json-title">Описание книги из JSON</h2><p>Получите ответ в DeepSeek, Gemini или другом ИИ и выберите поля для карточки. Ключ API не нужен.</p></div><button type="button" :disabled="busy" aria-label="Закрыть импорт JSON" @click="dialog?.close()">✕</button></header>
  <section>
   <h3>1. Скопируйте задание для ИИ</h3>
   <p>Вставьте задание в новый чат и приложите до 6 фотографий одной книги: титульный лист, оборот и при необходимости оглавление. Ответ должен быть в формате JSON.</p>
   <p class="muted">Задание содержит поля и справочники выбранного типа документа. Фотографии вы отправляете в выбранный сервис самостоятельно.</p>
   <p v-if="loading" role="status">Готовим задание…</p>
   <div class="json-actions"><button type="button" :disabled="loading||busy||!prompt" @click="copyPrompt">Скопировать промпт для ИИ</button><button v-if="prompt" type="button" :aria-expanded="showPrompt" aria-controls="book-json-prompt" @click="showPrompt=!showPrompt">{{showPrompt?'Скрыть задание':'Показать задание'}}</button><button v-if="!loading&&!prompt" type="button" :disabled="busy" @click="loadPrompt">Повторить загрузку задания</button></div>
   <p v-if="copyStatus" role="status">{{copyStatus}}</p>
   <textarea v-if="showPrompt&&prompt" id="book-json-prompt" ref="promptArea" :value="prompt" readonly rows="8" aria-label="Промпт для ИИ"></textarea>
   <p v-for="(warning,i) in promptWarnings" :key="i" class="notice">{{warning}}</p>
  </section>
  <section>
   <h3>2. Вставьте ответ ИИ</h3>
   <label for="book-json-answer">JSON-ответ</label>
   <textarea id="book-json-answer" v-model="text" rows="8" :disabled="busy" :maxlength="256*1024" spellcheck="false" placeholder="Вставьте сюда целиком JSON, который вернул ИИ" @input="resetResults"></textarea>
   <p class="muted">Можно скопировать блок вместе с обрамлением ```json. Проверка не сохраняет запись и не отправляет запрос в ИИ.</p>
   <button type="button" class="primary" :disabled="busy||loading||!text.trim()" @click="check">{{busy?'Проверяем ответ…':'Проверить JSON'}}</button>
   <p v-if="error" role="alert" class="error">{{error}}</p>
  </section>
  <BookPhotoResults v-if="checked" :fields="fields" :rows="rows" :warnings="warnings" :disabled="busy" heading="3. Проверьте и выберите поля" empty-message="В ответе нет подходящих значений для этого рабочего листа. Проверьте предупреждения или попросите ИИ обработать более чёткие фотографии." @insert="insert"/>
 </dialog>
</template>
<style scoped>
.book-json-dialog{width:min(1080px,95vw);max-height:90vh;max-height:90dvh;overflow:auto;box-sizing:border-box;border:1px solid var(--border,#dce4ee);border-radius:20px;padding:28px;color:#203247;background:white}
.book-json-dialog::backdrop{background:#10233988}header{display:flex;align-items:start;justify-content:space-between;gap:14px}h2{margin:0}h3{margin-top:0}
section{border-top:1px solid #e0e7ef;margin-top:22px;padding-top:22px}.json-actions{display:flex;gap:12px;flex-wrap:wrap}label{display:block;font-weight:600;margin-bottom:8px}
textarea{display:block;width:100%;box-sizing:border-box;margin:14px 0;font-family:monospace;font-size:14px;white-space:pre-wrap;overflow-wrap:anywhere}
.notice{color:#805319;background:#fff8e6;padding:8px 10px;border-radius:7px}.error{color:#9c2935;background:#fff0f0;padding:12px;border-radius:8px}
@media(max-width:650px){.book-json-dialog{padding:16px}}
</style>
