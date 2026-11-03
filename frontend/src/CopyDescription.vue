<script setup lang="ts">
import {nextTick, onUnmounted, ref} from 'vue';
import {descriptionForCopy,type DescriptionSource,type DescriptionApi} from './copyDescription';
const props=defineProps<DescriptionSource & {api:DescriptionApi;label?:string;disabled?:boolean}>();
const busy=ref(false),copied=ref(false),error=ref(''),text=ref('');
const dialog=ref<HTMLDialogElement|null>(null),manual=ref<HTMLTextAreaElement|null>(null);
let timer:ReturnType<typeof setTimeout>|undefined;
onUnmounted(()=>clearTimeout(timer));
function legacyCopy(value:string){
 const area=document.createElement('textarea');const active=document.activeElement as HTMLElement|null;
 area.value=value;area.setAttribute('readonly','');area.style.cssText='position:fixed;left:-9999px;top:0';document.body.append(area);
 try{area.select();return document.execCommand('copy');}catch{return false;}finally{area.remove();active?.focus();}
}
async function copy(){
 if(busy.value||props.disabled)return;busy.value=true;copied.value=false;error.value='';text.value='';clearTimeout(timer);
 const content=descriptionForCopy(props.api,props).then(value=>{text.value=value;return value;});
 // Safari requires clipboard.write during the click, before waiting for the API.
 try{
  let done=false;
  if(navigator.clipboard?.write&&typeof ClipboardItem!=='undefined'){
   const blob=content.then(value=>new Blob([value],{type:'text/plain'}));void blob.catch(()=>{});
   try{await navigator.clipboard.write([new ClipboardItem({'text/plain':blob})]);done=true;}catch{/* Try the browser's other clipboard paths below. */}
  }
  const value=await content;
  if(!done&&navigator.clipboard?.writeText){try{await navigator.clipboard.writeText(value);done=true;}catch{/* HTTP or permission restriction. */}}
  if(!done)done=legacyCopy(value);
  if(done){copied.value=true;timer=setTimeout(()=>copied.value=false,2500);}
  else{await nextTick();dialog.value?.showModal();manual.value?.focus();manual.value?.select();}
 }catch(e){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}
}
</script>
<template>
<div class="copy-description" :class="{'copy-description-full':!!marc}">
 <button type="button" :disabled="busy||disabled" :aria-label="marc?'Копировать библиографическую запись':'Копировать библиографическое описание записи №'+recordId" title="Копировать библиографическое описание" @click="copy">{{busy?'Копирование…':copied?'✓ Скопировано':label||'Копировать'}}</button>
 <span class="sr-only" role="status">{{copied?'Библиографическое описание скопировано':''}}</span>
 <small v-if="error" role="alert">{{error}}</small>
 <dialog ref="dialog" class="modal card" aria-label="Копирование библиографического описания">
  <h2>Библиографическое описание</h2><p>Браузер ограничил автоматическое копирование. Текст выделен: нажмите Ctrl+C или ⌘C.</p>
  <textarea ref="manual" :value="text" readonly aria-label="Библиографическое описание для копирования" rows="8"></textarea>
  <button type="button" @click="dialog?.close()">Закрыть</button>
 </dialog>
</div>
</template>
<style scoped>
.copy-description{display:inline-flex;flex-direction:column;gap:6px;align-items:flex-start}.copy-description>button{white-space:nowrap;font-size:12px;padding:8px 12px;min-height:34px}.copy-description>small{max-width:240px;color:#a23c32;font-size:12px}.copy-description dialog{width:min(700px,94vw);white-space:normal;text-align:left}.copy-description textarea{width:100%;margin:16px 0;line-height:1.6}
.copy-description-full>button{font-size:14px;padding:12px 16px;min-height:44px}
</style>
