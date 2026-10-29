<script setup lang="ts">
import {computed, nextTick, onMounted, onUnmounted, ref} from 'vue';
import AttendanceFilter from './AttendanceFilter.vue';

type Count = {visits:number;unique:number};
type Row = Count & {period:string;date_from:string;date_to:string;categories:Record<string,Count>;subtotal?:boolean};
type Filters = Record<string,string|string[]>;
type Report = {
  filters:Filters;timezone:string;rules:string;columns:{key:string;label:string}[];
  rows:Row[];months:Row[];totals:Row;
  summary:{selected_days:number;active_days:number;average_per_day:number;visits_per_reader:number;peak:{date:string;visits:number}|null};
  breakdown:({key:string;label:string}&Count)[];hours:({hour:number}&Count)[];weekdays:({day:number;label:string}&Count)[];
};
const props=defineProps<{api:(path:string,method?:string,body?:any)=>Promise<any>;can:(permission:string)=>boolean}>();
const emit=defineEmits<{reader:[id:number]}>();
const lists=['branch_id','bucket','faculty','department','education_program','study_group','course','cohort_year','category','status','scanned_by','source','weekday'];
const labels:Record<string,string>={branch_id:'Пункт обслуживания',bucket:'Группа отчёта',faculty:'Факультет',department:'Кафедра',education_program:'Образовательная программа',study_group:'Учебная группа',course:'Курс',cohort_year:'Год поступления',category:'Категория в карточке',status:'Статус читателя',scanned_by:'Отметил',source:'Точка отметки',weekday:'Дни недели',time_from:'Время с',time_to:'Время до',q:'Читатель'};
function today(){const p=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Almaty',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());return ['year','month','day'].map(k=>p.find(x=>x.type===k)!.value).join('-');}
function defaults():Filters{return {date_from:today().slice(0,7)+'-01',date_to:today(),group_by:'day',breakdown:'faculty',q:'',time_from:'',time_to:'',...Object.fromEntries(lists.map(k=>[k,[]]))};}
const form=ref<Filters>(defaults()),data=ref<Report|null>(null),busy=ref(false),error=ref(''),optionError=ref(''),exporting=ref(false),advanced=ref(false);
const options=ref<Record<string,{value:string;label:string}[]>>({}),dimensions=ref<Record<string,string>>({});
const metric=ref<'visits'|'unique'>('visits'),chartMode=ref<'period'|'hour'|'weekday'>('period');
const tableOffset=ref(0),breakdownOffset=ref(0),breakdownSearch=ref('');
const journal=ref<any>(null),journalFilters=ref<Filters|null>(null),journalOffset=ref(0),journalBusy=ref(false),journalError=ref('');
let generation=0,journalGeneration=0;
const number=(value:number)=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(value);
const day=(value:string)=>value.split('-').reverse().join('.');
const month=(value:string)=>new Date(value.slice(0,7)+'-01T12:00:00Z').toLocaleDateString('ru-RU',{month:'long',year:'numeric',timeZone:'Asia/Almaty'});
const dateTime=(value:string)=>new Date(value).toLocaleString('ru-RU',{timeZone:'Asia/Almaty'});
const copy=(value:Filters):Filters=>JSON.parse(JSON.stringify(value));
function query(value:Filters){const p=new URLSearchParams();for(const key of Object.keys(value).sort()){const v=value[key];if(Array.isArray(v)){for(const item of v)p.append(key,String(item));}else if(v!=='')p.set(key,String(v));}return p.toString();}
const dirty=computed(()=>data.value&&query(form.value)!==query(data.value.filters));
const appliedLabels=computed(()=>data.value?Object.entries(labels).flatMap(([key,label])=>{
  const value=data.value!.filters[key];if(!value||Array.isArray(value)&&!value.length)return [];
  const text=Array.isArray(value)?value.map(v=>options.value[key]?.find(o=>String(o.value)===String(v))?.label||String(v)||'Не указано').join(', '):value;
  return [label+': '+text];
}):[]);
async function load(){
  if(busy.value)return;
  busy.value=true;error.value='';const token=++generation,snapshot=copy(form.value);
  journalGeneration++;journal.value=null;journalFilters.value=null;journalBusy.value=false;journalError.value='';
  try{const result=await props.api('/statistics/attendance?'+query(snapshot));if(token!==generation)return;data.value=result;tableOffset.value=0;breakdownOffset.value=0;}
  catch(e){if(token===generation)error.value=e instanceof Error?e.message:String(e);}
  finally{if(token===generation)busy.value=false;}
}
async function loadOptions(){try{const r=await props.api('/statistics/attendance/options');options.value=r.filters;dimensions.value=r.dimensions;optionError.value='';}catch(e){optionError.value='Не удалось загрузить варианты фильтров. '+String(e);}}
function iso(value:Date){return value.toISOString().slice(0,10);}
function preset(kind:string){
  const now=today(),d=new Date(now+'T12:00:00Z');let from=now,to=now;
  if(kind==='week'){d.setUTCDate(d.getUTCDate()-6);from=iso(d);}
  if(kind==='month')from=now.slice(0,7)+'-01';
  if(kind==='previous'){d.setUTCDate(0);to=iso(d);from=to.slice(0,7)+'-01';}
  if(kind==='year')from=now.slice(0,4)+'-01-01';
  if(kind==='academic')from=String(d.getUTCFullYear()-(d.getUTCMonth()<8?1:0))+'-09-01';
  form.value.date_from=from;form.value.date_to=to;load();
}
function reset(){form.value=defaults();load();}
async function download(format:'xlsx'|'csv'){
  if(!data.value||exporting.value)return;
  exporting.value=true;error.value='';
  const snapshot=copy(data.value.filters);
  try{const response=await fetch('/api/statistics/attendance/export?'+query(snapshot)+'&format='+format,{credentials:'same-origin'});
    if(!response.ok){const d=await response.json();throw Error(typeof d.detail==='string'?d.detail:'Не удалось выгрузить отчёт');}
    const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='Посещаемость '+snapshot.date_from+' — '+snapshot.date_to+'.'+format;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(e){error.value=e instanceof Error?e.message:String(e);}finally{exporting.value=false;}
}
const allTableRows=computed(()=>{
  if(!data.value)return [];
  const rows:Row[]=[],months=Object.fromEntries(data.value.months.map(m=>[m.period.slice(0,7),m]));
  data.value.rows.forEach((row,i)=>{rows.push(row);if(data.value!.filters.group_by==='day'&&(i===data.value!.rows.length-1||data.value!.rows[i+1].period.slice(0,7)!==row.period.slice(0,7)))rows.push({...months[row.period.slice(0,7)],subtotal:true});});
  return rows;
});
const tableRows=computed(()=>allTableRows.value.slice(tableOffset.value,tableOffset.value+62));
const breakdownRows=computed(()=>data.value?.breakdown.filter(r=>r.label.toLocaleLowerCase().includes(breakdownSearch.value.trim().toLocaleLowerCase()))||[]);
function periodLabel(row:Row){return row.subtotal?'Итого за '+month(row.period):row.date_from===row.date_to?day(row.date_from):day(row.date_from)+' — '+day(row.date_to);}
async function tablePage(delta:number){tableOffset.value+=delta;await nextTick();document.getElementById('attendance-table')?.scrollIntoView({block:'start'});}
const series=computed(()=>{
  if(!data.value)return [];
  if(chartMode.value==='hour')return data.value.hours.map(r=>({...r,label:String(r.hour).padStart(2,'0')+':00'}));
  if(chartMode.value==='weekday')return data.value.weekdays;
  return data.value.rows.map(r=>({...r,label:periodLabel(r)}));
});
const peak=computed(()=>Math.max(1,...series.value.map(r=>r[metric.value])));
const points=computed(()=>series.value.map((r,i)=>({x:series.value.length===1?400:30+i*740/Math.max(1,series.value.length-1),y:195-r[metric.value]/peak.value*165,...r})));
const line=computed(()=>points.value.map(p=>p.x+','+p.y).join(' '));
const categoryMax=computed(()=>Math.max(1,...(data.value?.columns.map(c=>data.value!.totals.categories[c.key][metric.value])||[])));
async function showJournal(row?:Row,bucket?:string,dimensionValue?:string){
  if(!data.value)return;
  const f=copy(data.value.filters);
  if(row){f.date_from=row.date_from;f.date_to=row.date_to;}
  if(bucket)f.bucket=[bucket];
  if(dimensionValue!==undefined)f[String(f.breakdown)]=[dimensionValue];
  journalFilters.value=f;journalOffset.value=0;await loadJournal();await nextTick();document.getElementById('attendance-journal')?.scrollIntoView({block:'start'});
}
async function loadJournal(){
  if(!journalFilters.value)return;
  const token=++journalGeneration; journalBusy.value=true;journalError.value='';journal.value=null;
  try{const r=await props.api('/statistics/attendance/journal?'+query(journalFilters.value)+'&offset='+journalOffset.value);if(token===journalGeneration)journal.value=r;}
  catch(e){if(token===journalGeneration)journalError.value=String(e);}
  finally{if(token===journalGeneration)journalBusy.value=false;}
}
function closeJournal(){journalGeneration++;journalFilters.value=null;journal.value=null;journalBusy.value=false;}
function journalPage(delta:number){journalOffset.value+=delta;loadJournal();}
onMounted(async()=>{await Promise.all([loadOptions(),load()]);});
onUnmounted(()=>{generation++;journalGeneration++;});
</script>

<template>
<section class="attendance-page" :aria-busy="busy">
  <header class="page-heading">
    <div><h1>Отчёт по посещаемости</h1><p>Посещения библиотеки, состав читателей и часы нагрузки. Все даты и время — Алматы.</p></div>
    <div class="report-actions"><button :disabled="busy||!data" @click="load">Обновить</button><button :disabled="busy||exporting||!data" @click="download('csv')">CSV</button><button class="primary" :disabled="busy||exporting||!data" @click="download('xlsx')">{{exporting?'Выгрузка…':'↓ Скачать Excel'}}</button></div>
  </header>
  <p v-if="optionError" class="error" role="alert">{{optionError}} <button @click="loadOptions">Повторить</button></p>
  <p v-if="error" class="error attendance-alert" role="alert">{{error}}</p>
  <form class="card report-filters" @submit.prevent="load">
    <div class="filter-heading"><h2>Период и условия</h2><small>Внутри одного фильтра — любое выбранное значение; между фильтрами — все условия сразу.</small></div>
    <div class="period-row">
      <label>Дата с<input type="date" v-model="form.date_from" required min="1900-01-01" max="2200-12-31"></label>
      <label>Дата по<input type="date" v-model="form.date_to" required min="1900-01-01" max="2200-12-31"></label>
      <label>Строки таблицы<select aria-label="Строки таблицы" v-model="form.group_by"><option value="day">По дням</option><option value="week">По неделям</option><option value="month">По месяцам</option></select></label>
      <label>Подробная разбивка<select aria-label="Подробная разбивка" v-model="form.breakdown"><option v-for="(label,key) in dimensions" :key="key" :value="key">{{label}}</option></select></label>
    </div>
    <div class="period-presets"><span>Быстрый период:</span><button type="button" :disabled="busy" @click="preset('today')">Сегодня</button><button type="button" :disabled="busy" @click="preset('week')">7 дней</button><button type="button" :disabled="busy" @click="preset('month')">Этот месяц</button><button type="button" :disabled="busy" @click="preset('previous')">Прошлый месяц</button><button type="button" :disabled="busy" @click="preset('academic')">Учебный год</button><button type="button" :disabled="busy" @click="preset('year')">Календарный год</button></div>
    <div class="filter-grid"><AttendanceFilter v-for="key in ['branch_id','bucket','faculty']" :key="key" :label="labels[key]" :model-value="form[key] as string[]" @update:model-value="form[key]=$event" :options="options[key]||[]" /></div>
    <button type="button" class="advanced-toggle" :aria-expanded="advanced" aria-controls="attendance-advanced" @click="advanced=!advanced">{{advanced?'− Скрыть':'＋ Ещё'}} фильтры: кафедра, группа, время, читатель</button>
    <div v-if="advanced" id="attendance-advanced">
      <div class="filter-grid"><AttendanceFilter v-for="key in ['department','education_program','study_group','course','cohort_year','category','status','scanned_by','source']" :key="key" :label="labels[key]" :model-value="form[key] as string[]" @update:model-value="form[key]=$event" :options="options[key]||[]" /></div>
      <div class="time-filters"><label>Время с<input type="time" v-model="form.time_from"></label><label>Время по<input type="time" v-model="form.time_to"></label><label class="reader-query">ФИО, номер билета или штрихкод<input v-model="form.q" maxlength="200" placeholder="Любой фрагмент имени или точный билет"></label></div>
      <fieldset class="weekday-filter"><legend>Дни недели <small>Без выбора — все дни, включая выходные.</small></legend><label v-for="d in options.weekday||[]" :key="d.value"><input type="checkbox" :value="d.value" v-model="form.weekday">{{d.label}}</label><button type="button" @click="form.weekday=['0','1','2','3','4']">Пн–Пт</button><button type="button" @click="form.weekday=[]">Все дни</button></fieldset>
      <p class="filter-help">Время ограничивает каждый выбранный день; 22:00–08:00 означает ночные часы. «Не указано» находит карточки с незаполненным полем.</p>
    </div>
    <div class="filter-footer"><span v-if="dirty" role="status">Условия изменены. Нажмите «Применить».</span><span v-else>Учитываются фактически зарегистрированные визиты.</span><div><button type="button" :disabled="busy" @click="reset">Сбросить</button><button class="primary" :disabled="busy">{{busy?'Подсчёт…':'Применить'}}</button></div></div>
  </form>
  <p v-if="busy" role="status" class="muted">Рассчитываем отчёт…</p>
  <template v-if="data">
    <div class="report-scope"><strong>{{day(String(data.filters.date_from))}} — {{day(String(data.filters.date_to))}}</strong><span>{{data.summary.selected_days}} дней в выборке · {{data.summary.active_days}} с посещениями</span></div>
    <div v-if="appliedLabels.length" class="applied-filters"><span v-for="label in appliedLabels" :key="label">{{label}}</span></div>
    <div class="attendance-metrics">
      <article class="card"><span>Посещений</span><strong>{{number(data.totals.visits)}}</strong><button class="text-link" @click="showJournal()">Открыть журнал →</button></article>
      <article class="card"><span>Уникальных читателей</span><strong>{{number(data.totals.unique)}}</strong><small>{{number(data.summary.visits_per_reader)}} визита на читателя</small></article>
      <article class="card"><span>В среднем за день</span><strong>{{number(data.summary.average_per_day)}}</strong><small>включая дни без посещений</small></article>
      <article class="card"><span>Самый посещаемый день</span><strong>{{data.summary.peak?number(data.summary.peak.visits):'—'}}</strong><small>{{data.summary.peak?day(data.summary.peak.date):'За период посещений нет'}}</small></article>
    </div>
    <p v-if="!data.totals.visits" class="attendance-empty" role="status">По этим условиям посещений нет. Таблица показывает нули; попробуйте другой период или снимите часть фильтров.</p>
    <div class="chart-toolbar"><h2>Динамика и состав</h2><label>Показатель диаграмм<select aria-label="Показатель диаграмм" v-model="metric"><option value="visits">Посещения</option><option value="unique">Уникальные читатели</option></select></label></div>
    <div class="attendance-charts">
      <article class="card trend-card">
        <div class="chart-heading"><h3>{{chartMode==='period'?'Динамика посещаемости':chartMode==='hour'?'Распределение по часам':'Распределение по дням недели'}}</h3><select v-model="chartMode" aria-label="Группировка диаграммы"><option value="period">За период</option><option value="hour">По часам</option><option value="weekday">По дням недели</option></select></div>
        <svg viewBox="0 0 800 225" role="img" :aria-label="(metric==='visits'?'Посещения':'Уникальные читатели')+'; максимум '+peak" class="trend-chart">
          <title>Динамика посещаемости. Точные значения доступны в таблицах ниже.</title>
          <line v-for="n in [0,1,2,3]" :key="n" x1="30" x2="770" :y1="195-n*55" :y2="195-n*55" stroke="#e0e8f0" stroke-dasharray="4 5"/>
          <polygon v-if="points.length" :points="points[0].x+',195 '+line+' '+points[points.length-1].x+',195'" fill="#e2f3f2"/>
          <polyline :points="line" fill="none" stroke="#008789" stroke-width="3" stroke-linejoin="round"/>
          <circle v-for="(p,i) in points.length<=90?points:[]" :key="i" :cx="p.x" :cy="p.y" r="4" fill="#008789"><title>{{p.label}}: {{number(p[metric])}}</title></circle>
          <text x="30" y="218" fill="#72839b" font-size="12">{{series[0]?.label}}</text><text x="770" y="218" text-anchor="end" fill="#72839b" font-size="12">{{series.length>1?series[series.length-1].label:''}}</text>
          <text x="30" y="18" fill="#536478" font-size="12">{{number(peak)}}</text>
        </svg>
        <p class="chart-note">При выборе уникальных читателей один человек считается один раз в каждой точке диаграммы.</p>
      </article>
      <article class="card category-chart"><h3>По группам читателей</h3><div v-for="column in data.columns" :key="column.key" class="category-bar">
        <div><button class="text-link" @click="showJournal(undefined,column.key)">{{column.label}}</button><strong>{{number(data.totals.categories[column.key][metric])}}</strong></div>
        <div class="bar-track"><span :style="{width:(100*data.totals.categories[column.key][metric]/categoryMax)+'%'}"></span></div>
      </div></article>
    </div>
    <section id="attendance-table" class="card report-table">
      <div class="section-heading"><div><h2>Посещения по категориям</h2><p>Нажмите на дату или число, чтобы открыть соответствующие посещения.</p></div><span>{{({day:'По дням',week:'По неделям',month:'По месяцам'} as any)[String(data.filters.group_by)]}}</span></div>
      <div class="attendance-table-scroll" tabindex="0" role="region" aria-label="Посещения по категориям читателей">
        <table><thead><tr><th rowspan="2" scope="col">Дата / период</th><th :colspan="data.columns.length" scope="colgroup">Посещения по группам читателей</th><th rowspan="2" scope="col">Всего посещений</th><th rowspan="2" scope="col">Уникальных читателей</th></tr><tr><th v-for="col in data.columns" :key="col.key" scope="col">{{col.label}}</th></tr></thead>
          <tbody><tr v-for="row in tableRows" :key="row.period+(row.subtotal?'-total':'')" :class="{'month-total':row.subtotal}"><th scope="row"><span v-if="row.subtotal">{{periodLabel(row)}}</span><button v-else class="text-link" @click="showJournal(row)">{{periodLabel(row)}}</button></th><td v-for="col in data.columns" :key="col.key"><span v-if="row.subtotal||!row.categories[col.key].visits">{{number(row.categories[col.key].visits)}}</span><button v-else class="text-link" :aria-label="col.label+', '+periodLabel(row)+': '+row.categories[col.key].visits+' посещений'" @click="showJournal(row,col.key)">{{number(row.categories[col.key].visits)}}</button></td><td class="total-cell">{{number(row.visits)}}</td><td>{{number(row.unique)}}</td></tr></tbody>
          <tfoot><tr><th scope="row">Итого за период</th><td v-for="col in data.columns" :key="col.key">{{number(data.totals.categories[col.key].visits)}}</td><td>{{number(data.totals.visits)}}</td><td>{{number(data.totals.unique)}}</td></tr></tfoot>
        </table>
      </div>
      <div v-if="allTableRows.length>62" class="report-pagination"><span>Строки {{tableOffset+1}}–{{Math.min(tableOffset+62,allTableRows.length)}} из {{allTableRows.length}}. Excel содержит весь отчёт.</span><div><button :disabled="tableOffset===0" @click="tablePage(-62)">← Назад</button><button :disabled="tableOffset+62>=allTableRows.length" @click="tablePage(62)">Далее →</button></div></div>
      <p class="report-footnote">Итог уникальных читателей не равен сумме по дням или месяцам: повторные визиты одного человека объединяются за весь период.</p>
    </section>
    <section class="card report-table breakdown-table">
      <div class="section-heading"><div><h2>{{dimensions[String(data.filters.breakdown)]||'Подробная разбивка'}}</h2><p>Все показатели рассчитаны с теми же фильтрами. Нажмите на группу для детализации.</p></div><input v-model="breakdownSearch" @input="breakdownOffset=0" aria-label="Поиск в группах отчёта" placeholder="Найти группу…"></div>
      <div class="attendance-table-scroll"><table><thead><tr><th scope="col">Группа</th><th scope="col">Посещений</th><th scope="col">Доля посещений</th><th scope="col">Уникальных читателей</th></tr></thead><tbody><tr v-for="row in breakdownRows.slice(breakdownOffset,breakdownOffset+20)" :key="row.key"><th scope="row"><button class="text-link" @click="showJournal(undefined,undefined,row.key)">{{row.label}}</button></th><td>{{number(row.visits)}}</td><td>{{number(data.totals.visits?100*row.visits/data.totals.visits:0)}}%</td><td>{{number(row.unique)}}</td></tr><tr v-if="!breakdownRows.length"><td colspan="4" class="attendance-empty">Нет данных для отображения.</td></tr></tbody></table></div>
      <div v-if="breakdownRows.length>20" class="report-pagination"><span>{{breakdownOffset+1}}–{{Math.min(breakdownOffset+20,breakdownRows.length)}} из {{breakdownRows.length}}</span><div><button :disabled="breakdownOffset===0" @click="breakdownOffset-=20">← Назад</button><button :disabled="breakdownOffset+20>=breakdownRows.length" @click="breakdownOffset+=20">Далее →</button></div></div>
    </section>
    <details class="card distribution-details"><summary>Часы и дни недели — точные значения</summary><div class="distribution-grid"><table><thead><tr><th>Час</th><th>Посещений</th><th>Читателей</th></tr></thead><tbody><tr v-for="r in data.hours" :key="r.hour"><td>{{String(r.hour).padStart(2,'0')}}:00</td><td>{{r.visits}}</td><td>{{r.unique}}</td></tr></tbody></table><table><thead><tr><th>День</th><th>Посещений</th><th>Читателей</th></tr></thead><tbody><tr v-for="r in data.weekdays" :key="r.day"><td>{{r.label}}</td><td>{{r.visits}}</td><td>{{r.unique}}</td></tr></tbody></table></div></details>
    <section v-if="journalFilters" id="attendance-journal" class="card report-table">
      <div class="section-heading"><div><h2>Детализация посещений</h2><p>{{day(String(journalFilters.date_from))}} — {{day(String(journalFilters.date_to))}} · {{journal?.total??'…'}} посещений</p></div><button @click="closeJournal">Закрыть</button></div>
      <p v-if="journalBusy" role="status" class="report-footnote">Загружаем журнал…</p><p v-if="journalError" role="alert" class="error report-footnote">{{journalError}}</p>
      <div v-if="journal" class="attendance-table-scroll"><table><thead><tr><th>Читатель</th><th>Время</th><th>Категория / факультет</th><th>Пункт обслуживания</th><th>Отметил</th></tr></thead><tbody><tr v-for="r in journal.items" :key="r.id"><td><button v-if="can('readers.registry.view')" class="text-link" @click="emit('reader',r.reader_id)">{{r.full_name}}</button><strong v-else>{{r.full_name}}</strong><small>{{r.ticket_number}}</small></td><td>{{dateTime(r.scanned_at)}}</td><td>{{options.category?.find(o=>o.value===r.category)?.label||r.category}}<small>{{r.faculty||'Факультет не указан'}}<template v-if="r.study_group"> · {{r.study_group}}</template></small></td><td>{{r.branch}}<small>{{options.source?.find(o=>o.value===r.source)?.label||r.source}}</small></td><td>{{r.actor}}</td></tr><tr v-if="!journal.items.length"><td colspan="5" class="attendance-empty">Посещений не найдено.</td></tr></tbody></table></div>
      <div v-if="journal" class="report-pagination"><span>{{journal.total?journalOffset+1:0}}–{{Math.min(journalOffset+50,journal.total)}} из {{number(journal.total)}}</span><div><button :disabled="journalBusy||journalOffset===0" @click="journalPage(-50)">← Назад</button><button :disabled="journalBusy||journalOffset+50>=journal.total" @click="journalPage(50)">Далее →</button></div></div>
    </section>
    <details class="card report-rules"><summary>Как считается отчёт</summary><p>{{data.rules}}</p><p>БАК — подтверждённая категория «Бакалавр», МАГ — «Магистрант», ПОҚ — преподаватели, ППС и читатели с признаком преподавателя. «Внешние пользователи» — отдельная категория в карточке читателя. Докторанты и остальные категории не теряются: при наличии посещений появляются дополнительные колонки.</p><p>Фильтр пункта обслуживания относится к месту визита. Выходные и дни без посещений включены, пока вы явно не выбрали дни недели. Среднее за день считается по всем выбранным датам; для рабочей недели выберите Пн–Пт. Время окончания включается до конца указанной минуты. Один читатель может посещать разные пункты или приходить в разные часы, поэтому уникальных читателей этих групп нельзя складывать.</p><p>Это отчёт по зарегистрированным посещениям. Выдача книги, вход на сайт и добавление читателя сами по себе не являются посещением.</p></details>
  </template>
</section>
</template>

<style scoped>
.attendance-page{--ink:#052744;--teal:#008789}.attendance-page .page-heading{align-items:flex-start}.attendance-page .page-heading>div:first-child{max-width:760px}.report-actions{display:flex;gap:8px;flex-wrap:wrap;flex-shrink:0}.report-filters{padding:24px;margin:28px 0}.filter-heading{display:flex;align-items:center;gap:24px;justify-content:space-between;margin-bottom:20px}.filter-heading h2{margin:0;white-space:nowrap}.filter-heading small{color:#708199;max-width:540px;font-size:12px;line-height:1.5}.period-row{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}.period-row label,.time-filters label{font-size:13px;color:#536478}.period-row input,.period-row select,.time-filters input{width:100%;height:44px}.period-presets{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:14px 0 22px}.period-presets>span{font-size:12px;color:#708199}.period-presets button{border:0;background:#edf4f8;color:#275069;min-height:30px;padding:6px 12px;font-size:12px;box-shadow:none}.filter-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.advanced-toggle{border:0;box-shadow:none;background:transparent;padding:14px 0;color:var(--teal);font-size:13px}.time-filters{display:grid;grid-template-columns:1fr 1fr 2fr;gap:16px;margin:18px 0}.weekday-filter{border:0;padding:0;display:flex;flex-wrap:wrap;gap:8px;align-items:center}.weekday-filter legend{font-size:13px;color:#536478;margin-bottom:12px}.weekday-filter legend small{font-size:12px;margin-left:8px;color:#708199}.weekday-filter label{display:flex;gap:7px;align-items:center;font-size:13px;margin:0;padding:9px 12px;border:1px solid #dbe4ee;border-radius:8px}.weekday-filter input{width:15px;height:15px;margin:0;accent-color:var(--teal)}.weekday-filter button{font-size:12px;min-height:35px;padding:7px 10px}.filter-help{font-size:12px;color:#708199;line-height:1.6}.filter-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;border-top:1px solid #e2e9f1;padding-top:18px;margin-top:16px}.filter-footer>span{font-size:12px;color:#708199}.filter-footer>div{display:flex;gap:10px}.report-scope{display:flex;gap:20px;align-items:center;justify-content:space-between;margin:24px 0 16px;color:var(--ink)}.report-scope>span{font-size:12px;color:#708199}.applied-filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}.applied-filters>span{font-size:12px;line-height:1.5;max-width:100%;overflow-wrap:anywhere;border:1px solid #cfe5e8;background:#f1f8f9;border-radius:8px;padding:6px 10px;color:#31636b}.attendance-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:20px 0 28px}.attendance-metrics article{padding:22px;display:flex;flex-direction:column;align-items:flex-start;gap:12px}.attendance-metrics article>span{font-size:13px;color:#536478}.attendance-metrics strong{font-size:32px;font-variant-numeric:tabular-nums;color:var(--ink)}.attendance-metrics small{font-size:12px;color:#708199}.text-link{border:0!important;background:transparent!important;box-shadow:none!important;padding:0!important;min-height:0!important;text-align:inherit;color:#00777a;font-weight:600;line-height:1.5}.text-link:hover{text-decoration:underline}.attendance-metrics .text-link{font-size:12px}.chart-toolbar,.chart-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:14px}.chart-toolbar h2,.chart-heading h3{margin:0}.chart-toolbar label{display:flex;gap:10px;align-items:center;font-size:12px;color:#708199}.chart-toolbar select,.chart-heading select{width:auto;margin:0;padding:9px 12px;font-size:13px}.attendance-charts{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:20px;margin-bottom:24px}.attendance-charts article{padding:24px;min-width:0}.trend-chart{width:100%;display:block;margin:14px 0}.chart-note{font-size:12px;color:#708199}.category-chart h3{margin:0 0 20px}.category-bar{margin:14px 0}.category-bar>div:first-child{display:flex;justify-content:space-between;gap:12px;font-size:12px;margin-bottom:7px}.category-bar .text-link{font-weight:400}.category-bar strong{color:var(--ink);font-variant-numeric:tabular-nums}.bar-track{height:7px;border-radius:6px;background:#eef3f7;overflow:hidden}.bar-track>span{height:100%;background:#008789;display:block;border-radius:6px}.report-table{margin:24px 0;overflow:hidden;scroll-margin-top:20px}.report-table .section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:22px 24px}.report-table h2{margin:0}.report-table .section-heading p{margin:7px 0 0;font-size:12px}.report-table .section-heading>span{font-size:12px;color:#708199;white-space:nowrap}.report-table .section-heading>input{width:240px;margin:0}.attendance-table-scroll{overflow:auto}.attendance-table-scroll table{width:100%;min-width:780px;border-collapse:collapse}.attendance-table-scroll th,.attendance-table-scroll td{border-bottom:1px solid #e2e9f1;padding:14px 16px;font-variant-numeric:tabular-nums}.attendance-table-scroll thead th{color:#536478;vertical-align:middle;font-size:12px;background:#f0f4f8;text-align:center;min-width:100px}.attendance-table-scroll tbody th{font-size:13px;font-weight:500;background:transparent;text-align:left;min-width:180px}.attendance-table-scroll td{text-align:right}.attendance-table-scroll thead th:first-child{text-align:left}.attendance-table-scroll .total-cell{background:#f2f7fa;font-weight:600;color:var(--ink)}.attendance-table-scroll .month-total{background:#eaf2f8;font-weight:700;color:var(--ink)}.attendance-table-scroll .month-total th{font-weight:700}.attendance-table-scroll tfoot{background:#dceaf3;font-weight:700;color:var(--ink)}.attendance-table-scroll tfoot th{text-align:left;padding:18px 16px}.report-footnote{padding:12px 24px;font-size:12px;color:#708199;line-height:1.6}.report-pagination{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:18px 24px;font-size:12px;color:#708199}.report-pagination>div{display:flex;gap:8px}.report-pagination button{font-size:12px;padding:8px 12px;min-height:36px}.breakdown-table tbody th{width:55%;overflow-wrap:anywhere}.distribution-details,.report-rules{padding:22px 24px;margin:24px 0}.distribution-details summary,.report-rules summary{cursor:pointer;color:var(--ink);font-weight:600}.distribution-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:18px;align-items:start;overflow:auto}.distribution-grid td,.distribution-grid th{padding:10px;font-size:12px}.report-rules p{font-size:13px;line-height:1.7;color:#708199}.attendance-alert,.attendance-empty{padding:20px;background:#eef6f9;border-radius:10px;font-size:13px;color:#46657b}.attendance-table-scroll small{display:block;color:#708199;font-size:11px;margin-top:6px}#attendance-journal td{text-align:left;vertical-align:middle}
@media(max-width:1200px){.attendance-charts{grid-template-columns:1fr}.attendance-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.report-actions{flex-shrink:1}.period-row{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:700px){.report-filters{padding:18px}.filter-heading{display:block}.filter-heading small{display:block;margin-top:10px}.period-row,.filter-grid,.time-filters{grid-template-columns:1fr}.attendance-metrics{gap:10px}.attendance-metrics article{padding:18px}.attendance-metrics strong{font-size:26px}.report-scope,.filter-footer,.chart-toolbar,.chart-heading,.report-table .section-heading,.report-pagination{align-items:flex-start;flex-direction:column}.attendance-charts article{padding:18px}.chart-toolbar label{flex-wrap:wrap}.report-table .section-heading>input{width:100%}.report-actions button{font-size:12px;padding:10px}.distribution-grid{grid-template-columns:1fr}}
</style>
