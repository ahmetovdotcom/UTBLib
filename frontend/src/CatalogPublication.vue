<script setup lang="ts">
import {ref} from 'vue';
import type {RecordData} from './catalog';
const props=defineProps<{record:RecordData,csrf:string,disabled?:boolean,readonly?:boolean}>();
const emit=defineEmits<{loading:[boolean]}>();
const uploading=ref(false),error=ref(''),progress=ref(0);
const MAX_PDF_BYTES=1024*1024*1024;
let activeUpload:XMLHttpRequest|null=null;
async function upload(event:Event){
 const input=event.target as HTMLInputElement,file=input.files?.[0];input.value='';if(!file)return;
 error.value='';
 if(!file.name.toLowerCase().endsWith('.pdf')||file.size>MAX_PDF_BYTES){error.value='Выберите PDF размером до 1 ГБ (1024 МБ).';return;}
 uploading.value=true;progress.value=0;emit('loading',true);
 try{
  const data=await new Promise<{token:string,name:string,size:number,pages:number}>((resolve,reject)=>{
   const request=new XMLHttpRequest();activeUpload=request;
   request.open('POST','/api/catalog-files?filename='+encodeURIComponent(file.name));
   request.setRequestHeader('Content-Type','application/pdf');request.setRequestHeader('X-CSRF-Token',props.csrf);
   request.upload.onprogress=e=>{if(e.lengthComputable)progress.value=Math.min(100,Math.round(e.loaded/e.total*100));};
   request.upload.onload=()=>{progress.value=100;};
   request.onload=()=>{
    let result;try{result=JSON.parse(request.responseText);}catch{reject(Error(request.status===413?'Размер PDF не должен превышать 1 ГБ (1024 МБ).':'Не удалось загрузить PDF. Повторите загрузку.'));return;}
    if(request.status<200||request.status>=300){reject(Error(typeof result.detail==='string'?result.detail:'Не удалось загрузить PDF. Повторите загрузку.'));return;}
    resolve(result);
   };
   request.onerror=()=>reject(Error('Соединение прервано. Повторите загрузку PDF.'));
   request.onabort=()=>reject(Error('Загрузка отменена.'));
   request.send(file);
  });
  props.record.digital_upload=data.token;props.record.electronic_file={name:data.name,size:data.size,pages:data.pages};
 }catch(e){error.value=e instanceof Error?e.message:String(e);}finally{activeUpload=null;uploading.value=false;emit('loading',false);}
}
function remove(){props.record.digital_upload=null;props.record.electronic_file=null;props.record.use_first_page_cover=false;error.value='';}
</script>
<template>
<section class="publication card">
 <label class="check"><input v-model="record.is_faculty_work" type="checkbox" :disabled="readonly||disabled||uploading"> Труды ППС</label>
 <template v-if="record.is_faculty_work||record.electronic_file">
  <p class="hint">Отмеченная запись появится в разделе «Труды ППС». Краткое описание доступно всем; полная карточка и чтение книги — после входа.</p>
  <div v-if="record.electronic_file" class="file"><strong>{{record.electronic_file.name}}</strong><span>{{record.electronic_file.pages}} стр. · {{(record.electronic_file.size/1024/1024).toFixed(1)}} МБ</span><button v-if="!readonly" type="button" class="danger-link" :disabled="disabled||uploading" @click="remove">Убрать файл</button></div>
  <label v-if="!readonly" class="upload">{{record.electronic_file?'Заменить электронную книгу (PDF, до 1 ГБ)':'Загрузить электронную книгу (PDF, до 1 ГБ)'}}<input type="file" accept="application/pdf,.pdf" :disabled="disabled||uploading" @change="upload"></label>
  <div v-if="uploading" class="file" role="status"><span>{{progress<100?`Передача PDF — ${progress}%`:'Проверка PDF и подготовка обложки…'}}</span><button type="button" @click="activeUpload?.abort()">Отменить загрузку</button></div>
  <label class="check"><input v-model="record.use_first_page_cover" type="checkbox" :disabled="readonly||disabled||uploading||!record.electronic_file"> Взять первую страницу как обложку</label>
  <p v-if="!readonly" class="hint">Изменения появятся на сайте после нажатия «Сохранить запись». Загрузка файла необязательна.</p>
 </template>
 <p v-if="error" role="alert" class="error">{{error}}</p>
</section>
</template>
<style scoped>
.publication{margin:16px 0;padding:18px}.check{display:flex;flex-direction:row;justify-content:flex-start;gap:9px;align-items:center;margin:12px 0}.check input{width:auto}.hint{color:var(--muted,#64748b);font-size:13px;max-width:850px}.upload{display:grid;gap:8px;font-size:14px;margin:14px 0}.file{display:flex;gap:14px;align-items:center;flex-wrap:wrap}.file strong{overflow-wrap:anywhere}.file span{color:#64748b}.error{color:#b91c1c}
</style>
