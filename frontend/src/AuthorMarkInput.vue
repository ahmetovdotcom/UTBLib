<script setup lang="ts">
import {computed, nextTick, ref, watch} from 'vue';
import VocabularyInput from './VocabularyInput.vue';
import {canInsertAuthorMark, formatAuthorMark, lookupAuthorMark, tableRows} from './authorMarks';
import type {Alphabet, AuthorChoice, AuthorTable, Separator} from './authorMarks';

const props=defineProps<{modelValue:string; placeholder?:string; ariaLabel:string; readonly?:boolean;
  settings?:{auto_add:boolean; allow_edit?:boolean}; entries:{id:number;value:string;label:string}[];
  author:string; title:string}>();
const emit=defineEmits<{'update:modelValue':[value:string]; enter:[event:KeyboardEvent]}>();
const dialog=ref<HTMLDialogElement|null>(null), termInput=ref<HTMLInputElement|null>(null);
const tables=ref<AuthorTable[]>([]), loading=ref(false), error=ref(''), query=ref('');
const alphabet=ref<Alphabet>('cyrillic'), letter=ref('А'), separator=ref<Separator>('auto');
const chosen=ref<AuthorChoice|null>(null), verified=ref(false), open=ref(false);
let returnFocus:HTMLElement|null=null;
const result=computed(()=>lookupAuthorMark(tables.value,query.value));
const letters=computed(()=>tables.value.filter(t=>t.alphabet===alphabet.value).map(t=>t.letter));
const table=computed(()=>tables.value.find(t=>t.alphabet===alphabet.value&&t.letter===letter.value));
const rows=computed(()=>table.value?tableRows(table.value,table.value.letter==='I'&&/^\s*[Jj]/.test(query.value)?'J':table.value.letter):[]);
const mark=computed(()=>chosen.value?formatAuthorMark(chosen.value,separator.value):'');
const allowed=computed(()=>canInsertAuthorMark(mark.value,props.modelValue,props.settings,props.entries));
const needsVerification=computed(()=>!!chosen.value?.review||!!chosen.value?.special);
const canApply=computed(()=>!!chosen.value&&!props.readonly&&allowed.value&&(!needsVerification.value||verified.value));
const source=computed(()=>`/author-tables/${chosen.value?.alphabet||alphabet.value}.pdf#page=${chosen.value?.page||table.value?.page||1}`);
function select(row:AuthorChoice){chosen.value=row;verified.value=false;}
async function scrollToResult(){
  await nextTick();
  if(!open.value)return;
  const number=chosen.value?.number??result.value.anchor;
  const list=dialog.value?.querySelector<HTMLElement>('.author-table-rows');
  const row=list?.querySelector<HTMLElement>(`[data-number="${number}"]`);
  if(list&&row)list.scrollTop+=row.getBoundingClientRect().top-list.getBoundingClientRect().top-(list.clientHeight-row.clientHeight)/2;
}
watch(result,r=>{
  chosen.value=r.choice;verified.value=false;
  if(r.alphabet){
    alphabet.value=r.alphabet;
    if(tables.value.some(t=>t.alphabet===r.alphabet&&t.letter===r.letter))letter.value=r.letter;
    else letter.value=letters.value[0]||'А';
  }
  void scrollToResult();
});
function browse(){chosen.value=null;verified.value=false;query.value='';}
function changeAlphabet(){browse();letter.value=letters.value[0]||'А';}
async function show(){
  if(props.readonly)return;
  returnFocus=document.activeElement as HTMLElement;
  open.value=true;dialog.value?.showModal();loading.value=true;error.value='';
  try {
    if(!tables.value.length)tables.value=(await import('./data/authorTables.json')).default as AuthorTable[];
    query.value='';await nextTick();query.value=props.author.trim()||props.title.trim()||props.modelValue;
    loading.value=false;await nextTick();termInput.value?.focus();termInput.value?.select();await scrollToResult();
  } catch {error.value='Не удалось загрузить таблицы. Закройте окно и попробуйте ещё раз.';}
  finally {loading.value=false;}
}
function close(){dialog.value?.close();}
function closed(){open.value=false;returnFocus?.focus();}
function apply(){if(canApply.value){emit('update:modelValue',mark.value);close();}}
</script>

<template>
<div class="author-mark-input">
  <VocabularyInput :modelValue="modelValue" :placeholder="placeholder" :ariaLabel="ariaLabel" :readonly="readonly" :settings="settings" :entries="entries" @update:modelValue="emit('update:modelValue',$event)" @enter="emit('enter',$event)" />
  <button v-if="!readonly" type="button" class="author-table-open" :aria-label="'Авторские таблицы: '+ariaLabel" @click="show">Авторские таблицы</button>
</div>
<Teleport to="body">
<dialog ref="dialog" class="author-table-dialog" aria-label="Подбор авторского знака" @close="closed" @contextmenu.stop @click="($event.target===dialog)&&close()">
  <div class="author-table-content">
    <header><div><h2>Авторский знак</h2><p>Двузначные авторские таблицы Л. Б. Хавкиной</p></div><button type="button" aria-label="Закрыть авторские таблицы" @click="close">×</button></header>
    <p v-if="error" role="alert" class="author-warning">{{error}}</p>
    <p v-if="loading" role="status">Загрузка таблиц…</p>
    <template v-else-if="!error">
      <label class="author-query-label">Фамилия автора, начало заглавия или знак
        <input ref="termInput" v-model="query" type="text" autocomplete="off" placeholder="Например, Иванов, March или И20" @keydown.enter.prevent>
      </label>
      <div class="author-shortcuts"><button type="button" :disabled="!author.trim()" @click="query=author">Взять автора</button><button type="button" :disabled="!title.trim()" @click="query=title">Взять заглавие</button></div>
      <p class="author-hint">Начните с фамилии. Если автора нет — с первого слова заглавия. При выборе строки значение в карточке ещё не меняется.</p>
      <div class="author-controls">
        <label>Таблица<select aria-label="Таблица" v-model="alphabet" @change="changeAlphabet"><option value="cyrillic">Кириллица</option><option value="latin">Латиница</option></select></label>
        <label>Буква<select aria-label="Буква" v-model="letter" @change="browse"><option v-for="l in letters" :key="l" :value="l">{{l==='I'?'I / J':l}}</option></select></label>
        <label>Разделитель<select aria-label="Разделитель" v-model="separator"><option value="auto">По правилам таблицы</option><option value="none">Без разделителя</option><option value="space">Пробел</option><option value="hyphen">Дефис</option></select></label>
      </div>
      <div class="author-result" aria-live="polite"><div><small>Авторский знак</small><strong>{{mark||'Не выбран'}}</strong></div><div><p>{{result.message}}</p><p v-if="chosen">Строка: <b>{{chosen.term}}</b> · страница {{chosen.page}}</p></div></div>
      <div class="author-source"><span>Выберите строку таблицы</span><a :href="source" target="_blank" rel="noopener">Открыть исходный PDF ↗</a></div>
      <div class="author-table-rows" aria-label="Строки авторской таблицы">
        <button v-for="row in rows" :key="row.number!" type="button" :data-number="row.number" :class="{selected:chosen?.number===row.number&&chosen?.alphabet===row.alphabet&&chosen?.letter===row.letter}" :aria-pressed="chosen?.number===row.number&&chosen?.alphabet===row.alphabet&&chosen?.letter===row.letter" @click="select(row)">
          <strong>{{formatAuthorMark(row,separator)}}</strong><span>{{row.term}}</span><small v-if="row.review">Сверить с PDF</small><small v-else-if="row.special">Специальный знак</small>
        </button>
      </div>
      <label v-if="needsVerification" class="author-verify"><input v-model="verified" type="checkbox">{{chosen?.review?'Строка в исходном PDF неоднозначна. Я сверил(а) знак по оригиналу.':'Этот специальный знак относится именно к выбранному автору или организации.'}}</label>
      <p v-if="mark&&!allowed" class="author-warning">Знака «{{mark}}» нет в разрешённых значениях этого поля. Администратор может добавить его в справочник или разрешить редактирование значений в настройках поля.</p>
      <p class="author-hint">Таблицы содержат две цифры. Редкие буквы и неоднозначные строки требуют ручной проверки. Ручной ввод в карточке остаётся доступен согласно настройкам поля.</p>
      <footer><span>Сейчас в карточке: <b>{{modelValue||'не заполнено'}}</b></span><button type="button" @click="close">Отмена</button><button type="button" class="primary" :disabled="!canApply" @click="apply">Вставить{{mark?' '+mark:''}}</button></footer>
    </template>
  </div>
</dialog>
</Teleport>
</template>

<style scoped>
.author-mark-input{display:flex;align-items:center;gap:8px;flex:1;min-width:0}.author-mark-input :deep(.lookup-input){flex:1;min-width:0}.author-table-open{white-space:nowrap;font-size:12px;padding:8px 11px}
.author-table-dialog{width:min(760px,calc(100vw - 32px));max-height:calc(100dvh - 32px);padding:0;border:1px solid #dce5ee;border-radius:20px;color:#19334b;background:#fff;box-shadow:0 24px 70px #0b263b38}.author-table-dialog::backdrop{background:#10263c77}.author-table-content{padding:24px}.author-table-dialog header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.author-table-dialog h2{font-size:24px;margin:0;color:#082b45}.author-table-dialog header p{margin:5px 0 20px;color:#667b92}.author-table-dialog button,.author-table-dialog select,.author-table-dialog input[type=text]{font:inherit;border:1px solid #cad7e3;border-radius:9px;background:#fff;color:inherit;box-sizing:border-box}.author-table-dialog button{padding:9px 14px;cursor:pointer}.author-table-dialog button:disabled{opacity:.5;cursor:default}.author-table-dialog :focus-visible{outline:2px solid #00858c;outline-offset:3px}.author-table-dialog label{font-weight:600;font-size:14px}.author-query-label{display:block}.author-query-label input{display:block;width:100%;margin:8px 0;padding:11px 12px}.author-shortcuts{display:flex;gap:8px}.author-shortcuts button{font-size:13px}.author-hint{font-size:13px;line-height:1.5;color:#667b92;margin:10px 0 16px}.author-controls{display:grid;grid-template-columns:1fr 90px 1.3fr;gap:12px}.author-controls select{display:block;padding:9px;margin-top:6px;width:100%}.author-result{display:flex;align-items:center;gap:24px;background:#f0f8f8;border:1px solid #d9e9e9;border-radius:12px;margin:16px 0;padding:14px}.author-result small{display:block;color:#61778c;white-space:nowrap}.author-result strong{font-size:26px;white-space:nowrap;color:#075d66}.author-result p{font-size:13px;line-height:1.5;margin:0}.author-source{display:flex;justify-content:space-between;gap:10px;font-size:13px;margin:14px 0 8px}.author-source a{color:#087b83}.author-table-rows{max-height:210px;overflow:auto;border:1px solid #dce5ee;border-radius:10px;overscroll-behavior:contain}.author-table-rows button{width:100%;display:grid;grid-template-columns:90px 1fr auto;text-align:left;gap:10px;align-items:center;border:0;border-bottom:1px solid #edf1f5;border-radius:0;padding:10px 14px}.author-table-rows button:hover{background:#f4f8fa}.author-table-rows button.selected{background:#e5f3f3;box-shadow:inset 3px 0 #00858c}.author-table-rows small{color:#8b6118;font-size:11px}.author-table-rows strong{font-variant-numeric:tabular-nums}.author-verify{display:flex;align-items:flex-start;gap:8px;margin:14px 0;padding:12px;background:#fff8e8;border-radius:9px;line-height:1.5}.author-verify input{margin-top:3px}.author-warning{font-size:13px;line-height:1.5;background:#fff8e8;color:#81591d;padding:12px;border-radius:10px}.author-table-dialog footer{display:flex;align-items:center;gap:10px;border-top:1px solid #e2eaf1;padding-top:16px}.author-table-dialog footer span{margin-right:auto;font-size:12px;color:#667b92}.author-table-dialog .primary{background:#082b45;border-color:#082b45;color:#fff;font-weight:600}
@media(max-width:600px){.author-mark-input{flex-wrap:wrap}.author-mark-input :deep(.lookup-input){flex-basis:100%}.author-table-content{padding:16px}.author-controls{grid-template-columns:1fr 80px}.author-controls label:last-child{grid-column:1/-1}.author-result{align-items:flex-start;gap:12px}.author-table-dialog footer{flex-wrap:wrap}.author-table-dialog footer span{width:100%}.author-table-rows button{grid-template-columns:65px 1fr}.author-table-rows small{grid-column:2}}
</style>
