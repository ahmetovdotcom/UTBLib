import {test} from 'node:test';
import assert from 'node:assert/strict';
import {primarySpecialty,specialtyChoices,cleanRecord,type RecordData} from '../src/catalog.ts';
const record=(values:string[],primary?:string|null):RecordData=>({type_id:1,primary_specialty:primary,marc:{leader:'',fields:values.map(value=>({tag:'952',subfields:[{code:'j',value}]}))}});
test('one distinct specialty is automatic; several require an explicit choice',()=>{
 assert.equal(primarySpecialty(record([' Туризм ','Туризм'])),'Туризм');
 assert.equal(primarySpecialty(record(['Туризм','Финансы'])),null);
 assert.equal(primarySpecialty(record(['Туризм','Финансы'],'Финансы')),'Финансы');
 assert.deepEqual(specialtyChoices(record(['Туризм',' ','Туризм','Финансы'])),['Туризм','Финансы']);
});
test('save preserves all MARC values and clears a removed main without picking the first',()=>{
 const r=record(['Туризм','Финансы'],'Право'),before=JSON.stringify(r.marc);
 const saved=cleanRecord(r);assert.equal(saved.primary_specialty,null);
 assert.equal(JSON.stringify(saved.marc),before);assert.equal(r.primary_specialty,'Право');
 r.primary_specialty='Туризм';assert.equal(cleanRecord(r).primary_specialty,'Туризм');
 r.marc.fields.shift();assert.equal(cleanRecord(r).primary_specialty,'Финансы');
});
