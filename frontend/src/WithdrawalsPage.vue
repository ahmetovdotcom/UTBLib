<script setup lang="ts">
import {authStorage} from "./authStorage";
import {ref,onMounted} from 'vue';
const props=defineProps<{canCreate:boolean,api:(path:string,method?:string,body?:unknown)=>Promise<any>}>();
const inventory=ref(''),copy=ref<any>(null),draft=ref<any>(null),pending=ref<any>(null),busy=ref(false),error=ref(''),notice=ref(''),rows=ref<any[]>([]),total=ref(0),offset=ref(0);
function today(){const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
const status=(s:string)=>({active:'В фонде',withdrawn:'Списан',cancelled:'Отменён'}[s]||s);
async function load(){const data=await props.api('/withdrawals?offset='+offset.value);rows.value=data.items;total.value=data.total;}
async function run(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn();}catch(e){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}}
async function find(){await run(async()=>{copy.value=null;draft.value=null;notice.value='';const found=await props.api('/copies/lookup?inventory_number='+encodeURIComponent(inventory.value.trim()));copy.value=found;if(found.status==='active')draft.value={request_key:crypto.randomUUID(),copy_id:found.id,version:found.version,withdrawn_on:today(),act_number:'',reason:'',note:''};});}
function forget(){authStorage.removeItem('pending-withdrawal');pending.value=null;}
async function post(body:any){pending.value=body;authStorage.setItem('pending-withdrawal',JSON.stringify(body));let result;try{result=await props.api('/withdrawals','POST',body);}catch(e){const status=(e as any).status;if(status>=400&&status<500)forget();throw e;}forget();notice.value=`Экземпляр ${result.snapshot.inventory_number} списан. Акт: ${result.act_number}.`;copy.value=null;draft.value=null;offset.value=0;await load();}
onMounted(()=>{try{pending.value=JSON.parse(authStorage.getItem('pending-withdrawal')||'null');}catch{}run(load);});
</script>
<template>
<section class="withdrawals-page">
<div class="page-heading"><div><div class="eyebrow">УЧЁТ ФОНДА</div><h1>Списание</h1><p>Найдите экземпляр по точному инвентарному номеру и оформите списание.</p></div><button :disabled="busy" @click="run(load)">Обновить журнал</button></div>
<div v-if="pending&&canCreate" class="pending-note"><p>Не получено подтверждение списания. Повтор безопасен и не спишет экземпляр дважды.</p><button :disabled="busy" @click="run(()=>post(pending))">Проверить и восстановить списание</button></div>
<p v-if="error" role="alert" class="inline-error">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
<form v-if="canCreate" class="card search-bar" @submit.prevent="find"><label>Инвентарный номер<input v-model="inventory" required maxlength="100" placeholder="Введите или отсканируйте номер"></label><button :disabled="busy||!!pending">Найти экземпляр</button></form>
<section v-if="copy" class="card holdings"><h2>{{copy.title}}</h2><p><strong>{{copy.inventory_number}}</strong> · {{status(copy.status)}} · {{copy.sigla||'Сигла не указана'}}</p><p>Цена: {{copy.unit_price===null?'не указана':copy.unit_price+' '+copy.currency}} · Запись №{{copy.record_id}}</p>
<form v-if="draft" @submit.prevent="run(()=>post(draft))"><fieldset :disabled="busy||!!pending" class="plain-fieldset acquisition-grid"><label>Дата списания<input type="date" v-model="draft.withdrawn_on" required :max="today()" :min="copy.received_on||undefined"></label><label>Номер акта<input v-model="draft.act_number" required maxlength="255"></label><label>Причина списания<input v-model="draft.reason" required maxlength="4000" placeholder="Например, ветхость или утрата"></label><label>Примечание<textarea v-model="draft.note" maxlength="4000"></textarea></label></fieldset><p>Будет списан только этот экземпляр. Описание книги останется в каталоге, а сведения об экземпляре — в истории.</p><button class="danger-button" :disabled="busy||!!pending">Подтвердить списание экземпляра</button></form>
<p v-else>Повторное списание недоступно: экземпляр уже исключён из действующего фонда.</p></section>
<section class="card holdings"><h2>Журнал списания</h2><p>Всего: {{total}}</p><div class="table-wrap"><table><thead><tr><th>Дата / акт</th><th>Инвентарный номер</th><th>Книга</th><th>Стоимость</th><th>Причина / примечание</th></tr></thead><tbody><tr v-for="r in rows" :key="r.id"><td>{{r.withdrawn_on}}<small class="block">{{r.act_number}}</small></td><td>{{r.snapshot.inventory_number}}</td><td>{{r.snapshot.title}}</td><td>{{r.snapshot.unit_price===null?'Не указана':r.snapshot.unit_price+' '+r.snapshot.currency}}</td><td>{{r.reason}}<small class="block">{{r.note}}</small></td></tr></tbody></table></div><p v-if="!total&&!busy">Списаний пока нет.</p><div class="table-footer"><button :disabled="busy||offset===0" @click="offset-=20;run(load)">Предыдущие списания</button><button :disabled="busy||offset+rows.length>=total" @click="offset+=20;run(load)">Следующие списания</button></div></section>
</section>
</template>
