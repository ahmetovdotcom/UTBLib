<script setup lang="ts">
import {photoCost,type PhotoUsage} from './bookPhotos';
defineProps<{usage:PhotoUsage}>();
const tokens=(value:number|null)=>value===null?'Нет данных':value.toLocaleString('ru-RU');
</script>
<template>
<section class="photo-usage" aria-labelledby="photo-usage-title" aria-live="polite">
 <div class="usage-heading"><h3 id="photo-usage-title">Расход на распознавание</h3><span>Модель: <strong>{{usage.model}}</strong></span></div>
 <dl class="usage-counters">
  <div><dt>Входящие токены</dt><dd>{{tokens(usage.input_tokens)}}</dd></div>
  <div><dt>Исходящие токены</dt><dd>{{tokens(usage.output_tokens)}}</dd></div>
  <div><dt>Всего токенов</dt><dd>{{tokens(usage.total_tokens)}}</dd></div>
  <div><dt>Примерная стоимость, USD</dt><dd>{{usage.estimated_cost_usd!==null?'≈ ':''}}{{photoCost(usage.estimated_cost_usd)}}</dd></div>
 </dl>
 <p>За последний запрос. Повторные распознавания оплачиваются отдельно.</p>
 <details><summary>Как считается расход</summary>
  <p>Входящие токены включают фотографии, инструкции и справочники. Исходящие — ответ и внутренние рассуждения модели.</p>
  <ul>
   <li>Входящие из кэша: {{tokens(usage.cached_input_tokens)}}.</li>
   <li>Входящие, записанные в кэш: {{tokens(usage.cache_write_tokens)}}.</li>
   <li>Из исходящих — рассуждения: {{tokens(usage.reasoning_tokens)}}.</li>
  </ul>
  <p>Эти части уже входят в общие счётчики и не добавляются к ним повторно.</p>
  <p>{{usage.cost_note}} <template v-if="usage.pricing_date">Тариф проверен {{usage.pricing_date.split('-').reverse().join('.')}}. <a :href="usage.pricing_url!" target="_blank" rel="noopener noreferrer">Тариф модели</a>.</template></p>
  <p>Окончательные расходы доступны в <a href="https://platform.openai.com/usage" target="_blank" rel="noopener noreferrer">OpenAI Usage</a>.</p>
 </details>
</section>
</template>
<style scoped>
.photo-usage{margin-top:22px;padding:20px;background:#f3f8fa;border:1px solid #dce8ee;border-radius:14px;color:#203247}
.usage-heading{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}.usage-heading h3{margin:0}.usage-heading span{overflow-wrap:anywhere;font-size:14px}
.usage-counters{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}.usage-counters div{background:white;border:1px solid #dce8ee;border-radius:10px;padding:14px}
dt{font-size:13px;color:#52677c}dd{margin:8px 0 0;font-weight:700;font-size:22px;overflow-wrap:anywhere}
p,li,summary{font-size:14px;line-height:1.5}summary{cursor:pointer;color:#146a68}a{color:#146a68}
@media(max-width:700px){.usage-counters{grid-template-columns:repeat(2,minmax(0,1fr))}.photo-usage{padding:14px}dd{font-size:19px}}
</style>
