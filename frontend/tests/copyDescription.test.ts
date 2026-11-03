import {test} from 'node:test';
import assert from 'node:assert/strict';
import {descriptionForCopy} from '../src/copyDescription.ts';

test('copy in the editor uses a snapshot of unsaved values instead of the saved record',async()=>{
 const marc={leader:'00000nam a2200000   4500',fields:[{tag:'245',ind1:'1',ind2:'0',subfields:[{code:'a',value:'Новое заглавие'}]}]};
 let payload:any;let finish:(value:any)=>void=()=>{};
 const pending=descriptionForCopy(async(path,method,body)=>{assert.equal(path,'/gost/preview');assert.equal(method,'POST');payload=body;return new Promise(resolve=>finish=resolve);},{recordId:42,marc,kind:'component'});
 marc.fields[0].subfields[0].value='Следующая правка';
 assert.equal(payload.marc.fields[0].subfields[0].value,'Новое заглавие');assert.equal(payload.kind,'component');
 finish({text:'Описание.',record_text:'Автор. Описание.'});assert.equal(await pending,'Автор. Описание.');
});
test('copy works before the first save and still supports copying from the catalog list',async()=>{
 const marc={leader:'00000nam a2200000   4500',fields:[]};
 await descriptionForCopy(async(path,method,body:any)=>{assert.equal(path,'/gost/preview');assert.equal(body.kind,'single');return {record_text:'Новая запись.'};},{marc});
 assert.equal(await descriptionForCopy(async(path,method)=>{assert.equal(path,'/records/7/description');assert.equal(method,undefined);return {text:'Запись.'};},{recordId:7}),'Запись.');
});
test('empty output and API errors do not produce successful copy',async()=>{
 await assert.rejects(descriptionForCopy(async()=>({text:''}),{recordId:7}),/нет данных/);
 await assert.rejects(descriptionForCopy(async()=>{throw Error('Нет доступа');},{recordId:7}),/Нет доступа/);
});
