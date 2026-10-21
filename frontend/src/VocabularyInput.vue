<script setup lang="ts">
import {ref,computed,watch,nextTick} from 'vue';
const props=defineProps<{modelValue:string,placeholder?:string,ariaLabel:string,readonly?:boolean,settings?:{auto_add:boolean,allow_edit?:boolean},entries:{id:number,value:string,label:string}[]}>();
const emit=defineEmits<{'update:modelValue':[value:string],enter:[event:KeyboardEvent]}>();
const open=ref(false),query=ref(''),dialog=ref<HTMLElement|null>(null);
let returnFocus:HTMLElement|null=null;
watch(open,async value=>{if(value){returnFocus=document.activeElement as HTMLElement;await nextTick();dialog.value?.querySelector<HTMLInputElement>('input')?.focus();}else returnFocus?.focus();});
function trap(event:KeyboardEvent){if(event.key!=='Tab')return;const items=Array.from(dialog.value?.querySelectorAll<HTMLElement>('input,button:not([disabled])')||[]);const first=items[0],last=items.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}}
const filtered=computed(()=>props.entries.filter(e=>(e.value+' '+e.label).toLocaleLowerCase().includes(query.value.toLocaleLowerCase())));
function choose(value:string){emit('update:modelValue',value);open.value=false;}
</script>
<template>
<div class="lookup-input">
<input class="value-input" :value="modelValue" :readonly="readonly||(!!settings&&!settings.auto_add&&!settings.allow_edit)" :placeholder="settings&&!settings.auto_add&&!settings.allow_edit?'Выберите из справочника':placeholder" :aria-label="ariaLabel" @input="emit('update:modelValue',($event.target as HTMLInputElement).value)" @keydown.enter="emit('enter',$event)" @keydown.alt.down.prevent="open=true">
<button v-if="settings&&!readonly" type="button" class="lookup-button" :aria-label="'Справочник: '+ariaLabel" @click="query='';open=true">▾</button>
</div>
<Teleport to="body"><div v-if="open" class="vocabulary-overlay" @click.self="open=false" @keydown.esc.stop="open=false"><section ref="dialog" @keydown="trap" class="vocabulary-dialog" role="dialog" aria-modal="true" :aria-label="'Справочник: '+ariaLabel"><div class="section-heading"><h2>{{ariaLabel}}</h2><button aria-label="Закрыть справочник" @click="open=false">×</button></div><input v-model="query" aria-label="Поиск значения в справочнике" placeholder="Найти код или название"><p v-if="settings?.auto_add">Можно выбрать значение здесь или ввести новое в строке. Оно попадёт в справочник после сохранения записи.</p><p v-if="settings?.allow_edit&&!settings.auto_add">После выбора значение можно изменить в строке. Изменение сохранится только в этой записи, справочник останется прежним.</p><div class="vocabulary-options"><button v-for="e in filtered" :key="e.id" @click="choose(e.value)"><strong>{{e.value}}</strong><span>{{e.label}}</span></button><p v-if="!filtered.length">{{entries.length?'Ничего не найдено':'Справочник пока пуст'}}</p></div><div class="actions"><button @click="choose('')">Очистить значение</button><button @click="open=false">Отмена</button></div></section></div></Teleport>
</template>
