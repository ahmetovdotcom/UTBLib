import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {makeField,cleanRecord,prepareRecord,type Spec,type MF} from '../src/catalog.ts';
import {insertPhotoFields,photoValues,canSelectPhotoField,photoCost,type PhotoSelection} from '../src/bookPhotos.ts';
const data=JSON.parse(readFileSync(new URL('../../data/marc21.json',import.meta.url),'utf8'));
const specs:Record<string,Spec>=Object.fromEntries(data.fields.map((f:Spec)=>[f.tag,f]));
const create=(tag:string)=>makeField(specs[tag],{tag,label:'',required:false,subfields:['a']});
function choice(tag:string,code:string,values:string[],selected=true,mode:'append'|'replace'='replace'):PhotoSelection{
 return {row:{key:tag+'$'+code,tag,code,label:'Поле',values,repeatable:!!specs[tag]?.repeatable,image_numbers:[1],evidence:'Фото',confidence:'clear',warnings:[]},selected,mode};
}
test('Only selected subfields change; title does not replace subtitle, identifiers or unrelated fields',()=>{
 const fields:MF[]=[{tag:'001',value:'42'}, {tag:'245',ind1:'0',ind2:'0',subfields:[{code:'a',value:'Старое'},{code:'b',value:'Подзаголовок'}]},
 {tag:'999',ind1:' ',ind2:' ',subfields:[{code:'a',value:'Локальное'}]}];
 const original=JSON.stringify(fields);
 const result=insertPhotoFields(fields,[choice('245','a',['Новое']),choice('245','b',['Другое'],false)],specs,create);
 assert.equal(JSON.stringify(fields),original);
 assert.deepEqual(result[0],fields[0]);assert.deepEqual(result[2],fields[2]);
 assert.equal(result[1].ind1,'0');assert.equal(result[1].ind2,'0');
 assert.deepEqual(result[1].subfields,[{code:'a',value:'Новое'},{code:'b',value:'Подзаголовок'}]);
});
test('Repeated authors can be appended without duplication or deleted author roles',()=>{
 const fields:MF[]=[{tag:'700',ind1:'1',ind2:' ',subfields:[{code:'a',value:'Автор А'},{code:'e',value:'переводчик'}]}];
 const selected=[choice('700','a',['Автор А','Автор Б'],true,'append')];
 const result=insertPhotoFields(fields,selected,specs,create);
 assert.deepEqual(photoValues(result,{tag:'700',code:'a'}),['Автор А','Автор Б']);
 assert.equal(result[0].subfields![1].value,'переводчик');
 assert.deepEqual(insertPhotoFields(result,selected,specs,create),result);
});
test('Replacement removes surplus targeted repetitions but retains all other subfields',()=>{
 const fields:MF[]=['А','Б','В'].map(value=>({tag:'700',ind1:'1',ind2:' ',subfields:[{code:'a',value}]}));
 fields[1].subfields!.push({code:'e',value:'редактор'});
 const result=insertPhotoFields(fields,[choice('700','a',['Новый'])],specs,create);
 assert.equal(result.length,2);
 assert.deepEqual(result[1].subfields,[{code:'e',value:'редактор'}]);
 assert.deepEqual(photoValues(result,{tag:'700',code:'a'}),['Новый']);
});
test('Repeated subfields stay within nonrepeatable field; invalid repeat is atomic',()=>{
 const changed={...specs,'952':{...specs['700'],tag:'952',repeatable:false,subfields:[{code:'j',label:'Специальность',repeatable:true}]}};
 const createCustom=(tag:string)=>makeField(changed[tag],{tag,label:'',required:false,subfields:['j']});
 const result=insertPhotoFields([], [choice('952','j',['А','Б'])],changed,createCustom);
 assert.equal(result.length,1);assert.deepEqual(photoValues(result,{tag:'952',code:'j'}),['А','Б']);
 const original:MF[]=[];
 assert.throws(()=>insertPhotoFields(original,[choice('700','a',['Автор']),choice('245','a',['А','Б'])],specs,create));
 assert.deepEqual(original,[]);
});
test('No implicit selection and empty proposal cannot erase data',()=>{
 const fields=[{tag:'245',ind1:'1',ind2:'0',subfields:[{code:'a',value:'Ручное'}]}];
 assert.deepEqual(insertPhotoFields(fields,[choice('245','a',['Новое'],false)],specs,create),fields);
 assert.throws(()=>insertPhotoFields(fields,[choice('245','a',[' '])],specs,create));
 assert.equal(fields[0].subfields[0].value,'Ручное');
});
test('New record insertion keeps automatic placeholders out of saved MARC',()=>{
 const record={type_id:1,marc:{leader:'00000nam a2200000   4500',fields:[] as MF[]}};
 const type={id:1,name:'Книга',config:[{tag:'245',label:'',required:true,subfields:['a','b']},{tag:'260',label:'',required:false,subfields:['a','b','c']}]};
 prepareRecord(record,type,specs);
 record.marc.fields=insertPhotoFields(cleanRecord(record).marc.fields,[choice('245','a',['Қазақ тілі'])],specs,create);
 prepareRecord(record,type,specs);
 assert.deepEqual(cleanRecord(record).marc.fields,[{tag:'245',ind1:'1',ind2:'0',subfields:[{code:'a',value:'Қазақ тілі'}]}]);
});

test('Quick selection includes only clear extracted values, never recommendations or new vocabulary values',()=>{
 const row={...choice('245','a',['Новое']).row,basis:'printed' as const};
 assert.equal(canSelectPhotoField([],row),true);
 assert.equal(canSelectPhotoField([],{...row,basis:'inferred'}),false);
 assert.equal(canSelectPhotoField([],{...row,confidence:'uncertain'}),false);
 assert.equal(canSelectPhotoField([],{...row,warnings:['Проверьте']}),false);
 assert.equal(canSelectPhotoField([],{...row,vocabulary_status:'new'}),false);
 assert.equal(canSelectPhotoField([],{...row,basis:undefined}),false);
 assert.equal(canSelectPhotoField([{tag:'245',subfields:[{code:'a',value:'Уже заполнено'}]}],row),false);
});


test('Small paid requests never round to zero; missing cost is not free',()=>{
 assert.equal(photoCost('0.000002'),'0,000002 $');
 assert.equal(photoCost('0.00000005'),'< 0,000001 $');
 assert.equal(photoCost('0.032'),'0,032 $');
 assert.equal(photoCost('0'),'0,00 $');
 for(const missing of [null,'','NaN','Infinity','-1'])assert.equal(photoCost(missing),'Не рассчитана');
});
