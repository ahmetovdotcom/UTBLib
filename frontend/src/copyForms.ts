export type PrintCopy = {id:number;inventory_number:string;barcode?:string|null;unit_price:string|number|null;currency:string;status:string};
type Field = {tag:string;ind2?:string;subfields?:{code:string;value:string}[]};
export type FormBook = {index:string;authorMark:string;author:string;title:string;year:string};
export const DEFAULT_FORM_LAYOUT={width:80,height:130,columns:2};
export const FORM_PAGE={width:210,height:297,margin:5,previewGap:8};
const PRINT_WIDTH=FORM_PAGE.width-2*FORM_PAGE.margin,PRINT_HEIGHT=FORM_PAGE.height-2*FORM_PAGE.margin;
export function formBook(record:{marc:{fields:Field[]}}):FormBook {
 const fields=record.marc.fields;
 const values=(tag:string,code:string)=>fields.filter(f=>f.tag===tag).flatMap(f=>f.subfields||[]).filter(s=>s.code===code).map(s=>s.value.trim()).filter(Boolean);
 const publication=fields.filter(f=>f.tag==='264'&&f.ind2==='1').flatMap(f=>f.subfields||[]).find(s=>s.code==='c'&&s.value.trim())?.value;
 return {index:values('090','a')[0]||values('080','a')[0]||'',authorMark:values('090','x')[0]||'',author:values('100','a').join('; '),title:[values('245','a').join(' '),values('245','b').join(' ')].filter(Boolean).join(' : '),year:values('260','c')[0]||publication||''};
}
export async function loadFormCopies(api:(path:string)=>Promise<any>,recordId:number):Promise<PrintCopy[]> {
 const result=new Map<number,PrintCopy>();
 for(let offset=0;;){
  const page=await api(`/records/${recordId}/copies?offset=${offset}&limit=100`);
  for(const copy of page.items)if(copy.status==='active')result.set(copy.id,copy);
  offset+=page.items.length;
  if(offset>=page.matched)break;
  if(!page.items.length)throw new Error('Список экземпляров изменился. Откройте печать повторно.');
 }
 return [...result.values()];
}
export function selectedFormCopies(copies:PrintCopy[],ids:ReadonlySet<number>):PrintCopy[]{
 return copies.filter(c=>c.status==='active'&&ids.has(c.id));
}
export function filterFormCopies(copies:PrintCopy[],query:string):PrintCopy[]{
 const q=query.trim().toLocaleLowerCase();return copies.filter(c=>(c.inventory_number+' '+(c.barcode||'')).toLocaleLowerCase().includes(q));
}
export function formLayout(width:number,height:number,columns:number){
 if(!Number.isFinite(width)||!Number.isFinite(height)||!Number.isInteger(columns)||width<35||height<70||width>PRINT_WIDTH||height>PRINT_HEIGHT||columns<1||columns>4)throw new Error('Размер: ширина 35–200 мм, высота 70–287 мм; столбцов от 1 до 4.');
 if(width*columns>PRINT_WIDTH)throw new Error('Бланки не помещаются по ширине A4. Уменьшите ширину или число столбцов.');
 const rows=Math.floor(PRINT_HEIGHT/height);return {rows,perPage:rows*columns};
}
const escape=(value:unknown)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
export function formDocument(book:FormBook,copies:PrintCopy[],width:number,height:number,columns:number):string {
 const {perPage}=formLayout(width,height,columns);
 const cards=copies.map(c=>{
  const price=c.unit_price===null?'—':Number(c.unit_price).toFixed(2)+(c.currency==='KZT'?'':` ${c.currency}`);
  return `<article class="copy-form"><header><div class="classification"><span>${escape(book.index)}</span>${book.authorMark?`<span class="author-mark">${escape(book.authorMark)}</span>`:''}</div><strong>${escape(c.inventory_number)}</strong></header><section class="description"><b>${escape(book.author)}</b><div class="book-title">${escape(book.title)}</div><footer><b>${escape(book.year)}</b><b>${escape(price)}</b></footer></section><div class="writing-lines">${'<div><span></span><span></span></div>'.repeat(14)}</div></article>`;
 });
 const pages=[];for(let i=0;i<cards.length;i+=perPage)pages.push(`<div class="sheet">${cards.slice(i,i+perPage).join('')}</div>`);
 return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Бланки экземпляров</title><style>
 @page{size:A4 portrait;margin:0}*{box-sizing:border-box}html,body{margin:0;padding:0}body{color:#000;background:#eee;font-family:"Times New Roman",serif;font-size:9pt;line-height:1.15;-webkit-text-size-adjust:none;text-size-adjust:none}.sheet{width:${FORM_PAGE.width}mm;height:${FORM_PAGE.height}mm;margin:0 auto ${FORM_PAGE.previewGap}mm;padding:${FORM_PAGE.margin}mm;display:grid;grid-template-columns:repeat(${columns},${width}mm);grid-auto-rows:${height}mm;gap:0;justify-content:start;align-content:start;background:white;break-after:page}.sheet:last-child{break-after:auto;margin-bottom:0}
 .copy-form{position:relative;width:${width}mm;height:${height}mm;padding:1.3mm;display:flex;flex-direction:column;break-inside:avoid;min-width:0;min-height:0;overflow-wrap:anywhere}.copy-form::before{content:"";position:absolute;inset:-.15mm;border:.3mm solid #000;pointer-events:none}header{display:flex;justify-content:space-between;align-items:flex-start;gap:1mm;font-weight:bold;font-size:10pt;flex-shrink:0}header>*{min-width:0}.classification{display:flex;flex-direction:column;gap:.5mm}.description{text-align:center;margin-top:1mm;flex-shrink:0}.book-title{margin-top:.5mm}footer{display:flex;justify-content:space-between;gap:1mm;margin-top:1mm}.writing-lines{flex:1;min-height:12mm;display:flex;flex-direction:column;padding:1mm 0 0;gap:0}.writing-lines>div{flex:1;display:flex;gap:1.5mm;align-items:flex-end}.writing-lines span{flex:1;border-bottom:.3pt solid black;min-width:0}
 @media screen{.sheet{box-shadow:0 0 0 1px #ccc}}
 @media print{body{background:white}.sheet{margin:0}}
 </style></head><body>${pages.join('')}</body></html>`;
}
