<script setup lang="ts">
import {ref,onMounted} from 'vue';
const props=defineProps<{api:(path:string,method?:string,body?:unknown)=>Promise<any>}>();
const emit=defineEmits<{record:[id:number],receipt:[id:number]}>();
const year=new Intl.DateTimeFormat('en',{year:'numeric',timeZone:'Asia/Almaty'}).format(new Date());
const from=ref(year+'-01-01'),to=ref(year+'-12-31'),data=ref<any>(null),busy=ref(false),error=ref('');
const money=(v:any)=>Number(v||0).toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2});
const date=(v:string)=>v.split('-').reverse().join('.');
async function load(){if(busy.value)return;busy.value=true;error.value='';data.value=null;try{data.value=await props.api('/ksu/specialties/report?'+new URLSearchParams({date_from:from.value,date_to:to.value}));}catch(e){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}}
async function download(){if(!data.value||busy.value)return;busy.value=true;error.value='';try{const q=new URLSearchParams({date_from:data.value.date_from,date_to:data.value.date_to});const r=await fetch('/api/ksu/specialties/export?'+q,{credentials:'same-origin'});if(!r.ok){const d=await r.json();throw Error(typeof d.detail==='string'?d.detail:'Не удалось выгрузить отчёт');}const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download='КСУ-по-специальностям.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}}
onMounted(load);
</script>
<template>
<section :aria-busy="busy">
 <div class="page-heading"><div><div class="eyebrow">УЧЁТ ФОНДА</div><h1>Поступления по специальностям</h1><p>Полные названия специальностей из карточек книг · второй отчёт КСУ.</p></div><button :disabled="busy||!data||data.total.unpriced_count>0" @click="download">Скачать Excel</button></div>
 <form class="card specialty-toolbar" @submit.prevent="load"><label>С даты<input v-model="from" type="date" required></label><label>По дату включительно<input v-model="to" type="date" :min="from" required></label><button :disabled="busy">{{busy?'Загрузка…':'Показать'}}</button></form>
 <p v-if="error" role="alert" class="inline-error">{{error}}</p>
 <template v-if="data">
  <p>Период по дате поступления: {{date(data.date_from)}} — {{date(data.date_to)}}. Отменённые поступления и экземпляры без поступления исключены.</p>
  <p class="profile-note">Специальность берётся из поля «Специальность» в карточке книги (952$j). Количество и стоимость — только по данной партии. Наименования считаются отдельно в каждой партии; списание не уменьшает историческое поступление. Суммы без доставки.</p>
  <p v-if="data.issue_count" class="pending-note">Книги без специальности или с несколькими специальностями показаны отдельно и включены в итог один раз. Пояснения приведены под таблицей и в Excel.</p>
  <p v-if="data.total.unpriced_count" role="alert" class="inline-error">Без цены в тенге: {{data.total.unpriced_count}} экз. Показана только известная сумма. Для выгрузки исправьте цены в поступлениях.</p>
  <div class="card holdings"><div class="specialty-summary"><span><b>{{data.rows.length}}</b> поступлений</span><span><b>{{data.total.titles}}</b> наименований по партиям</span><span><b>{{data.total.copies}}</b> экземпляров</span><span><b>{{money(data.total.amount)}} ₸</b> {{data.total.unpriced_count?'известная сумма':'общая сумма'}}</span></div>
   <div class="table-wrap specialty-table" tabindex="0" aria-label="Поступления по специальностям, горизонтальная прокрутка"><table><thead><tr><th rowspan="2">№ КСУ / дата</th><th rowspan="2">Источник / документ</th><th v-for="c in data.columns" :key="c.key" colspan="3" class="specialty-name">{{c.label}}</th><th colspan="3">Всего</th></tr><tr><template v-for="c in data.columns" :key="c.key"><th>Наим.</th><th>Экз.</th><th>Сумма, ₸</th></template><th>Наим.</th><th>Экз.</th><th>Сумма, ₸</th></tr></thead>
   <tbody><tr v-for="r in data.rows" :key="r.acquisition_id"><td><button @click="emit('receipt',r.acquisition_id)">{{r.number===null?'Без КСУ':r.number+'/'+r.year}}</button><small>{{date(r.received_on)}}</small></td><td>{{r.source}}<small>{{r.invoice||'Без номера документа'}}</small></td><template v-for="c in data.columns" :key="c.key"><td>{{r.groups[c.key]?.titles||0}}</td><td>{{r.groups[c.key]?.copies||0}}</td><td>{{money(r.groups[c.key]?.amount)}}</td></template><td>{{r.total.titles}}</td><td>{{r.total.copies}}</td><td>{{money(r.total.amount)}}</td></tr></tbody>
   <tfoot><tr><th colspan="2">Итого</th><template v-for="c in data.columns" :key="c.key"><td>{{data.totals[c.key].titles}}</td><td>{{data.totals[c.key].copies}}</td><td>{{money(data.totals[c.key].amount)}}</td></template><td>{{data.total.titles}}</td><td>{{data.total.copies}}</td><td>{{money(data.total.amount)}}</td></tr></tfoot></table></div>
   <p v-if="!data.rows.length" class="empty">За выбранный период поступлений нет.</p>
  </div>
  <section v-if="data.issue_count" class="card holdings"><h2>Пояснения к распределению</h2><template v-for="r in data.rows" :key="r.acquisition_id"><article v-if="r.issues.length"><h3>Поступление №{{r.acquisition_id}} · {{r.source}}</h3><button @click="emit('receipt',r.acquisition_id)">Открыть поступление</button><div v-for="(issue,i) in r.issues" :key="i"><button @click="emit('record',issue.record_id)">{{issue.title}} · запись №{{issue.record_id}}</button><ul><li v-for="text in issue.messages" :key="text">{{text}}</li></ul></div></article></template></section>
 </template>
</section>
</template>
<style scoped>
.specialty-toolbar{display:flex;gap:20px;align-items:end;padding:20px;flex-wrap:wrap}.specialty-toolbar label{display:flex;flex-direction:column;gap:6px}.specialty-summary{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:20px}.specialty-summary b{display:block;font-size:24px}.specialty-table{max-height:65vh;overflow:auto}.specialty-table table{border-collapse:separate;border-spacing:0;min-width:100%}.specialty-table th,.specialty-table td{padding:12px;min-width:90px;border-bottom:1px solid #dce3ed;text-align:right}.specialty-table th{background:#eef3fa}.specialty-table .specialty-name{min-width:300px;max-width:420px;white-space:normal;overflow-wrap:anywhere;text-align:center}.specialty-table td:nth-child(-n+2){text-align:left;min-width:180px}.specialty-table small{display:block;margin-top:6px}.specialty-table tfoot{font-weight:bold;background:#eef3fa}article{margin-top:20px}article button{margin:4px 0}
</style>
