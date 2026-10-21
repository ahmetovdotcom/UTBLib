<script setup lang="ts">
import {ref,onMounted} from 'vue';
const props=defineProps<{api:(path:string,method?:string,body?:any)=>Promise<any>}>();
defineEmits<{record:[id:number]}>();
const from=ref(''),to=ref(''),employee=ref(''),action=ref(''),offset=ref(0),data=ref<any>(null),busy=ref(false),error=ref('');
let request=0;
async function load(reset=true){if(reset)offset.value=0;const token=++request;busy.value=true;error.value='';try{
 const q=new URLSearchParams({offset:String(offset.value)});if(from.value)q.set('date_from',from.value);if(to.value)q.set('date_to',to.value);if(employee.value)q.set('user_id',employee.value);if(action.value)q.set('action',action.value);
 const result=await props.api('/statistics/staff?'+q);if(token===request)data.value=result;
}catch(e:any){if(token===request){error.value=e.message;data.value=null;}}finally{if(token===request)busy.value=false;}}
function date(value:string){return new Date(value).toLocaleString('ru-RU',{timeZone:'Asia/Almaty'});}
onMounted(()=>load());
</script>
<template>
<section class="staff-stats">
<header><h1>Работа сотрудников</h1><p>Создание и редактирование записей каталога</p></header>
<p class="stats-note">Учёт ведётся с момента установки раздела статистики. Старые действия и импорт из MARCSQL не включены. Сотрудник определяется по учётной записи при сохранении.</p>
<form class="stats-filters" @submit.prevent="load()">
<label>С даты<input type="date" v-model="from"></label><label>По дату<input type="date" v-model="to"></label>
<label>Сотрудник<select v-model="employee" @change="load()"><option value="">Все сотрудники</option><option v-for="u in data?.employees||[]" :key="u.actor_id" :value="String(u.actor_id)">{{u.name}}{{u.deleted?' (удалён)':''}}</option></select></label>
<button :disabled="busy">{{busy?'Загрузка…':'Показать'}}</button><button type="button" @click="from='';to='';employee='';action='';load()">За всё время</button>
</form>
<p v-if="error" role="alert">{{error}}</p>
<template v-if="data">
<div class="stats-cards"><article><strong>{{data.summary.created}}</strong><span>Новых записей</span></article><article><strong>{{data.summary.updated}}</strong><span>Изменённых записей</span></article><article><strong>{{data.summary.processed}}</strong><span>Всего уникальных записей</span></article></div>
<p class="stats-note">{{employee?'Показатели выбранного сотрудника.':'Общие показатели всех сотрудников.'}} Повторные правки одной записи считаются один раз. Созданная и затем изменённая запись может входить в обе категории. Сохранение без изменения данных не учитывается. Даты — по времени Алматы.</p>
<h2>По сотрудникам</h2><div class="stats-table"><table><thead><tr><th>Сотрудник</th><th>Создал</th><th>Изменил</th><th>Уникальных записей</th></tr></thead><tbody><tr v-for="u in data.employees" :key="u.actor_id"><td><button class="staff-name" @click="employee=String(u.actor_id);load()">{{u.name}}</button><small v-if="u.deleted"> (удалён)</small></td><td>{{u.created}}</td><td>{{u.updated}}</td><td>{{u.processed}}</td></tr><tr v-if="!data.employees.length"><td colspan="4">За этот период действий пока нет.</td></tr></tbody></table></div>
<p class="stats-note">Если одну книгу изменяли несколько сотрудников, она учитывается у каждого, а в общем итоге — один раз.</p>
<div class="stats-filters"><h2>Обработанные записи</h2><label>Действие<select v-model="action" @change="load()"><option value="">Все действия</option><option value="created">Создание</option><option value="updated">Изменение</option></select></label></div>
<div class="stats-table"><table><thead><tr><th>Последнее действие</th><th>Сотрудник</th><th>Книга</th><th>Действие</th><th>Число сохранений</th></tr></thead><tbody><tr v-for="r in data.rows" :key="`${r.actor_id}-${r.record_id}-${r.action}`"><td>{{date(r.at)}}</td><td>{{r.name}}</td><td><button v-if="r.exists" class="staff-name" @click="$emit('record',r.record_id)">{{r.title}}</button><span v-else>{{r.title}} (запись удалена)</span><small> № {{r.record_id}}</small></td><td>{{r.action==='created'?'Создание':'Изменение'}}</td><td>{{r.operations}}</td></tr><tr v-if="!data.rows.length"><td colspan="5">Нет записей для выбранных условий.</td></tr></tbody></table></div>
<div class="stats-filters"><button :disabled="busy||offset===0" @click="offset-=30;load(false)">Назад</button><span>{{data.total?offset+1:0}}–{{Math.min(offset+30,data.total)}} из {{data.total}}</span><button :disabled="busy||offset+30>=data.total" @click="offset+=30;load(false)">Далее</button></div>
</template></section>
</template>
<style scoped>
.staff-stats{padding:24px;max-width:1500px}.stats-note{color:#58677b;line-height:1.6}.stats-filters{display:flex;align-items:end;gap:16px;flex-wrap:wrap;margin:20px 0}.stats-filters label{display:grid;gap:6px}.stats-cards{display:flex;gap:18px;flex-wrap:wrap}.stats-cards article{background:white;border:1px solid #dce3ed;border-radius:12px;padding:22px;flex:1;min-width:180px;display:grid;gap:8px}.stats-cards strong{font-size:32px;color:#235ca8}.stats-table{overflow-x:auto;background:white;border:1px solid #dce3ed;border-radius:10px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid #e5eaf0}th{background:#f3f6fa}.staff-name{color:#235ca8;background:transparent;border:0;text-align:left;text-decoration:underline;cursor:pointer}small{color:#65758a}input,select{padding:9px;max-width:300px}
</style>
