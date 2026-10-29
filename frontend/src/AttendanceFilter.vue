<script setup lang="ts">
import {computed, ref, onMounted, onUnmounted} from 'vue';
const props=defineProps<{label:string;modelValue:string[];options:{value:string;label:string}[]}>();
const emit=defineEmits<{ 'update:modelValue':[value:string[]] }>();
const search=ref(''),el=ref<HTMLDetailsElement|null>(null);
const shown=computed(()=>props.options.filter(o=>o.label.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())));
const selectedLabel=computed(()=>props.modelValue.length===1?(props.options.find(o=>o.value===props.modelValue[0])?.label||'Не указано'):props.modelValue.length?'Выбрано: '+props.modelValue.length:'Все');
function toggle(value:string){emit('update:modelValue',props.modelValue.includes(value)?props.modelValue.filter(v=>v!==value):[...props.modelValue,value]);}
function outside(e:Event){if(el.value&&!el.value.contains(e.target as Node))el.value.open=false;}
function close(){if(el.value){el.value.open=false;el.value.querySelector('summary')?.focus();}}
onMounted(()=>document.addEventListener('pointerdown',outside));
onUnmounted(()=>document.removeEventListener('pointerdown',outside));
</script>
<template>
<details ref="el" class="attendance-select" @keydown.esc.prevent="close">
  <summary :aria-label="label+': '+selectedLabel"><span>{{label}}<small>{{selectedLabel}}</small></span><span aria-hidden="true">⌄</span></summary>
  <div class="select-menu">
    <input v-model="search" :aria-label="'Поиск: '+label" placeholder="Найти значение…" @keydown.enter.prevent>
    <div class="select-actions"><button type="button" @click="emit('update:modelValue',[])">Снять выбор</button><button type="button" @click="close">Готово</button></div>
    <div class="select-options" role="group" :aria-label="label">
      <label v-for="option in shown" :key="option.value"><input type="checkbox" :checked="modelValue.includes(option.value)" @change="toggle(option.value)"><span>{{option.label}}</span></label>
      <p v-if="!shown.length">Значения не найдены.</p>
    </div>
  </div>
</details>
</template>
<style scoped>
.attendance-select{position:relative;min-width:0}.attendance-select summary{list-style:none;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 13px;border:1px solid #cfdbe7;border-radius:10px;background:white;min-height:65px;cursor:pointer;font-size:12px;color:#5c6d81}.attendance-select summary::-webkit-details-marker{display:none}.attendance-select summary>span:first-child{min-width:0}.attendance-select small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;color:#172e45;margin-top:5px}.attendance-select[open]{z-index:15}.attendance-select[open] summary{border-color:#008789;box-shadow:0 0 0 2px #dff2f2}.select-menu{position:absolute;top:calc(100% + 6px);left:0;min-width:0;width:100%;max-width:100%;background:white;border:1px solid #dbe4ef;border-radius:12px;padding:12px;box-shadow:0 12px 30px #09243e26}.select-menu>input{width:100%;margin:0}.select-actions{display:flex;justify-content:space-between;gap:8px;margin:8px 0}.select-actions button{padding:6px 9px;min-height:30px;font-size:12px}.select-options{max-height:240px;overflow:auto}.select-options label{display:flex;align-items:flex-start;gap:10px;padding:8px 4px;font-size:13px;font-weight:400;color:#22364b;cursor:pointer;line-height:1.4}.select-options label:hover{background:#eff7f8}.select-options input{width:16px;height:16px;margin:1px 0 0;flex-shrink:0;accent-color:#007e80}.select-options p{font-size:12px}.attendance-select summary:focus-visible{outline:2px solid #008789;outline-offset:2px}
</style>
