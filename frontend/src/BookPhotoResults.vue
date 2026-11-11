<script setup lang="ts">
import {computed} from 'vue';
import type {MF} from './catalog';
import {photoValues,canSelectPhotoField,type PhotoSelection} from './bookPhotos';
const props=withDefaults(defineProps<{fields:MF[];rows:PhotoSelection[];warnings:string[];disabled?:boolean;heading?:string;emptyMessage?:string}>(),{
 heading:'2. Проверьте и выберите поля',
 emptyMessage:'Сведения для полей этого рабочего листа не распознаны. Попробуйте более чёткие фотографии титульного листа и страницы с выходными данными.'
});
const emit=defineEmits<{insert:[selections:PhotoSelection[]]}>();
const selectedCount=computed(()=>props.rows.filter(r=>r.selected).length);
const selectedValid=computed(()=>props.rows.filter(r=>r.selected).every(r=>r.row.values.some(v=>v.trim())));
function selectEmpty(){for(const item of props.rows)item.selected=canSelectPhotoField(props.fields,item.row);}
</script>
<template>
 <section class="photo-results">
  <h3>{{heading}}</h3>
  <p v-for="(warning,i) in warnings" :key="i" class="photo-notice" role="status">{{warning}}</p>
  <p v-if="!rows.length">{{emptyMessage}}</p>
  <template v-else>
   <p>Ничего не выбрано автоматически. Значения можно исправить здесь. Рекомендации по тематике книги (включая факультет и специальность) проверьте отдельно. Для заполненных полей выберите замену или добавление.</p>
   <div class="photo-tools"><button type="button" @click="selectEmpty">Выбрать прочитанные данные для пустых полей</button><button type="button" @click="rows.forEach(r=>r.selected=false)">Снять выбор</button><span>Выбрано полей: {{selectedCount}}</span></div>
   <div class="photo-table-wrap"><table><thead><tr><th>Вставить</th><th>Поле / сейчас в карточке</th><th>Предложение ИИ</th></tr></thead><tbody>
    <tr v-for="item in rows" :key="item.row.key" :class="{'photo-selected':item.selected}">
     <td><input type="checkbox" v-model="item.selected" :aria-label="'Вставить '+item.row.label"></td>
     <td><strong>{{item.row.label}}</strong><div class="muted">{{item.row.key}}</div><p v-if="!photoValues(fields,item.row).length" class="muted">Не заполнено</p><p v-for="(value,i) in photoValues(fields,item.row)" :key="i" class="photo-existing">{{value}}</p>
      <label v-if="photoValues(fields,item.row).length&&item.row.repeatable">Действие<select v-model="item.mode"><option value="append">Добавить к текущим значениям</option><option value="replace">Заменить значения этого подполя</option></select></label>
      <p v-else-if="photoValues(fields,item.row).length" class="photo-replace">При выборе — заменить текущее значение</p>
     </td>
     <td><label v-for="(_,i) in item.row.values" :key="i" class="photo-value"><span class="sr-only">{{item.row.label}}: значение {{i+1}}</span><textarea v-model="item.row.values[i]" :rows="item.row.values[i].length>120?4:2" maxlength="4000"></textarea></label>
      <p v-if="item.row.basis==='inferred'" class="photo-notice">Рекомендация по содержанию — подтвердите соответствие книге</p>
      <p v-else class="muted">Прочитано с фотографии</p>
      <p v-if="item.row.vocabulary_status==='matched'" class="photo-matched">Значение из справочника</p>
      <span v-if="item.row.confidence==='uncertain'" class="photo-notice">ИИ сомневается — проверьте предложение</span>
      <p class="muted">Фото {{item.row.image_numbers.join(', ')}} · {{item.row.evidence}}</p>
      <p v-for="(warning,i) in item.row.warnings" :key="i" class="photo-notice">{{warning}}</p>
     </td>
    </tr>
   </tbody></table></div>
   <p>Изменятся только отмеченные подполя. Запись сохранится после нажатия «Сохранить запись» в карточке.</p>
   <button type="button" class="primary" :disabled="!selectedCount||!selectedValid||disabled" @click="emit('insert', rows)">Вставить выбранные поля ({{selectedCount}})</button>
  </template>
 </section>
</template>
<style scoped>
.photo-results{border-top:1px solid #e0e7ef;margin-top:22px;padding-top:22px}h3{margin-top:0}
.photo-notice{color:#805319;background:#fff8e6;padding:8px 10px;border-radius:7px;font-size:14px}
.photo-tools{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:16px 0}
.photo-table-wrap{overflow:auto}table{width:100%;table-layout:fixed}
th:first-child{width:75px}th:nth-child(2){width:32%}td{vertical-align:top;overflow-wrap:anywhere}
.photo-matched{color:#146a58;font-size:14px}.photo-selected{background:#f2faf8}.photo-value textarea{width:100%;box-sizing:border-box}
.photo-existing{white-space:pre-wrap;font-size:14px}.photo-replace{font-size:13px;color:#805319}
.sr-only{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0)}
@media(max-width:650px){.photo-table-wrap table{min-width:600px}}
</style>
