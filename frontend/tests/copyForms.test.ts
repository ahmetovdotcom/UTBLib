import {test} from 'node:test';
import assert from 'node:assert/strict';
import {formBook,formDocument,formLayout,loadFormCopies} from '../src/copyForms.ts';
test('loads every page without the holdings search and excludes inactive copies',async()=>{
 const calls:string[]=[];
 const items=Array.from({length:103},(_,id)=>({id,inventory_number:`000${id}`,status:id<101?'active':'withdrawn',unit_price:null,currency:'KZT'}));
 const copies=await loadFormCopies(async path=>{calls.push(path);const offset=Number(new URL(path,'http://test').searchParams.get('offset'));return {matched:103,items:items.slice(offset,offset+100)};},7);
 assert.equal(copies.length,101);assert.equal(copies[0].inventory_number,'0000');assert.equal(calls.length,2);assert.ok(calls[1].includes('offset=100'));assert.ok(calls.every(p=>!p.includes('&q=')));
});
test('uses shelf index, publication year and bibliographic title',()=>{
 const field=(tag:string,code:string,value:string)=>({tag,subfields:[{code,value}]});
 assert.deepEqual(formBook({marc:{fields:[field('080','a','3'),field('090','a','336.6'),field('100','a','Автор'),field('245','a','Книга'),field('245','b','Учебник'),field('260','c','2023')]}}),{index:'336.6',author:'Автор',title:'Книга : Учебник',year:'2023'});
});
test('six forms per A4, no loss on final page, escaped content and per-copy prices',()=>{
 assert.equal(formLayout(40,100,3).perPage,6);assert.throws(()=>formLayout(100,100,3));
 const copies=Array.from({length:7},(_,id)=>({id,inventory_number:`000${id}`,status:'active',unit_price:id===0?null:id===1?'0.00':'500.00',currency:'KZT'}));
 const html=formDocument({index:'1',author:'<script>alert(1)</script>',title:'Книга & книга',year:'2023'},copies,40,100,3);
 assert.equal((html.match(/class="sheet"/g)||[]).length,2);assert.equal((html.match(/class="copy-form"/g)||[]).length,7);assert.ok(!html.includes('<script>'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('0006'));assert.ok(html.includes('<b>—</b>'));assert.ok(html.includes('<b>0.00</b>'));assert.ok(html.includes('<b>500.00</b>'));
});
