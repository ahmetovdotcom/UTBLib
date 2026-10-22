<script setup lang="ts">
import {onMounted,onBeforeUnmount,ref,nextTick} from 'vue';
const props=defineProps<{ticket:{brand:string,full_name:string,category:string,department:string,barcode:string,ticket_number:string,svg:string,qr_svg:string}}>();
const emit=defineEmits<{close:[]}>();
const sheet=ref<HTMLElement>(),printButton=ref<HTMLButtonElement>();
const priorFocus=document.activeElement as HTMLElement|null;
const priorTitle=document.title;
function print(){window.print();}
function key(event:KeyboardEvent){
 if(event.key==='Escape'){event.preventDefault();emit('close');}
 if(event.key==='Tab'){
  const buttons=sheet.value?.querySelectorAll<HTMLButtonElement>('button');if(!buttons?.length)return;
  if(event.shiftKey&&document.activeElement===buttons[0]){event.preventDefault();buttons[buttons.length-1].focus();}
  else if(!event.shiftKey&&document.activeElement===buttons[buttons.length-1]){event.preventDefault();buttons[0].focus();}
 }
}
onMounted(async()=>{
 document.title='Читательский билет — '+props.ticket.ticket_number;
 document.addEventListener('keydown',key);
 await nextTick();printButton.value?.focus();
 // Keep long names/departments within the same physical card dimensions.
 for(const element of Array.from(sheet.value?.querySelectorAll<HTMLElement>('[data-fit]')||[])){
  let size=parseFloat(getComputedStyle(element).fontSize);
  while((element.scrollHeight>element.clientHeight+1||element.scrollWidth>element.clientWidth+1)&&size>6){size-=0.25;element.style.fontSize=size+'px';}
 }
});
onBeforeUnmount(()=>{document.title=priorTitle;document.removeEventListener('keydown',key);priorFocus?.focus();});
</script>
<template>
<Teleport to="body">
 <section ref="sheet" class="reader-ticket-screen" role="dialog" aria-modal="true" aria-label="Печать читательского билета">
  <div class="ticket-actions"><button ref="printButton" class="ticket-print" @click="print">Печать</button><button class="ticket-back" @click="emit('close')">Назад</button></div>
  <div class="ticket-sheet">
   <article id="reader-ticket" class="print-reader-card">
    <div>
     <header class="ticket-brand"><div class="ticket-brand-name" data-fit>{{ticket.brand}}</div><div class="ticket-brand-note">Читательский<br>билет</div></header>
     <div class="ticket-holder"><div class="ticket-holder-name" data-fit>{{ticket.full_name}}</div><div class="ticket-holder-meta" data-fit>{{ticket.category}}<template v-if="ticket.department"> · {{ticket.department}}</template></div></div>
    </div>
    <div class="ticket-codes"><div><div class="ticket-code-caption">Штрихкод</div><div class="ticket-code128" role="img" :aria-label="'Штрихкод '+ticket.barcode" v-html="ticket.svg"></div><div class="ticket-number">{{ticket.barcode}}</div></div><div class="ticket-qr" role="img" :aria-label="'QR-код '+ticket.barcode" v-html="ticket.qr_svg"></div></div>
    <footer class="ticket-footer"><span>Предъявите билет на кафедре выдачи и при входе в библиотеку.</span><strong class="ticket-number">{{ticket.ticket_number}}</strong></footer>
   </article>
  </div>
  <p class="ticket-print-hint">Размер билета — 86 × 54 мм. При печати выберите масштаб 100% и отключите колонтитулы.</p>
 </section>
</Teleport>
</template>
<style>
body:has(>.reader-ticket-screen){overflow:hidden}
.reader-ticket-screen{position:fixed;inset:0;z-index:10000;background:#e9eaec;overflow:auto;color:#000;font-family:Arial,'Helvetica Neue',sans-serif}
.reader-ticket-screen *{box-sizing:border-box}
.ticket-actions{display:flex;justify-content:center;gap:12px;padding:18px 12px}
.ticket-actions button{border:1px solid #001f3f;border-radius:6px;padding:10px 18px;font-size:18px;font-weight:700;cursor:pointer}
.ticket-actions .ticket-print{background:#001f3f;color:white}.ticket-actions .ticket-back{background:white;color:#001f3f;border-color:#c4c6cf}
.ticket-sheet{display:flex;justify-content:center;padding:12px}
.print-reader-card{width:86mm;height:54mm;flex:none;padding:3mm 3.6mm;background:white;border:1px solid #b9bcc2;border-radius:2mm;display:flex;flex-direction:column;justify-content:space-between;color:#000;zoom:1.7}
.ticket-brand{display:flex;align-items:flex-start;gap:2mm;border-bottom:0.4mm solid #000;padding-bottom:1mm}
.ticket-brand-name{font-size:4mm;font-weight:800;letter-spacing:.22mm;line-height:1;flex:1;min-width:0;max-height:12mm;overflow-wrap:anywhere}
.ticket-brand-note{text-transform:uppercase;font-size:2mm;letter-spacing:.1mm;line-height:1.15;color:#444;flex:none;padding-top:1.4mm}
.ticket-holder{margin-top:1.6mm}.ticket-holder-name{font-size:3.6mm;font-weight:700;line-height:1.1;max-height:8mm;overflow-wrap:anywhere}
.ticket-holder-meta{font-size:2.2mm;line-height:1.2;margin-top:.8mm;color:#444;max-height:5.3mm;overflow-wrap:anywhere}
.ticket-codes{display:grid;grid-template-columns:minmax(0,1fr) 15mm;gap:2mm;align-items:end}
.ticket-code-caption{font-size:1.9mm;font-weight:700;letter-spacing:.12mm;line-height:1;color:#444;text-transform:uppercase}
.ticket-code128 svg{display:block;width:100%;height:12mm}.ticket-qr svg{display:block;width:15mm;height:15mm}
.ticket-number{font-family:'Courier New',monospace;font-size:2.5mm;font-weight:700;line-height:1.1;white-space:nowrap}
.ticket-footer{display:flex;align-items:flex-end;gap:2mm;border-top:.25mm solid #999;padding-top:.9mm;color:#444;font-size:2mm;line-height:1.2}.ticket-footer>span{flex:1}.ticket-footer strong{color:#000}
.ticket-print-hint{text-align:center;color:#525866;font-size:14px;margin:16px}
@media(max-width:620px){.print-reader-card{zoom:1}.ticket-sheet{padding:12px 0}}
@media print{
 @page reader-ticket{size:94mm 62mm;margin:4mm}
 html:has(.reader-ticket-screen),body:has(>.reader-ticket-screen){margin:0!important;padding:0!important;overflow:visible!important;height:auto!important;background:white!important}
 body:has(>.reader-ticket-screen)>:not(.reader-ticket-screen){display:none!important}
 .reader-ticket-screen{page:reader-ticket;position:static;overflow:visible;background:white;width:86mm;margin:0;padding:0;-webkit-print-color-adjust:exact;print-color-adjust:exact}
 .ticket-actions,.ticket-print-hint{display:none!important}.ticket-sheet{display:block;padding:0;margin:0}
 .print-reader-card{zoom:1;break-inside:avoid;border:0;border-radius:0}
}
</style>
