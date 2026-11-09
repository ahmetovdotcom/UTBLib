<script setup lang="ts">
import {nextTick,onBeforeUnmount,onMounted,onUpdated,ref,watch} from 'vue';

const props=defineProps<{title:string,frozenColumns:number}>();
const root=ref<HTMLElement|null>(null),scroller=ref<HTMLElement|null>(null),toggle=ref<HTMLButtonElement|null>(null);
const expanded=ref(false);
let observer:ResizeObserver|undefined,frame=0;
let observed=new Set<Element>();
let previousOverflow='';

function measure(){
 frame=0;
 const table=scroller.value?.querySelector('table');
 if(!table?.tHead)return;
 const headings=Array.from(table.tHead.rows[0].cells);
 const targets=new Set<Element>([scroller.value!,table,...Array.from(table.tHead.rows),...headings.slice(0,props.frozenColumns)]);
 for(const el of observed)if(!targets.has(el))observer?.unobserve(el);
 for(const el of targets)if(!observed.has(el))observer?.observe(el);
 observed=targets;

 const offsets:number[]=[];
 let left=0;
 for(let i=0;i<props.frozenColumns;i++){
  offsets.push(left);
  left+=headings[i]?.getBoundingClientRect().width||0;
 }
 function freeze(row:HTMLTableRowElement){
  let column=0;
  for(const cell of Array.from(row.cells)){
   const pinned=column+cell.colSpan<=props.frozenColumns;
   cell.classList.toggle('ksu-frozen',pinned);
   cell.classList.toggle('ksu-frozen-edge',pinned&&column+cell.colSpan===props.frozenColumns);
   if(pinned)cell.style.setProperty('--ksu-left',`${offsets[column]}px`);
   else cell.style.removeProperty('--ksu-left');
   column+=cell.colSpan;
  }
 }
 freeze(table.tHead.rows[0]);
 for(const body of Array.from(table.tBodies))for(const row of Array.from(body.rows))freeze(row);
 if(table.tFoot)for(const row of Array.from(table.tFoot.rows))freeze(row);
 let top=0;
 for(const row of Array.from(table.tHead.rows)){
  for(const cell of Array.from(row.cells))cell.style.setProperty('--ksu-top',`${top}px`);
  top+=row.getBoundingClientRect().height;
 }
}
function scheduleMeasure(){if(!frame)frame=requestAnimationFrame(measure);}
async function setExpanded(value:boolean){
 if(expanded.value===value)return;
 expanded.value=value;
 if(value){previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';}
 else document.body.style.overflow=previousOverflow;
 await nextTick();
 toggle.value?.focus({preventScroll:true});
 scheduleMeasure();
}
function keyboard(event:KeyboardEvent){
 if(!expanded.value)return;
 if(event.key==='Escape'){
  event.preventDefault();event.stopPropagation();void setExpanded(false);return;
 }
 if(event.key!=='Tab')return;
 const targets=Array.from(root.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], [tabindex="0"]')||[])
  .filter(el=>el.getClientRects().length>0);
 const first=targets[0],last=targets.at(-1);
 if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
 else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
}
onMounted(()=>{observer=new ResizeObserver(scheduleMeasure);scheduleMeasure();});
onUpdated(scheduleMeasure);
watch(()=>props.frozenColumns,()=>nextTick(scheduleMeasure));
onBeforeUnmount(()=>{
 observer?.disconnect();cancelAnimationFrame(frame);
 if(expanded.value)document.body.style.overflow=previousOverflow;
});
</script>

<template>
 <div ref="root" class="ksu-table-view" :class="{'ksu-table-expanded':expanded}"
      :style="{'--ksu-frozen-count':frozenColumns}" :data-frozen-columns="frozenColumns" :role="expanded?'dialog':'region'"
      :aria-label="title" :aria-modal="expanded?true:undefined" @keydown="keyboard">
  <div class="ksu-table-view-toolbar">
   <strong>{{title}}</strong>
   <slot name="controls" />
   <button ref="toggle" type="button" :aria-expanded="expanded" @click="setExpanded(!expanded)">
    {{expanded?'Свернуть таблицу':'На весь экран'}}
   </button>
  </div>
  <div ref="scroller" class="table-wrap ksu-table-scroll" tabindex="0" :aria-label="title+' · прокрутка данных'">
   <slot />
  </div>
 </div>
</template>

<style>
.app-shell .ksu-table-view{container-type:inline-size;min-width:0;margin-top:16px}
.app-shell .ksu-table-view-toolbar{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding:0 0 12px;color:#33465c}
.app-shell .ksu-table-view-toolbar>button{margin-left:auto;flex-shrink:0}
.app-shell .ksu-table-view-toolbar .check-label{margin:0}
.app-shell .ksu-table-scroll{max-height:65vh;overflow:auto;isolation:isolate;overscroll-behavior:contain}
.app-shell .ksu-table-view table.ksu-grid{border-collapse:separate;border-spacing:0;border:0;min-width:100%}
.app-shell .ksu-table-view .ksu-grid :is(th,td){border:0;border-right:1px solid #9aabbf;border-bottom:1px solid #9aabbf}
.app-shell .ksu-table-view .ksu-grid tr>:first-child{border-left:1px solid #9aabbf}
.app-shell .ksu-table-view .ksu-grid thead tr:first-child>th{border-top:1px solid #8295ac}
.app-shell .ksu-table-view .ksu-grid thead th{position:sticky;top:var(--ksu-top,0px);z-index:3;background:#eef3fa;border-color:#8295ac}
.app-shell .ksu-table-view .ksu-grid thead tr:last-child th,
.app-shell .ksu-table-view .ksu-grid thead th[rowspan]{border-bottom:2px solid #8295ac}
.app-shell .ksu-table-view .ksu-grid .ksu-frozen{position:sticky;left:var(--ksu-left,0px);z-index:1;background:#fff;min-width:0;overflow-wrap:anywhere}
.app-shell .ksu-table-view .ksu-grid thead .ksu-frozen{z-index:4;background:#eef3fa;width:clamp(60px,calc(65cqw / var(--ksu-frozen-count)),var(--ksu-column-width,210px));min-width:clamp(60px,calc(65cqw / var(--ksu-frozen-count)),var(--ksu-column-width,210px));max-width:clamp(60px,calc(65cqw / var(--ksu-frozen-count)),var(--ksu-column-width,210px))}
.app-shell .ksu-table-view[data-frozen-columns="4"] thead th:is(:first-child,:nth-child(4)){--ksu-column-width:120px}
.app-shell .ksu-table-view[data-frozen-columns="4"] thead th:nth-child(2){--ksu-column-width:100px}
.app-shell .ksu-table-view .ksu-grid .ksu-frozen-edge{box-shadow:2px 0 #8295ac}
.app-shell .ksu-table-view .ksu-grid tbody tr:hover .ksu-frozen{background:#f8fbfc}
.app-shell .ksu-table-view .ksu-grid .cancelled .ksu-frozen{background:#f4f4f4}
.app-shell .ksu-table-view .ksu-grid tfoot :is(th,td){background:#eef3fa;border-top:2px solid #8295ac}
.app-shell .ksu-table-expanded{position:fixed;inset:0;z-index:90;display:flex;flex-direction:column;margin:0;padding:20px;background:#fff}
.app-shell .ksu-table-expanded>.ksu-table-view-toolbar{flex-shrink:0}
.app-shell .ksu-table-expanded>.ksu-table-scroll{flex:1;min-height:0;max-height:none}
@media(max-width:600px){.app-shell .ksu-table-expanded{padding:10px}.app-shell .ksu-table-view-toolbar{gap:10px;font-size:13px}}
@media print{.app-shell .ksu-table-view{container-type:normal}.app-shell .ksu-table-expanded{position:static;display:block;padding:0}.app-shell .ksu-table-view-toolbar{display:none}.app-shell .ksu-table-scroll{max-height:none;overflow:visible}.app-shell .ksu-table-view .ksu-grid :is(th,td){position:static!important}}
</style>
