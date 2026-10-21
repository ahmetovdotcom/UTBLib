import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {reactive} from 'vue';
import {makeField,prepareRecord,cleanRecord,cloneField,type DT,type RecordData,type Spec} from '../src/catalog.ts';
const data=JSON.parse(readFileSync(new URL('../../data/marc21.json',import.meta.url),'utf8'));
const specs:Record<string,Spec>=Object.fromEntries(data.fields.map((f:Spec)=>[f.tag,f]));
const cfg=(tag:string,required=false,subfields:string[]=[])=>({tag,label:'',required,subfields});
const type:DT={id:1,name:'Тест',config:[cfg('245',true),cfg('264'),cfg('084')]};
const record=():RecordData=>reactive({type_id:1,marc:{leader:'00000nam a2200000   4500',fields:[]}});
test('New worksheet presents every configured field but saves no empty placeholders',()=>{
 const r=record();prepareRecord(r,type,specs);
 assert.deepEqual(r.marc.fields.map(f=>f.tag),['245','264','084']);assert.equal(cleanRecord(r).marc.fields.length,0);
 r.marc.fields[0].subfields![0].value='Заглавие';const out=cleanRecord(r);
 assert.deepEqual(out.marc.fields.map(f=>f.tag),['245']);assert.deepEqual(out.marc.fields[0].subfields,[{code:'a',value:'Заглавие'}]);
});
test('Existing fields, blanks, repetitions, whitespace and hidden local fields survive editing',()=>{
 const r=record();r.marc.fields=[{tag:'999',ind1:' ',ind2:' ',subfields:[{code:'a',value:'  локальное  '},{code:'a',value:''}]},{tag:'245',ind1:'0',ind2:'0',subfields:[{code:'a',value:'Книга'},{code:'b',value:''}]}];
 const before=JSON.parse(JSON.stringify(r));prepareRecord(r,type,specs);assert.deepEqual(cleanRecord(r),before);
});
test('Editing an existing record provides missing selected subfields without persisting them empty',()=>{
 const r=record();r.marc.fields=[{tag:'245',ind1:'0',ind2:'0',subfields:[{code:'a',value:'Книга'}]}];prepareRecord(r,type,specs);
 assert.ok(r.marc.fields[0].subfields!.some(s=>s.code==='c'));r.marc.fields[0].subfields!.find(s=>s.code==='c')!.value='Иванов И. И.';
 assert.deepEqual(cleanRecord(r).marc.fields[0].subfields,[{code:'a',value:'Книга'},{code:'c',value:'Иванов И. И.'}]);
});
test('Cloned fields are independent and retain repeated subfields',()=>{
 const original={tag:'700',ind1:'1',ind2:' ',subfields:[{code:'a',value:'Иванов'},{code:'e',value:'автор'},{code:'e',value:'редактор'}]};
 const copy=cloneField(original);copy.subfields![0].value='Петров';assert.equal(original.subfields[0].value,'Иванов');assert.equal(copy.subfields!.length,3);
});
test('Selected subfield order determines the initial input order',()=>{
 const f=makeField(specs['264'],cfg('264',false,['c','b','a']));assert.deepEqual(f.subfields!.map(s=>s.code),['c','b','a']);assert.equal(f.ind2,'1');
});
test('Switching type does not delete fields of the original type',()=>{
 const r=record();prepareRecord(r,type,specs);r.marc.fields[0].subfields![0].value='Сохранить';prepareRecord(r,{id:2,name:'Статья',config:[cfg('773')]},specs);assert.equal(cleanRecord(r).marc.fields[0].subfields![0].value,'Сохранить');
});
test('Russian translation layer covers every source label',()=>{
 const labels=JSON.parse(readFileSync(new URL('../src/labels-ru.json',import.meta.url),'utf8'));
 for(const f of data.fields){assert.ok(labels[f.label]);for(const s of f.subfields)assert.ok(labels[s.label]);for(const i of f.indicators){assert.ok(labels[i.label]);for(const v of i.values)assert.ok(labels[v.label]);}}
});
test('Virtual MARCSQL marker 000 stays in leader, not in the fields array',()=>{
 const r=record();prepareRecord(r,{id:1,name:'MARCSQL',config:[{...cfg('000',true),local:true},cfg('245',true)]},{...specs,'000':{tag:'000',label:'Маркер',repeatable:false,obsolete:false,documentation:'',indicators:[],subfields:[]}});
 assert.ok(!r.marc.fields.some(f=>f.tag==='000'));assert.equal(cleanRecord(r).marc.leader.length,24);
});
test('Three keyword slots are displayed but only supplied values are saved',()=>{
 const r=record();const t={id:1,name:'MARCSQL',config:[{...cfg('653',false,['a','a','a']),local:true}]};prepareRecord(r,t,specs);assert.equal(r.marc.fields[0].subfields!.length,3);r.marc.fields[0].subfields![1].value='История';assert.deepEqual(cleanRecord(r).marc.fields[0].subfields,[{code:'a',value:'История'}]);
});
test('New MARCSQL rows use screenshot indicators without changing existing records',()=>{
 for(const [tag,ind1,ind2] of [['700','1',' '],['246','0','1'],['440',' ','0'],['520','0',' '],['541','1',' '],['650','1','4'],['856','0',' ']]){
  const spec={...specs[tag],local:true};const f=makeField(spec,{...cfg(tag,false,['a']),local:true});
  assert.equal(f.ind1,ind1);assert.equal(f.ind2,ind2);
 }
 const r=record();r.marc.fields=[{tag:'856',ind1:'1',ind2:' ',subfields:[{code:'d',value:'10'}]}];
 const before=JSON.parse(JSON.stringify(r));prepareRecord(r,{id:1,name:'Книга',config:[{...cfg('856',false,['d','u','f']),local:true}]},{...specs,'856':{...specs['856'],local:true}});
 assert.deepEqual(cleanRecord(r),before);
});

import {insertIsbn,targets} from '../src/isbn.ts';
test('ISBN insertion preserves unchecked values and merges repeated authors and publication subfields',()=>{
 const r=record();prepareRecord(r,type,specs);
 const rows=[{tag:'245',code:'a',label:'Title',value:'New title'},{tag:'260',code:'a',label:'Place',value:'City'},{tag:'260',code:'b',label:'Publisher',value:'Press'},{tag:'700',code:'a',label:'Author',value:'A'},{tag:'700',code:'a',label:'Author',value:'B'}];
 r.marc.fields.find(f=>f.tag==='245')!.subfields!.find(s=>s.code==='a')!.value='Manual title';
 assert.equal(targets(rows,r.marc.fields)[0].existing,'Manual title');
 insertIsbn(rows,r.marc.fields,[false,true,true,true,true],tag=>makeField(specs[tag],cfg(tag)));
 assert.equal(r.marc.fields.find(f=>f.tag==='245')!.subfields![0].value,'Manual title');
 assert.equal(r.marc.fields.filter(f=>f.tag==='260').length,1);
 assert.deepEqual(r.marc.fields.filter(f=>f.tag==='700').map(f=>f.subfields![0].value),['A','B']);
 insertIsbn(rows,r.marc.fields,[true,true,true,true,true],tag=>makeField(specs[tag],cfg(tag)));
 assert.equal(r.marc.fields.filter(f=>f.tag==='700').length,2);
 assert.equal(r.marc.fields.find(f=>f.tag==='245')!.subfields![0].value,'New title');
});
