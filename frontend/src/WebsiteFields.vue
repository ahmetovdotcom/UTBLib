<script setup lang="ts">
import {computed} from 'vue';
defineOptions({name:'WebsiteFields'});
const props=defineProps<{schema:any,modelValue:any,locale:string,depth?:number}>();
const emit=defineEmits<{(e:'update:modelValue',value:any):void}>();
const fields=computed(()=>Object.entries(props.schema.fields||{}).filter(([,n]:any)=>!n.hidden) as [string,any][]);
function blank(s:any):any{if(s.type==='locales')return {...Object.fromEntries(['ru','kk','en'].map(l=>[l,blank(s.item)])),...Object.fromEntries(Object.entries(s.fields||{}).map(([k,v])=>[k,blank(v)]))};if(s.type==='object')return Object.fromEntries(Object.entries(s.fields).map(([k,v])=>[k,blank(v)]));if(s.type==='list')return [];if(s.type==='tuple')return s.items.map(blank);return s.nullable?null:'';}
function set(key:string|number,value:any){const result:any=Array.isArray(props.modelValue)?[...props.modelValue]:{...props.modelValue};result[key]=value;emit('update:modelValue',result);}
function remove(index:number){emit('update:modelValue',props.modelValue.filter((_:any,i:number)=>i!==index));}
function move(index:number,delta:number){const rows=[...props.modelValue];[rows[index],rows[index+delta]]=[rows[index+delta],rows[index]];emit('update:modelValue',rows);}
</script>
<template>
 <div class="website-fields">
  <template v-if="schema.type==='object'||schema.type==='locales'">
   <template v-for="[key,child] in fields" :key="key">
    <details v-if="['object','locales','list'].includes(child.type)" class="website-group" :open="(depth||0)>0"><summary>{{child.label}}</summary><WebsiteFields :schema="child" :model-value="modelValue?.[key]" :locale="locale" :depth="(depth||0)+1" @update:model-value="set(key,$event)"/></details>
    <WebsiteFields v-else :schema="child" :model-value="modelValue?.[key]" :locale="locale" @update:model-value="set(key,$event)"/>
   </template>
   <WebsiteFields v-if="schema.type==='locales'" :schema="schema.item" :model-value="modelValue?.[locale]" :locale="locale" :depth="depth" @update:model-value="set(locale,$event)"/>
  </template>
  <template v-else-if="schema.type==='list'">
   <div v-for="(row,index) in modelValue" :key="index" class="website-row">
    <div class="website-row-tools"><strong>Запись {{index+1}}</strong><button type="button" :disabled="index===0" @click="move(index,-1)" aria-label="Переместить выше">↑</button><button type="button" :disabled="index===modelValue.length-1" @click="move(index,1)" aria-label="Переместить ниже">↓</button><button type="button" @click="remove(index)">Удалить строку</button></div>
    <WebsiteFields :schema="schema.item" :model-value="row" :locale="locale" :depth="(depth||0)+1" @update:model-value="set(index,$event)"/>
   </div>
   <p v-if="!modelValue?.length" class="muted">Список пуст. На сайте записи этого списка не показываются.</p>
   <button v-if="(modelValue?.length||0)<schema.max" type="button" @click="emit('update:modelValue',[...(modelValue||[]),blank(schema.item)])">+ Добавить строку</button>
  </template>
  <template v-else-if="schema.type==='tuple'"><template v-for="(child,index) in schema.items" :key="index"><WebsiteFields v-if="!child.hidden" :schema="child" :model-value="modelValue[index]" :locale="locale" @update:model-value="set(index,$event)"/></template></template>
  <label v-else>{{schema.label||'Текст'}}
   <textarea v-if="schema.multiline" :value="modelValue??''" :maxlength="schema.max" rows="3" @input="emit('update:modelValue',($event.target as HTMLTextAreaElement).value)"/>
   <input v-else :type="schema.format==='email'?'email':'text'" :value="modelValue??''" :maxlength="schema.max" @input="emit('update:modelValue',($event.target as HTMLInputElement).value)">
   <small v-if="schema.format==='path'">Ссылка внутри сайта: /contacts или #general.</small><small v-else-if="schema.format==='link'">Ссылка https://… или путь внутри сайта /…</small>
  </label>
 </div>
</template>
<style scoped>
.website-fields label{display:flex;flex-direction:column;gap:7px;margin:0 0 18px;font-weight:600}.website-fields input,.website-fields textarea{width:100%;box-sizing:border-box}.website-fields small,.muted{font-weight:400;color:#66758b}.website-group{border:1px solid #dce5ed;border-radius:12px;margin:12px 0;padding:16px}.website-group summary{font-weight:700;cursor:pointer}.website-group[open]>summary{margin-bottom:18px}.website-row{padding:16px;border:1px solid #dce5ed;border-radius:10px;margin:10px 0;background:#f8fafc}.website-row-tools{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:14px}.website-row-tools strong{margin-right:auto}
</style>
