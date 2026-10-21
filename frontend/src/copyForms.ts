export type PrintCopy = {id:number;inventory_number:string;unit_price:string|number|null;currency:string;status:string};
type Field = {tag:string;ind2?:string;subfields?:{code:string;value:string}[]};
export type FormBook = {index:string;author:string;title:string;year:string};
export function formBook(record:{marc:{fields:Field[]}}):FormBook {
 const fields=record.marc.fields;
 const values=(tag:string,code:string)=>fields.filter(f=>f.tag===tag).flatMap(f=>f.subfields||[]).filter(s=>s.code===code).map(s=>s.value.trim()).filter(Boolean);
 const publication=fields.filter(f=>f.tag==='264'&&f.ind2==='1').flatMap(f=>f.subfields||[]).find(s=>s.code==='c'&&s.value.trim())?.value;
 return {index:values('090','a')[0]||values('080','a')[0]||'',author:values('100','a').join('; '),title:[values('245','a').join(' '),values('245','b').join(' ')].filter(Boolean).join(' : '),year:values('260','c')[0]||publication||''};
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
export function formLayout(width:number,height:number,columns:number){
 if(!Number.isFinite(width)||!Number.isFinite(height)||!Number.isInteger(columns)||width<35||height<70||width>190||height>277||columns<1||columns>4)throw new Error('Размер: ширина 35–190 мм, высота 70–277 мм; столбцов от 1 до 4.');
 if(width*columns+5*(columns-1)>190)throw new Error('Бланки не помещаются по ширине A4. Уменьшите ширину или число столбцов.');
 const rows=Math.floor((277+5)/(height+5));return {rows,perPage:rows*columns};
}
const escape=(value:unknown)=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
export function formDocument(book:FormBook,copies:PrintCopy[],width:number,height:number,columns:number):string {
 const {perPage}=formLayout(width,height,columns);
 const cards=copies.map(c=>{
  const price=c.unit_price===null?'—':Number(c.unit_price).toFixed(2)+(c.currency==='KZT'?'':` ${c.currency}`);
  return `<article class="copy-form"><header><span>${escape(book.index)}</span><strong>${escape(c.inventory_number)}</strong></header><section class="description"><b>${escape(book.author)}</b><div class="book-title">${escape(book.title)}</div><footer><b>${escape(book.year)}</b><b>${escape(price)}</b></footer></section><div class="writing-lines">${'<div><span></span><span></span></div>'.repeat(14)}</div></article>`;
 });
 const pages=[];for(let i=0;i<cards.length;i+=perPage)pages.push(`<div class="sheet">${cards.slice(i,i+perPage).join('')}</div>`);
 return `<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Бланки экземпляров</title><style>
 @page{size:A4 portrait;margin:10mm}*{box-sizing:border-box}body{margin:0;color:#000;background:#eee;font-family:"Times New Roman",serif}.sheet{width:190mm;height:277mm;margin:10mm auto;padding:0;display:grid;grid-template-columns:repeat(${columns},${width}mm);grid-auto-rows:${height}mm;gap:5mm;justify-content:center;align-content:start;background:white;break-after:page}.sheet:last-child{break-after:auto}
 .copy-form{width:${width}mm;height:${height}mm;border:3px double #000;padding:2mm;display:flex;flex-direction:column;break-inside:avoid;font-size:9pt;overflow-wrap:anywhere}header{display:flex;justify-content:space-between;gap:2mm;font-weight:bold;font-size:10pt}header>*{min-width:0}.description{text-align:center;margin-top:5mm;flex-shrink:0}.book-title{margin-top:1mm;font-size:9pt}footer{display:flex;justify-content:space-around;gap:2mm;margin-top:2mm}.writing-lines{flex:1;min-height:12mm;display:flex;flex-direction:column;padding:2mm 1mm 0;gap:0}.writing-lines>div{flex:1;display:flex;gap:1.5mm;align-items:flex-end}.writing-lines span{flex:1;border-bottom:0.3pt solid black;min-width:0}
 @media print{body{background:white}.sheet{margin:0}}
 </style></head><body>${pages.join('')}</body></html>`;
}
