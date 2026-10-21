<script setup lang="ts">
import {ref} from 'vue';
import type {MF} from './catalog';
import {targets,type IsbnRow} from './isbn';
const props=defineProps<{api:(path:string)=>Promise<any>,fields:MF[]}>();
const emit=defineEmits<{insert:[rows:IsbnRow[],selected:boolean[]]}>();
const dialog=ref<HTMLDialogElement>(),isbn=ref(''),busy=ref(false),error=ref(''),warnings=ref<string[]>([]),items=ref<any[]>([]),searched=ref(false),selected=ref<boolean[][]>([]);
function open(){isbn.value=props.fields.find(f=>f.tag==='020')?.subfields?.find(s=>s.code==='a')?.value||'';items.value=[];searched.value=false;error.value='';warnings.value=[];dialog.value?.showModal();}
async function search(){if(busy.value)return;busy.value=true;error.value='';items.value=[];warnings.value=[];searched.value=false;try{const data=await props.api('/isbn-lookup?isbn='+encodeURIComponent(isbn.value));items.value=data.items;warnings.value=data.warnings;selected.value=items.value.map(item=>targets(item.rows,props.fields).map(t=>!t.existing.trim()));searched.value=true;}catch(e){error.value=e instanceof Error?e.message:String(e);}finally{busy.value=false;}}
function insert(i:number){emit('insert',items.value[i].rows,selected.value[i]);dialog.value?.close();}
</script>
<template>
<button type="button" @click="open">Найти по ISBN</button>
<dialog ref="dialog" class="isbn-dialog" aria-labelledby="isbn-title" @cancel="busy&&$event.preventDefault()">
 <div class="isbn-heading"><h2 id="isbn-title">Поиск книги по ISBN</h2><button :disabled="busy" @click="dialog?.close()" aria-label="Закрыть поиск">✕</button></div>
 <p>Найдите издание, сверьте сведения с книгой и отметьте строки для вставки. Запись сохранится только после нажатия «Сохранить запись».</p>
 <form class="isbn-search" @submit.prevent="search"><label>ISBN<input v-model="isbn" autofocus required maxlength="40" placeholder="978-… или ISBN-10" :disabled="busy"></label><button class="primary" :disabled="busy">{{busy?'Ищем…':'Найти'}}</button></form>
 <p v-if="error" role="alert">{{error}}</p><p v-for="warning in warnings" role="status">{{warning}}</p>
 <p v-if="searched&&!items.length">Совпадений по ISBN не найдено в ответивших источниках. Проверьте номер или заполните запись вручную.</p>
 <article v-for="(item,i) in items" :key="i" class="isbn-result"><h3>{{item.title}}</h3><a :href="item.url" target="_blank" rel="noopener noreferrer">{{item.source}} ↗</a>
 <p>Проверьте авторов, издание, год и объём. Сведения об ответственности заполняются отдельно по книге.</p>
 <table><thead><tr><th>Вставить</th><th>Поле</th><th>Найденное значение</th><th>Сейчас в форме</th></tr></thead><tbody><tr v-for="(t,j) in targets(item.rows,fields)" :key="j"><td><input type="checkbox" v-model="selected[i][j]" :aria-label="'Вставить '+t.row.label"></td><td>{{t.row.tag}}${{t.row.code}} · {{t.row.label}}</td><td>{{t.row.value}}</td><td>{{t.existing||'—'}}</td></tr></tbody></table>
 <p>Выбранные строки заменят соответствующие значения в форме. Остальные поля сохранятся.</p><button class="primary" :disabled="!selected[i]?.some(Boolean)" @click="insert(i)">Вставить выбранные данные</button>
 </article>
</dialog>
</template>
<style scoped>
.isbn-dialog{width:min(960px,94vw);max-height:88vh;overflow:auto;border:1px solid #d9e0ea;border-radius:14px;padding:26px;color:#263446}.isbn-dialog::backdrop{background:#15233b70}.isbn-heading,.isbn-search{display:flex;align-items:center;justify-content:space-between;gap:16px}.isbn-search{margin:20px 0;align-items:end}.isbn-search label{flex:1}.isbn-result{border-top:1px solid #e1e7ef;margin-top:22px;padding-top:8px}.isbn-result table{margin:16px 0}.isbn-result td{overflow-wrap:anywhere}.isbn-result>.primary{margin-top:12px}
</style>
