<script setup lang="ts">
import {ref,nextTick} from 'vue';
const props=defineProps<{api:(path:string,method?:string,body?:any)=>Promise<any>,branches:any[];eventId?:number}>();
const dialog=ref<HTMLDialogElement|null>(null),branch=ref<number|null>(null),busy=ref(false),error=ref(''),point=ref<any>(null);
const origin=ref(localStorage.getItem('visit-qr-origin') || (['localhost','127.0.0.1'].includes(location.hostname)?'http://localhost:8098':'https://elibrary.kaztbu.edu.kz'));
async function open(){point.value=null;error.value='';branch.value=props.branches[0]?.id||null;await nextTick();dialog.value?.showModal();}
async function prepare(rotate=false,enabled?:boolean){
 if(rotate&&!confirm('Заменить QR-код? Ранее распечатанный код перестанет работать.'))return;
 busy.value=true;error.value='';
 try{point.value=await props.api(props.eventId?'/events/'+props.eventId+'/qr':'/visits/qr-points/'+branch.value,'POST',{base_url:origin.value,rotate,enabled});localStorage.setItem('visit-qr-origin',origin.value);}catch(e){error.value=String(e);}finally{busy.value=false;}
}
function print(){
 const w=window.open('','_blank');if(!w){error.value='Разрешите открытие окна для печати.';return;}
 const escape=(v:string)=>v.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
 w.document.write(`<!doctype html><html lang="ru"><meta charset="utf-8"><title>Посещение библиотеки</title><style>body{font:22px Arial;text-align:center;color:#052744;margin:30mm 15mm}h1{font-size:30px}svg{display:block;width:95mm;height:95mm;margin:12mm auto}p{line-height:1.6}small{font-size:12px;overflow-wrap:anywhere}@page{size:A4;margin:12mm}</style><h1>${escape(point.value.name)}</h1><h2>${props.eventId?'Отметьте участие в мероприятии':'Отметьте посещение библиотеки'}</h2>${point.value.qr_svg}<p>Отсканируйте QR-код камерой телефона.<br>Войдите в кабинет или укажите ФИО, группу и курс.</p><small>${escape(point.value.link)}</small></html>`);
 w.document.close();w.focus();w.print();
}
</script>
<template>
 <button type="button" @click="open">▦ {{eventId?'QR мероприятия':'QR для посетителей'}}</button>
 <dialog ref="dialog" class="visit-qr-dialog" aria-labelledby="visit-qr-title">
  <div class="qr-heading"><h2 id="visit-qr-title">{{eventId?'QR-код мероприятия':'QR-коды пунктов обслуживания'}}</h2><button type="button" @click="dialog?.close()" aria-label="Закрыть">✕</button></div>
  <p>{{eventId?'Отдельный QR для этого мероприятия. Отметка доступна в даты проведения, пока мероприятие не завершено и не отменено.':'Для каждого пункта — постоянный QR. Распечатайте его и разместите у входа.'}}</p>
  <p v-if="error" role="alert" class="error">{{error}}</p>
  <form @submit.prevent="prepare()">
   <label v-if="!eventId">Пункт обслуживания<select v-model="branch" :disabled="busy" @change="point=null"><option v-for="b in branches" :key="b.id" :value="b.id">{{b.name}}</option></select></label>
   <label>Адрес сайта для читателей<input v-model="origin" type="url" required :disabled="busy" @input="point=null" placeholder="https://elibrary.kaztbu.edu.kz"></label>
   <p class="muted">Для телефона нужен доступный ему адрес сайта. localhost открывается только на этом компьютере.</p>
   <button class="primary" :disabled="busy||(!eventId&&!branch)">{{busy?'Подготовка…':'Показать QR-код'}}</button>
  </form>
  <div v-if="point" class="qr-result">
   <h3>{{point.name}}</h3><p v-if="!point.enabled" class="error">Этот QR-код отключён.</p>
   <div v-html="point.qr_svg" role="img" :aria-label="'QR для '+point.name" class="qr-image"></div>
   <label>Ссылка для посетителя<input :value="point.link" readonly @focus="($event.target as HTMLInputElement).select()"></label>
   <div class="qr-actions"><button @click="print" :disabled="!point.enabled||busy">Печать QR</button><a :href="point.link" target="_blank" rel="noreferrer">Открыть страницу</a><button @click="prepare(false,!point.enabled)" :disabled="busy">{{point.enabled?'Отключить':'Включить'}}</button><button @click="prepare(true)" :disabled="busy">Заменить QR</button></div>
  </div>
  <p class="muted">Статичный QR можно сфотографировать и открыть позже. В журнале самостоятельные отметки выделяются по источнику; они не являются подтверждением присутствия сотрудником.</p>
 </dialog>
</template>
<style scoped>
.visit-qr-dialog{width:min(620px,calc(100vw - 32px));max-height:90vh;overflow:auto;border:1px solid #dce5ed;border-radius:20px;padding:24px;color:#052744}.visit-qr-dialog::backdrop{background:#05274488}.qr-heading,.qr-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.qr-heading{justify-content:space-between}.qr-heading h2{margin:0;font-size:22px}.visit-qr-dialog label{display:block;margin:16px 0;font-weight:600}.visit-qr-dialog input,.visit-qr-dialog select{width:100%;box-sizing:border-box;margin-top:6px}.qr-result{border-top:1px solid #dce5ed;margin-top:24px;padding-top:16px}.qr-image{text-align:center;background:white}.qr-image :deep(svg){width:240px;height:240px;max-width:100%}.muted{font-size:12px;color:#60758d;line-height:1.6}.qr-actions{margin-top:16px}.qr-actions a{font-size:14px}
</style>
