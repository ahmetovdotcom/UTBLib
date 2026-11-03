import {test} from 'node:test';
import assert from 'node:assert/strict';
import {emptyCatalogSearch,normalizeCatalogSearch,catalogSearchPath,fetchCatalogRecords} from '../src/catalogSearch.ts';
test('field search URL preserves Cyrillic, special characters, mode and paging without widening the search',()=>{
 const filter=normalizeCatalogSearch({...emptyCatalogSearch(),q:'  Книга ',udc:' 33 ',type_id:7,match:'any',conditions:[{field:'245$b',operator:'contains',value:' Монография & 100%_ + # ? '},{field:'952$j',operator:'equals',value:'Қазақ тілі'}]});
 const params=new URL(catalogSearchPath(filter,50),'http://test').searchParams;
 assert.equal(params.get('q'),'Книга');assert.equal(params.get('udc'),'33');assert.equal(params.get('offset'),'50');assert.equal(params.get('type_id'),'7');assert.equal(params.get('match'),'any');
 assert.deepEqual(JSON.parse(params.get('conditions')!),filter.conditions);
 assert.equal(filter.conditions[0].value,'Монография & 100%_ + # ?');
});
test('unapplied editing never mutates the snapshot used by pagination',()=>{
 const draft={...emptyCatalogSearch(),conditions:[{field:'245$b',operator:'contains' as const,value:'Монография'}]};
 const applied=normalizeCatalogSearch(draft);
 draft.conditions[0].value='Учебник';draft.q='another query';draft.conditions.push({field:'041$a',operator:'contains',value:'kaz'});
 const next=new URL(catalogSearchPath(applied,50),'http://test').searchParams;
 assert.deepEqual(JSON.parse(next.get('conditions')!),[{field:'245$b',operator:'contains',value:'Монография'}]);assert.equal(next.get('q'),'');
});
test('empty or invalid advanced conditions require correction, not a silent full-catalog search',()=>{
 for(const value of ['', '   ', 'a'.repeat(20001)])assert.throws(()=>normalizeCatalogSearch({...emptyCatalogSearch(),conditions:[{field:'245$b',operator:'contains',value}]}));
 assert.throws(()=>normalizeCatalogSearch({...emptyCatalogSearch(),conditions:[{field:'bad',operator:'contains',value:'x'}]}));
 assert.throws(()=>normalizeCatalogSearch({...emptyCatalogSearch(),conditions:Array.from({length:9},()=>({field:'245$b',operator:'contains' as const,value:'x'}))}));
 const plain=new URL(catalogSearchPath(emptyCatalogSearch()),'http://test');assert.equal(plain.searchParams.has('conditions'),false);assert.equal(plain.searchParams.has('type_id'),false);
});

test('long and multiple chosen terms use a request body instead of an oversized URL',async()=>{
 const calls:any[]=[];const api=async(...args:any[])=>{calls.push(args);return ['ok'];};
 const state=normalizeCatalogSearch({...emptyCatalogSearch(),conditions:[{field:'520$a',operator:'equals',value:'Аннотация. '.repeat(1000)}]});
 assert.deepEqual(await fetchCatalogRecords(api,state,50),['ok']);
 assert.equal(calls[0][0],'/catalog-search/records');assert.equal(calls[0][1],'POST');
 assert.equal(calls[0][2].offset,50);assert.equal(calls[0][2].type_id,null);assert.equal(calls[0][2].conditions[0].value,state.conditions[0].value);
 await fetchCatalogRecords(api,emptyCatalogSearch());assert.equal(calls[1].length,1);assert.ok(calls[1][0].startsWith('/records?'));
});
