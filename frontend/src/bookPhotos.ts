import type {MF, Spec} from './catalog';

export type PhotoField = {
 key:string; tag:string; code:string; label:string; values:string[]; repeatable:boolean;
 image_numbers:number[]; evidence:string; confidence:'clear'|'uncertain'; warnings:string[];
 basis?:'printed'|'inferred'; vocabulary_status?:'matched'|'new'|'none';
};
export type PhotoSelection = {row:PhotoField; selected:boolean; mode:'replace'|'append'};
export type PhotoUsage = {
 model:string; input_tokens:number|null; output_tokens:number|null; total_tokens:number|null;
 cached_input_tokens:number|null; cache_write_tokens:number|null; reasoning_tokens:number|null;
 estimated_cost_usd:string|null; pricing_date:string|null; pricing_url:string|null; cost_note:string;
};

export function photoCost(value:string|null):string{
 if(value===null||value.trim()==='')return 'Не рассчитана';
 const amount=Number(value);
 if(!Number.isFinite(amount)||amount<0)return 'Не рассчитана';
 // Keep tiny charges visible: rounding to cents makes a paid request look free.
 if(amount>0&&amount<0.000001)return '< 0,000001 $';
 return new Intl.NumberFormat('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:6}).format(amount)+' $';
}

export function photoValues(fields:MF[], row:Pick<PhotoField,'tag'|'code'>):string[]{
 return fields.filter(f=>f.tag===row.tag).flatMap(f=>(f.subfields||[]).filter(s=>s.code===row.code).map(s=>s.value)).filter(v=>v.trim());
}

export function canSelectPhotoField(fields:MF[], row:PhotoField):boolean{
 return !photoValues(fields,row).length&&row.confidence==='clear'&&row.basis==='printed'&&!row.warnings.length&&row.vocabulary_status!=='new';
}

// Work on a copy: a bad proposal must not partially update a user's draft.
export function insertPhotoFields(fields:MF[], selections:PhotoSelection[], specs:Record<string,Spec>, create:(tag:string)=>MF):MF[]{
 const result:MF[]=JSON.parse(JSON.stringify(fields));
 for(const {row,selected,mode} of selections){
  if(!selected)continue;
  const spec=specs[row.tag], sf=spec?.subfields.find(s=>s.code===row.code);
  if(!sf)throw Error('Поле больше не доступно в рабочем листе: '+row.key);
  let values=[...new Set(row.values.map(v=>v.trim()).filter(Boolean))];
  if(!values.length)throw Error('Введите значение для поля «'+row.label+'» или снимите галочку.');
  if(!spec.repeatable&&!sf.repeatable&&(values.length>1||mode==='append'))throw Error('Поле «'+row.label+'» не допускает повторений.');
  if(mode==='append'){
   const known=new Set(photoValues(result,row).map(v=>v.normalize('NFC').trim()));
   values=values.filter(v=>!known.has(v.normalize('NFC')));
  }
  if(mode==='replace'){
   // Replace targeted subfields only, preserving unrelated subfields, indicators and field order.
   for(const f of result.filter(f=>f.tag===row.tag)){
    f.subfields=(f.subfields||[]).flatMap(s=>{
     if(s.code!==row.code)return [s];
     return values.length?[{...s,value:values.shift()!}]:[];
    });
   }
  }
  for(const value of values){
   const same=result.filter(f=>f.tag===row.tag);
   let field=same.find(f=>!(f.subfields||[]).some(s=>s.code===row.code&&s.value.trim()));
   if(!field&&sf.repeatable)field=same[0];
   if(!field){field=create(row.tag);result.push(field);}
   field.subfields??=[];
   const blank=field.subfields.find(s=>s.code===row.code&&!s.value.trim());
   if(blank)blank.value=value;else field.subfields.push({code:row.code,value});
  }
 }
 // Remove only data fields emptied by the selected replacements, not unrelated legacy data.
 const tags=new Set(selections.filter(s=>s.selected&&s.mode==='replace').map(s=>s.row.tag));
 return result.filter(f=>!tags.has(f.tag)||!!f.subfields?.length);
}

export async function preparePhoto(file:File):Promise<string>{
 if(!['image/jpeg','image/png','image/webp'].includes(file.type))throw Error('Поддерживаются JPG, PNG и WebP. Сохраните HEIC в JPG.');
 if(file.size>15*1024*1024)throw Error('Фотография больше 15 МБ. Уменьшите её размер.');
 const url=URL.createObjectURL(file);
 try{
  const image=new Image();image.src=url;await image.decode();
  if(image.naturalWidth*image.naturalHeight>30_000_000||Math.min(image.naturalWidth,image.naturalHeight)<100)throw Error('Нужна фотография от 100 пикселей, не более 30 мегапикселей.');
  const scale=Math.min(1,2000/Math.max(image.naturalWidth,image.naturalHeight));
  const canvas=document.createElement('canvas');
  canvas.width=Math.round(image.naturalWidth*scale);canvas.height=Math.round(image.naturalHeight*scale);
  const context=canvas.getContext('2d');if(!context)throw Error('Не удалось подготовить фото.');
  context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);
  context.drawImage(image,0,0,canvas.width,canvas.height);
  let data=canvas.toDataURL('image/jpeg',0.9);
  if(data.length>1_350_000)data=canvas.toDataURL('image/jpeg',0.75);
  if(data.length>1_350_000)throw Error('Фотография слишком подробная. Обрежьте её до страницы книги.');
  return data;
 }finally{URL.revokeObjectURL(url);}
}
