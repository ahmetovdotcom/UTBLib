<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue';
import {preparePhoto} from './bookPhotos';
import {newPhotoId,type TransferStatus} from './phonePhotos';
const state=ref<TransferStatus|null>(null),error=ref(''),notice=ref(''),busy=ref(false),starting=ref(true);
const camera=ref<HTMLInputElement>(),gallery=ref<HTMLInputElement>();
let token='',timer:ReturnType<typeof setTimeout>|undefined,dead=false,captureTarget='';
const storageKey='book-photo-phone-token';
const ready=computed(()=>!!state.value?.accepting&&!busy.value&&state.value.photos.length<6);
async function request(path:string,method='GET',body?:unknown,credential=token){
 const response=await fetch('/api/photo-transfer/mobile'+path,{method,credentials:'omit',cache:'no-store',headers:{'Content-Type':'application/json','Authorization':'Bearer '+credential},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await response.json();if(!response.ok)throw Object.assign(Error(data.detail||'Не удалось связаться с компьютером.'),{status:response.status});return data;
}
function persist(value:string){try{value?sessionStorage.setItem(storageKey,value):sessionStorage.removeItem(storageKey);}catch{}}
async function refresh(){
 try{const data=await request('');if(!dead){if(state.value?.target_id!==data.target_id)notice.value='';state.value=data;}}
 catch(e){if(dead)return;error.value=e instanceof Error?e.message:String(e);state.value=null;if((e as any)?.status===401){token='';persist('');}}
 finally{if(!dead&&token)timer=setTimeout(refresh,2000);}
}
onMounted(async()=>{
 const pair=new URLSearchParams(location.hash.slice(1)).get('pair');
 history.replaceState(null,'',location.pathname);
 try{
  if(pair){const data=await request('/pair','POST',undefined,pair);token=data.token;state.value=data;persist(token);}
  else{try{token=sessionStorage.getItem(storageKey)||'';}catch{}if(!token)throw Error('Откройте «Заполнить по фото» на компьютере и отсканируйте QR-код.');}
  await refresh();
 }catch(e){error.value=e instanceof Error?e.message:String(e);}finally{starting.value=false;}
});
onUnmounted(()=>{dead=true;clearTimeout(timer);});
function choose(picker:HTMLInputElement|undefined){if(!ready.value)return;captureTarget=state.value!.target_id;notice.value='';error.value='';picker?.click();}
async function send(event:Event){
 const input=event.target as HTMLInputElement,files=Array.from(input.files||[]);input.value='';
 if(!files.length||busy.value)return;
 const target=captureTarget; // Captured BEFORE the camera/file picker opens, never after it closes.
 if(!target){error.value='Выберите книгу на компьютере и повторите съёмку.';return;}
 if(files.length+(state.value?.photos.length||0)>6){error.value='Для одной книги можно отправить до 6 фотографий.';return;}
 busy.value=true;error.value='';let sent=0;
 try{
  for(const file of files){
   const image=await preparePhoto(file);
   const requestId=newPhotoId();
   const body={target_id:target,label:state.value?.label||'Книга',request_id:requestId,name:file.name.slice(0,120)||'Фото книги',image};
   let data;
   try{data=await request('/photos','POST',body);}catch(e){
    // Retry transport failures once with the SAME id, so an accepted photo is not duplicated.
    if((e as any)?.status)throw e;data=await request('/photos','POST',body);
   }
   sent++;if(!dead)state.value=data;
  }
  notice.value=sent===1?'Фото загружено. Оно появится в карточке на компьютере.':`Загружено фотографий: ${sent}. Они появятся на компьютере.`;
 }catch(e){error.value=(sent?`Загружено ${sent}. `:'')+(e instanceof Error?e.message:String(e));}
 finally{busy.value=false;captureTarget='';}
}
</script>
<template>
<main class="phone-photo-page">
 <header><span class="phone-brand">Библиотека · Фото книги</span><h1>Фотографирование книг</h1><p>Снимайте здесь — проверяйте описание на компьютере.</p></header>
 <p v-if="starting" role="status">Подключаемся к рабочему месту…</p>
 <p v-if="error" class="phone-error" role="alert">{{error}}</p>
 <p v-if="notice" class="phone-success" role="status">{{notice}}</p>
 <section v-if="state" class="phone-card">
  <span class="phone-badge">Телефон подключён</span>
  <p class="muted">Сейчас на компьютере</p><h2>{{state.label||'Карточка ещё не выбрана'}}</h2>
  <p v-if="!state.accepting" role="status">Ожидаем готовности компьютера. Откройте нужную карточку; во время распознавания приём снимков приостановлен.</p>
  <template v-else><p>Обложка → титульный лист → оборот с ISBN и выходными данными.</p><p>Проверьте название перед съёмкой. При переходе к следующей книге комплект обновится автоматически.</p></template>
  <input ref="camera" hidden type="file" accept="image/jpeg,image/png,image/webp" capture="environment" @change="send">
  <input ref="gallery" hidden type="file" accept="image/jpeg,image/png,image/webp" multiple @change="send">
  <button class="primary" :disabled="!ready" @click="choose(camera)">{{busy?'Загружаем…':'Сделать фото'}}</button>
  <button :disabled="!ready" @click="choose(gallery)">Выбрать из галереи</button>
  <p v-if="busy" role="status">Дождитесь подтверждения загрузки, прежде чем закрывать страницу.</p>
  <h3>Снимки этой книги: {{state.photos.length}} / 6</h3>
  <ol v-if="state.photos.length"><li v-for="(photo,i) in state.photos" :key="photo.id">Фото {{i+1}} <span>✓ Загружено</span></li></ol>
  <p v-else class="muted">Снимков пока нет.</p>
  <p class="muted">Посмотреть и удалить снимки, запустить ИИ и выбрать поля можно на компьютере. Фотографии хранятся временно.</p>
 </section>
 <section v-else-if="!starting" class="phone-card"><p>Для подключения нужен QR-код из открытой карточки на компьютере. Подключение действует до 8 часов, пока сотрудник остаётся в системе.</p><button v-if="token" @click="refresh">Проверить соединение</button></section>
 <p class="muted">Оставьте эту страницу открытой для следующих книг. Телефону нужен доступ к сайту библиотеки.</p>
</main>
</template>
<style scoped>
.phone-photo-page{max-width:560px;margin:auto;padding:24px 18px;box-sizing:border-box;color:#18324b}.phone-brand{font-size:14px;font-weight:700;color:#007779}h1{font-size:27px;margin:18px 0 8px}h2{font-size:23px;overflow-wrap:anywhere}p{line-height:1.5}.phone-card{background:white;border:1px solid #dce5ee;border-radius:20px;padding:22px;margin:22px 0;box-shadow:0 4px 15px #17334908}.phone-badge{background:#e5f6ef;color:#146e4c;padding:6px 12px;border-radius:20px;font-size:14px;font-weight:700}button{display:block;width:100%;min-height:50px;margin:12px 0}.phone-photo-page button.primary{background:#062642;border-color:#062642;color:white}.phone-photo-page button.primary:hover{background:#123e5d}.phone-error,.phone-success{padding:14px;border-radius:12px;overflow-wrap:anywhere}.phone-error{background:#fff0f0;color:#9c2935}.phone-success{background:#e9f8ef;color:#146e4c}ol{padding-left:22px}li{padding:8px}li span{color:#146e4c;float:right;font-size:14px}.muted{color:#718198}
</style>
