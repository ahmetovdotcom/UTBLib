<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref} from 'vue';
import type {MF} from './catalog';
import {photoValues,preparePhoto,canSelectPhotoField,type PhotoSelection,type PhotoUsage} from './bookPhotos';
import PhotoUsagePanel from './PhotoUsage.vue';
import {phoneReceiver,type BookPhoto} from './phonePhotos';
const props=defineProps<{api:(path:string,method?:string,body?:unknown)=>Promise<any>,fields:MF[],typeId:number,recordId?:number}>();
const emit=defineEmits<{insert:[selections:PhotoSelection[]]}>();
const dialog=ref<HTMLDialogElement>(),picker=ref<HTMLInputElement>(),busy=ref(false),loading=ref(false);
const enabled=ref(false),error=ref(''),photos=ref<BookPhoto[]>([]);
const rows=ref<PhotoSelection[]>([]),warnings=ref<string[]>([]),searched=ref(false);
const usage=ref<PhotoUsage|null>(null);
const attempted=ref(false),noRequest=ref(false);
const selectedCount=computed(()=>rows.value.filter(r=>r.selected).length);
const selectedValid=computed(()=>rows.value.filter(r=>r.selected).every(r=>r.row.values.some(v=>v.trim())));
let generation=0;
const receiver=phoneReceiver(props.api,()=>{
 const title=photoValues(props.fields,{tag:'245',code:'a'})[0];
 return (props.recordId?'Запись № '+props.recordId+' · ':'Новая запись · ')+(title||'Без заглавия');
},(received,ids)=>{
 const before=photos.value.map(p=>p.remoteId||p.url).join('|');
 const retained=photos.value.filter(p=>!p.remoteId||ids.has(p.remoteId));
 const known=new Set(retained.map(p=>p.remoteId));
 photos.value=[...retained,...received.filter(p=>!known.has(p.remoteId))];
 if(before!==photos.value.map(p=>p.remoteId||p.url).join('|'))resetResults();
});
const {status:phoneStatus,error:phoneError,connecting,session:phoneSession}=receiver;
const localAddress=['localhost','127.0.0.1','[::1]'].includes(location.hostname);
onMounted(()=>{void receiver.resume();});
onUnmounted(()=>{generation++;receiver.dispose();photos.value=[];});
function resetResults(){rows.value=[];warnings.value=[];searched.value=false;usage.value=null;attempted.value=false;noRequest.value=false;}
async function clear(){if(busy.value)return;try{await receiver.restart();generation++;photos.value=[];resetResults();error.value='';if(picker.value)picker.value.value='';}catch(e){error.value=String(e);}}
async function open(){
 error.value='';enabled.value=false;loading.value=true;dialog.value?.showModal();const token=generation;
 try{const data=await props.api('/book-photos/config');if(token===generation)enabled.value=data.enabled;}
 catch(e){if(token===generation)error.value=e instanceof Error?e.message:String(e);}
 finally{if(token===generation)loading.value=false;}
}
async function addPhotos(event:Event){
 const input=event.target as HTMLInputElement,files=Array.from(input.files||[]);input.value='';
 if(!files.length||busy.value)return;
 if(photos.value.length+files.length>6){error.value='Можно загрузить до 6 фотографий одной книги.';return;}
 error.value='';busy.value=true;const token=generation;
 try{
  const added=[];for(const file of files)added.push({name:file.name,url:await preparePhoto(file)});
  if(token===generation){photos.value.push(...added);resetResults();}
 }catch(e){if(token===generation)error.value=e instanceof Error?e.message:'Не удалось открыть фотографию.';}
 finally{if(token===generation)busy.value=false;}
}
async function removePhoto(index:number){const photo=photos.value[index];try{if(photo.remoteId)await receiver.remove(photo.remoteId);photos.value=photos.value.filter(p=>p!==photo);resetResults();error.value='';}catch(e){error.value=String(e);}}
async function disconnect(){try{await receiver.disconnect();}catch(e){error.value=String(e);}}
async function analyze(){
 if(busy.value||!photos.value.length||photos.value.length>6)return;
 busy.value=true;error.value='';resetResults();const token=generation;
 try{
  await receiver.gate(false);
  if(!photos.value.length||photos.value.length>6)throw Error('Выберите от 1 до 6 фотографий одной книги.');
  attempted.value=true;
  const data=await props.api('/book-photos/analyze','POST',{type_id:props.typeId,images:photos.value.map(p=>p.url)});
  if(token!==generation)return;
  usage.value=data.usage??null;
  noRequest.value=data.request_sent===false;
  rows.value=data.fields.map((row:any)=>({row,selected:false,mode:row.repeatable&&photoValues(props.fields,row).length?'append':'replace'}));
  warnings.value=data.warnings;searched.value=true;
 }catch(e){if(token===generation){
  error.value=e instanceof Error?e.message:String(e);
  if(e&&typeof e==='object'&&'usage' in e)usage.value=(e as {usage?:PhotoUsage}).usage??null;
 }}
 finally{if(token===generation){busy.value=false;try{await receiver.gate(true);}catch(e){error.value=String(e);}}}
}
function selectEmpty(){for(const item of rows.value)item.selected=canSelectPhotoField(props.fields,item.row);}
function insert(){if(!selectedCount.value||!selectedValid.value)return;emit('insert',rows.value);dialog.value?.close();}
</script>
<template>
<button type="button" @click="open">Заполнить по фото{{photos.length?' ('+photos.length+')':''}}</button>
<span v-if="phoneStatus?.paired" class="phone-summary">Телефон подключён · {{photos.length}} фото</span>
<dialog ref="dialog" class="book-photos-dialog" aria-labelledby="book-photos-title" @cancel="busy&&$event.preventDefault()">
 <header><div><h2 id="book-photos-title">Описание книги по фотографиям</h2><p>Загрузите снимки одного издания, проверьте результат и выберите поля для вставки.</p></div><button type="button" :disabled="busy" aria-label="Закрыть распознавание" @click="dialog?.close()">✕</button></header>
 <p v-if="loading" role="status">Проверяем подключение…</p>
 <p v-else-if="!enabled&&!error" class="photo-notice" role="status">Распознавание пока не подключено. Администратору нужно добавить ключ OpenAI в настройки сервера.</p>
 <p v-if="error" class="photo-error" role="alert">{{error}}</p>
 <section class="photo-upload">
  <h3>1. Фотографии книги</h3>
  <p>Лучше всего подходят обложка, титульный лист и его оборот с ISBN, годом и издательством. До 6 фото JPG, PNG или WebP; до 15 МБ каждое.</p>
  <div class="phone-connect">
   <div><strong>Фотографии с телефона</strong><p>Подключите телефон один раз и снимайте книги по очереди. Фото попадут в текущую открытую карточку.</p></div>
   <button v-if="!phoneSession||!phoneStatus" type="button" :disabled="busy||connecting" @click="receiver.connect">{{connecting?'Подключаем…':'Подключить телефон по QR-коду'}}</button>
   <template v-if="phoneSession&&phoneStatus">
    <div v-if="!phoneStatus.paired&&phoneSession.qr" class="phone-qr"><img :src="phoneSession.qr" alt="QR-код для подключения телефона"><div><strong>Отсканируйте камерой телефона</strong><p>QR-код действует 10 минут. Подключение — до 8 часов.</p><a :href="phoneSession.link" target="_blank" rel="noreferrer">Открыть страницу подключения</a></div></div>
    <p v-else-if="phoneStatus.paired" class="photo-matched" role="status">{{phoneStatus.phone_online?'Телефон на связи':'Телефон подключён. Откройте на нём страницу съёмки.'}} · {{phoneStatus.label}}</p>
    <button v-else type="button" @click="receiver.connect">Показать новый QR-код</button>
    <button type="button" :disabled="busy" @click="disconnect">Отключить телефон</button>
   </template>
   <p v-if="localAddress" class="photo-notice">Адрес localhost доступен только этому компьютеру. Для съёмки телефоном откройте каталог по сетевому адресу, доступному обоим устройствам, например libstaff.kaztbu.edu.kz.</p>
   <p v-if="phoneError" class="photo-error" role="alert">{{phoneError}}</p>
  </div>
  <label class="manual-upload">Или загрузите фотографии с компьютера</label>
  <input ref="picker" type="file" accept="image/jpeg,image/png,image/webp" multiple :disabled="busy||loading||!enabled" aria-label="Выбрать фотографии книги" @change="addPhotos">
  <div class="photo-thumbnails"><figure v-for="(photo,i) in photos" :key="photo.remoteId||photo.url+'-'+i"><img :src="photo.url" :alt="'Фото '+(i+1)+': '+photo.name"><figcaption>Фото {{i+1}} · {{photo.name}}</figcaption><button type="button" :disabled="busy" :aria-label="'Удалить фото '+(i+1)" @click="removePhoto(i)">Убрать</button></figure></div>
  <p v-if="photos.length>6" class="photo-notice" role="alert">Получено больше 6 фото с телефона и компьютера. Уберите лишние перед распознаванием.</p>
  <button v-if="photos.length" type="button" :disabled="busy" @click="clear">Очистить комплект фотографий</button>
  <p class="muted">По нажатию «Распознать» фотографии отправятся в OpenAI. Запрос оплачивается с баланса API. Для подбора значений также передаются справочники полей этого типа документа. Снимки с телефона временно хранятся до смены книги или завершения сессии. В каталог они не сохраняются.</p>
  <button type="button" class="primary" :disabled="busy||loading||!enabled||!photos.length||photos.length>6" @click="analyze">{{busy?'Обрабатываем фотографии…':'Распознать'}}</button>
  <p v-if="busy" role="status">Подождите: обработка может занять до двух минут. Карточка пока не изменяется.</p>
 </section>
 <PhotoUsagePanel v-if="usage" :usage="usage"/>
 <p v-else-if="noRequest" class="muted">Запрос в OpenAI не отправлялся — расхода на распознавание нет.</p>
 <p v-else-if="attempted&&!busy" class="muted">Счётчики расхода не получены. Если запрос уже был отправлен, обработка могла быть оплачена. Проверьте расход в OpenAI Usage.</p>
 <section v-if="searched" class="photo-results">
  <h3>2. Проверьте и выберите поля</h3>
  <p v-for="(warning,i) in warnings" :key="i" class="photo-notice" role="status">{{warning}}</p>
  <p v-if="!rows.length">Сведения для полей этого рабочего листа не распознаны. Попробуйте более чёткие фотографии титульного листа и страницы с выходными данными.</p>
  <template v-else>
   <p>Ничего не выбрано автоматически. Значения можно исправить здесь. Рекомендации по тематике книги (включая факультет и специальность) проверьте отдельно. Для заполненных полей выберите замену или добавление.</p>
   <div class="photo-tools"><button type="button" @click="selectEmpty">Выбрать прочитанные данные для пустых полей</button><button type="button" @click="rows.forEach(r=>r.selected=false)">Снять выбор</button><span>Выбрано полей: {{selectedCount}}</span></div>
   <div class="photo-table-wrap"><table><thead><tr><th>Вставить</th><th>Поле / сейчас в карточке</th><th>Предложение ИИ</th></tr></thead><tbody>
    <tr v-for="item in rows" :key="item.row.key" :class="{'photo-selected':item.selected}">
     <td><input type="checkbox" v-model="item.selected" :aria-label="'Вставить '+item.row.label"></td>
     <td><strong>{{item.row.label}}</strong><div class="muted">{{item.row.key}}</div><p v-if="!photoValues(fields,item.row).length" class="muted">Не заполнено</p><p v-for="(value,i) in photoValues(fields,item.row)" :key="i" class="photo-existing">{{value}}</p>
      <label v-if="photoValues(fields,item.row).length&&item.row.repeatable">Действие<select v-model="item.mode"><option value="append">Добавить к текущим значениям</option><option value="replace">Заменить значения этого подполя</option></select></label>
      <p v-else-if="photoValues(fields,item.row).length" class="photo-replace">При выборе — заменить текущее значение</p>
     </td>
     <td><label v-for="(_,i) in item.row.values" :key="i" class="photo-value"><span class="sr-only">{{item.row.label}}: значение {{i+1}}</span><textarea v-model="item.row.values[i]" :rows="item.row.values[i].length>120?4:2" maxlength="4000"></textarea></label>
      <p v-if="item.row.basis==='inferred'" class="photo-notice">Рекомендация по содержанию — подтвердите соответствие книге</p>
      <p v-else class="muted">Прочитано с фотографии</p>
      <p v-if="item.row.vocabulary_status==='matched'" class="photo-matched">Значение из справочника</p>
      <span v-if="item.row.confidence==='uncertain'" class="photo-notice">ИИ сомневается — проверьте предложение</span>
      <p class="muted">Фото {{item.row.image_numbers.join(', ')}} · {{item.row.evidence}}</p>
      <p v-for="(warning,i) in item.row.warnings" :key="i" class="photo-notice">{{warning}}</p>
     </td>
    </tr>
   </tbody></table></div>
   <p>Изменятся только отмеченные подполя. Запись сохранится после нажатия «Сохранить запись» в карточке.</p>
   <button type="button" class="primary" :disabled="!selectedCount||!selectedValid||busy" @click="insert">Вставить выбранные поля ({{selectedCount}})</button>
  </template>
 </section>
</dialog>
</template>
<style scoped>
.phone-summary{font-size:13px;color:#146a58}.phone-connect{background:#f4f8fb;border:1px solid #dce5ee;border-radius:14px;padding:16px;margin:18px 0}.phone-qr{display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin-bottom:16px}.phone-qr img{width:210px;height:210px;max-width:100%}.phone-qr div{flex:1;min-width:180px}.manual-upload{display:block;font-weight:600;margin:12px 0}.book-photos-dialog{width:min(1080px,95vw);max-height:90vh;overflow:auto;border:1px solid var(--border,#dce4ee);border-radius:20px;padding:28px;color:#203247;background:white}
.book-photos-dialog::backdrop{background:#10233988}
header,.photo-tools{display:flex;align-items:start;justify-content:space-between;gap:14px}
h2{margin:0}h3{margin-top:0}.photo-upload,.photo-results{border-top:1px solid #e0e7ef;margin-top:22px;padding-top:22px}
.photo-thumbnails{display:flex;gap:14px;flex-wrap:wrap;margin-top:18px}
figure{margin:0;width:140px;background:#f4f7fb;padding:10px;border-radius:12px}
figure img{width:120px;height:145px;object-fit:contain;background:white}
figcaption{font-size:12px;overflow-wrap:anywhere;margin:8px 0}
.photo-notice{color:#805319;background:#fff8e6;padding:8px 10px;border-radius:7px;font-size:14px}
.photo-error{color:#9c2935;background:#fff0f0;padding:12px;border-radius:8px}
.photo-tools{align-items:center;justify-content:start;flex-wrap:wrap;margin:16px 0}
.photo-table-wrap{overflow:auto}table{width:100%;table-layout:fixed}
th:first-child{width:75px}th:nth-child(2){width:32%}td{vertical-align:top;overflow-wrap:anywhere}
.photo-matched{color:#146a58;font-size:14px}.photo-selected{background:#f2faf8}.photo-value textarea{width:100%;box-sizing:border-box}
.photo-existing{white-space:pre-wrap;font-size:14px}.photo-replace{font-size:13px;color:#805319}
.sr-only{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0)}
@media(max-width:650px){.book-photos-dialog{padding:16px}.photo-table-wrap table{min-width:600px}}
</style>
