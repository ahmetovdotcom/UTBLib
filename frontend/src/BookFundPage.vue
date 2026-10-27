<script setup lang="ts">
import {computed, onMounted, onUnmounted, ref} from 'vue';

type Language = 'kaz'|'rus'|'foreign'|'multilingual'|'unknown';
type Counts = {total:number}&Record<Language,number>;
type Fund = {as_of:string;rows:(Counts&{key:string;label:string})[];totals:Counts;
  records:number;excluded_non_book:number;needs_review:number};
const props=defineProps<{api:(path:string,method?:string,body?:unknown)=>Promise<any>}>();
const data=ref<Fund|null>(null),busy=ref(false),error=ref('');
let request=0;
const number=(n:number)=>new Intl.NumberFormat('ru-RU').format(n);
const stamp=computed(()=>data.value?new Date(data.value.as_of).toLocaleString('ru-RU',{timeZone:'Asia/Almaty'}):'');
const columns=computed(()=>[
  {key:'total',label:'Всего'},
  {key:'kaz',label:'На государственном языке'},
  {key:'rus',label:'На русском языке'},
  ...([{key:'foreign',label:'На иностранных языках'},
    {key:'multilingual',label:'Многоязычные'},
    {key:'unknown',label:'Язык не уточнён'}] as const).filter(c=>data.value?.totals[c.key]),
] as {key:keyof Counts;label:string}[]);
const rows=computed(()=>data.value?.rows.filter(r=>r.key!=='other'||r.total>0)||[]);
async function load(){
  if(busy.value)return;
  const token=++request;busy.value=true;error.value='';data.value=null;
  try{const result=await props.api('/statistics/book-fund');if(token===request)data.value=result;}
  catch(e){if(token===request)error.value=e instanceof Error?e.message:String(e);}
  finally{if(token===request)busy.value=false;}
}
function download(){
  if(!data.value)return;
  const table:(string|number)[][]=[['Книжный фонд — на '+stamp.value+' (Алматы)'],
    ['№','Книжный фонд',...columns.value.map(c=>c.label)],
    ['','Всего в фонде',...columns.value.map(c=>data.value!.totals[c.key])],
    ...rows.value.map((r,i)=>[r.key==='other'?'':i+1,r.label,...columns.value.map(c=>r[c.key])]),
    [],['Единица учёта — экземпляр. Выданные книги включены; списанные и отменённые исключены.'],
    ['Иностранные и многоязычные издания, неуточнённые данные входят в общий итог.'],
    ['Аудиовизуальные и электронные материалы вне книжного фонда',data.value.excluded_non_book],
  ];
  const csv='\uFEFF'+table.map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(';')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='Книжный фонд.csv';a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
onMounted(load);
onUnmounted(()=>request++);
</script>

<template>
<section class="book-fund" :aria-busy="busy">
  <header class="page-heading">
    <div><h1>Книжный фонд</h1><p>Состав действующего фонда по видам литературы и языкам. Единица учёта — экземпляр.</p></div>
    <div class="fund-actions"><button :disabled="busy" @click="load">{{busy?'Загрузка…':'Обновить'}}</button><button class="primary" :disabled="busy||!data" @click="download">Скачать CSV</button></div>
  </header>
  <p v-if="error" class="error" role="alert">Не удалось загрузить книжный фонд: {{error}}</p>
  <p v-if="busy" role="status">Подсчитываем экземпляры…</p>
  <template v-if="data">
    <div class="fund-metrics">
      <article class="card"><span>Всего в фонде</span><strong>{{number(data.totals.total)}}</strong><small>экземпляров · {{number(data.records)}} записей каталога</small></article>
      <article class="card"><span>На государственном языке</span><strong>{{number(data.totals.kaz)}}</strong><small>на казахском языке</small></article>
      <article class="card"><span>На русском языке</span><strong>{{number(data.totals.rus)}}</strong><small>экземпляров</small></article>
    </div>
    <section class="card fund-report" aria-label="Таблица книжного фонда">
      <div class="section-heading"><h2>Библиотечный фонд</h2><p>На {{stamp}} · Алматы</p></div>
      <div class="fund-table-scroll" role="region" aria-label="Книжный фонд по видам литературы и языкам" tabindex="0">
        <table>
          <thead><tr><th scope="col">№</th><th scope="col">Книжный фонд</th><th v-for="col in columns" :key="col.key" scope="col" class="fund-number">{{col.label}}</th></tr></thead>
          <tbody>
            <tr class="fund-total"><td></td><th scope="row">Всего в фонде</th><td v-for="col in columns" :key="col.key" class="fund-number">{{number(data.totals[col.key])}}</td></tr>
            <tr v-for="(row,i) in rows" :key="row.key" :class="{'fund-other':row.key==='other'}"><td>{{row.key==='other'?'—':i+1}}</td><th scope="row">{{row.label}}</th><td v-for="col in columns" :key="col.key" class="fund-number">{{number(row[col.key])}}</td></tr>
          </tbody>
        </table>
      </div>
      <p v-if="!data.totals.total" class="fund-empty">В книжном фонде пока нет действующих экземпляров. Записи каталога без экземпляров в этот отчёт не входят.</p>
      <div class="fund-footnote"><p>Книги на руках у читателей включены. Списанные экземпляры и отменённые поступления исключены.</p><p>Каждый экземпляр входит в одну строку и одну языковую колонку. Дополнительные колонки появляются, если есть иностранные, многоязычные издания или неуточнённый язык.</p></div>
    </section>
    <p v-if="data.needs_review" class="fund-notice" role="status">Для {{number(data.needs_review)}} экземпляров вид литературы или язык не удалось однозначно определить. Они учтены в общем итоге, в строке «Прочая / вид не определён» или колонке «Язык не уточнён». Уточните поля в каталоге и обновите отчёт.</p>
    <p v-if="data.excluded_non_book" class="muted">Отдельно от книжного фонда: {{number(data.excluded_non_book)}} экземпляров аудио, видео, CD, дискет и кассет.</p>
    <details class="card fund-rules"><summary>Как рассчитывается фонд</summary>
      <ul>
        <li>Считаются действующие экземпляры из поступлений и добавленные отдельно, в том числе импортированные. Текущая выдача, ремонт или резерв не уменьшают фонд.</li>
        <li>Вид литературы определяется по «Типу литературы для КСУ ВШ» (952$a): КУ — учебная, КУМ и МИ — учебно-методическая, КН — научная, КС — справочная, КХ — художественная.</li>
        <li>Если код не заполнен, используется распознанное значение «Вид литературы» (952$c). Оно также уточняет учебно-методические пособия с общим кодом КУ. Неизвестные и противоречивые коды остаются в отдельной строке.</li>
        <li>Язык берётся из «Кода языка текста» (041$a), а при его отсутствии — из кода 952$a. Если они противоречат друг другу, язык считается неуточнённым. Несколько языков в 041$a учитываются как многоязычное издание.</li>
        <li>Отчёт показывает текущее состояние базы. Он не является историческим отчётом за прошлый год и не заменяет КСУ поступлений.</li>
      </ul>
    </details>
  </template>
</section>
</template>

<style scoped>
.fund-actions{display:flex;gap:10px;flex-shrink:0}.fund-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin:28px 0}.fund-metrics article{padding:26px;display:grid;gap:14px}.fund-metrics span{color:#536478;font-size:14px}.fund-metrics strong{font-size:34px;color:#052744;font-variant-numeric:tabular-nums}.fund-metrics small{color:#72839b;font-size:12px}.fund-report{overflow:hidden}.fund-report .section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}.fund-report h2{margin:0}.fund-report .section-heading p{margin:0;font-size:12px}.fund-table-scroll{overflow:auto}.fund-table-scroll table{width:100%;min-width:720px;border-collapse:collapse}.fund-table-scroll th,.fund-table-scroll td{padding:18px 20px;border-bottom:1px solid #e7edf4}.fund-table-scroll thead th{vertical-align:bottom}.fund-table-scroll th:first-child{width:40px}.fund-table-scroll tbody th{background:transparent;color:#18283b;font-size:14px;font-weight:500;text-align:left;min-width:230px}.fund-table-scroll .fund-number{text-align:right;font-variant-numeric:tabular-nums;min-width:105px}.fund-table-scroll thead .fund-number{max-width:175px}.fund-table-scroll .fund-total{background:#edf5f7}.fund-table-scroll .fund-total th,.fund-table-scroll .fund-total td{font-weight:700;color:#052744}.fund-table-scroll .fund-other{background:#fffbf2}.fund-footnote{padding:16px 24px}.fund-footnote p{font-size:12px;margin:4px 0}.fund-notice{padding:16px 20px;background:#fff8e6;border:1px solid #eddbad;border-radius:12px;color:#7c5c21!important;font-size:13px}.fund-empty{padding:20px 24px}.fund-rules{margin-top:24px;padding:20px 24px}.fund-rules summary{cursor:pointer;font-weight:600;color:#052744}.fund-rules ul{padding-left:20px;font-size:13px;line-height:1.7;color:#64748a}.fund-rules li{margin:10px 0}
@media(max-width:900px){.fund-metrics{gap:12px}.fund-metrics article{padding:20px}.fund-metrics strong{font-size:28px}.fund-report .section-heading{align-items:start;flex-direction:column}}
@media(max-width:650px){.fund-metrics{grid-template-columns:1fr}.fund-metrics article{gap:8px}.fund-actions{flex-wrap:wrap}.fund-rules{padding:20px}.fund-footnote{padding:16px 20px}}
</style>
