<script setup lang="ts">
import {computed} from 'vue';
import {configuredSpec,repetitionLocked,type Config,type Spec} from './catalog';
import {subName} from './ru';
const props=defineProps<{config:Config;spec:Spec}>();
const effective=computed(()=>configuredSpec(props.spec,props.config));
const locked=(code?:string)=>repetitionLocked(props.config.tag,code,!!props.config.local);
function setField(event:Event){props.config.repeatable=(event.target as HTMLInputElement).checked;}
function setSubfield(code:string,event:Event){props.config.subfield_repeatable={...props.config.subfield_repeatable,[code]:(event.target as HTMLInputElement).checked};}
function reset(){delete props.config.repeatable;delete props.config.subfield_repeatable;}
</script>
<template>
<div class="repeat-settings">
  <label class="check-label"><input type="checkbox" :checked="effective.repeatable" :disabled="locked()" :aria-label="'Дублирование поля '+config.tag" @change="setField">Разрешить дублирование поля целиком</label>
  <small v-if="locked()">Служебное поле: повторение недоступно.</small>
  <details v-if="spec.subfields.length">
    <summary>Дублирование отдельных строк (подполей)</summary>
    <p>Включите повторение нужных строк. Выключение запрещает добавлять новые повторы; сохранённые значения остаются.</p>
    <label v-for="s in effective.subfields" :key="s.code" class="check-label">
      <input type="checkbox" :checked="s.repeatable" :disabled="locked(s.code)" :aria-label="'Дублирование подполя '+config.tag+'$'+s.code" @change="setSubfield(s.code,$event)">
      <span class="code">${{s.code}}</span>{{spec.local?s.label:subName(config.tag,s.code,s.label)}}<small v-if="locked(s.code)">Служебное</small>
    </label>
  </details>
  <button v-if="config.repeatable!==undefined&&config.repeatable!==null||Object.keys(config.subfield_repeatable||{}).length" type="button" class="repeat-reset" :aria-label="'Правила повторения по умолчанию для '+config.tag" @click="reset">По умолчанию</button>
</div>
</template>
<style scoped>
.repeat-settings{padding:10px 0;border-top:1px solid #e4ebf1}.repeat-settings summary{cursor:pointer;color:#34536a;font-size:12px;margin:8px 0}.repeat-settings p,.repeat-settings>small{font-size:12px;line-height:1.5;color:#75869b;margin:6px 0 10px}.repeat-settings .check-label{font-size:12px;margin:6px 0}.repeat-settings .check-label small{color:#75869b;margin-left:auto}.repeat-settings .repeat-reset{font-size:11px;padding:4px 9px;margin-top:6px}
</style>
