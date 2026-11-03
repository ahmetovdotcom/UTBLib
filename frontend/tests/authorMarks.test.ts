import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {authorKey, canInsertAuthorMark, formatAuthorMark, lookupAuthorMark, tableRows} from '../src/authorMarks.ts';
import type {AuthorTable} from '../src/authorMarks.ts';
const tables:AuthorTable[]=JSON.parse(readFileSync(new URL('../src/data/authorTables.json',import.meta.url),'utf8'));
function mark(term:string){const r=lookupAuthorMark(tables,term);return r.choice?formatAuthorMark(r.choice):null;}

test('both source tables are complete; reliable alphabetical boundaries remain ordered',()=>{
  assert.equal(tables.length,53);
  for(const alphabet of ['cyrillic','latin']){
    const groups=tables.filter(t=>t.alphabet===alphabet);
    assert.equal(groups.reduce((n,g)=>n+g.entries.length,0),alphabet==='cyrillic'?2492:2250);
    assert.equal(new Set(groups.map(t=>t.letter)).size,groups.length);
    for(const g of groups){
      assert.equal(g.start,alphabet==='cyrillic'?11:10);assert.equal(g.start+g.entries.length-1,99);
      assert.ok(g.page>=2&&g.page<=(alphabet==='cyrillic'?15:14));
      const good=g.entries.filter(e=>!e.review&&!e.special).map(e=>e.term==='I/J'?'i':authorKey(e.term,g.alphabet));
      for(let i=1;i<good.length;i++)assert.ok(good[i-1]<good[i],`${g.letter}: ${good[i-1]} / ${good[i]}`);
      for(const e of g.entries)assert.ok(e.term.trim());
    }
  }
});
test('examples from the Cyrillic source use the lower alphabetical boundary, not longest prefix',()=>{
  for(const [term,expected] of [['Иванов','И20'],['Мосолов','М82'],['Абс','А17'],['Сбоев','С23'],['Тарасов','Т19'],['Оз','О-46']])assert.equal(mark(term),expected);
  assert.equal(mark('  «Иванов, И. И.'),'И20');
  assert.equal(mark('ИВАНОВ'),'И20');
});
test('Latin source examples, diacritics and I/J rules',()=>{
  for(const term of ['Marc','March','Märchen','Marcipan'])assert.equal(mark(term),'M29');
  assert.equal(mark('Ibsen'),'I-32');assert.equal(mark('Optimum'),'O-66');
  assert.equal(mark('Lai'),'L17');assert.equal(mark('Laj'),'L17');
  assert.equal(mark('Johnson'),'J74');
});
test('marks can also be located directly; formatting never changes their number',()=>{
  for(const term of ['А17','А 17','А-17'])assert.equal(mark(term),'А17');
  const c=lookupAuthorMark(tables,'Оз').choice!;
  assert.equal(formatAuthorMark(c,'none'),'О46');assert.equal(formatAuthorMark(c,'space'),'О 46');assert.equal(formatAuthorMark(c,'hyphen'),'О-46');
  for(const term of ['А100','А1','А00','Ё11'])assert.equal(mark(term),null);
});
test('unsupported letters and mixed scripts are not silently transliterated',()=>{
  for(const term of ['Әбішев','Қаржы','Сәбит','Aхметов','Ørsted','ß','123 книги',''])assert.equal(mark(term),null,term);
  for(const term of ['Ёлка','Йошкар-Ола','Ъ','Ы'])assert.equal(mark(term),term[0]);
});
test('reserved signs require full author identity or a manual choice',()=>{
  assert.equal(mark('Толстой'),null);assert.equal(mark('Толстой А. К.'),null);
  assert.equal(mark('Толстой Л.Н.'),'Т53');
  assert.equal(lookupAuthorMark(tables,'Толстой Л.Н.').choice?.special,true);
});
test('ambiguous source rows and affected intervals are not recommended',()=>{
  for(const term of ['A31','I54','O41','X11','Aid','Aldridge','Bernhard','Krzy','Zee'])assert.equal(mark(term),null,term);
  assert.equal(mark('Alf'),'A34');
  const a=tables.find(t=>t.alphabet==='latin'&&t.letter==='A')!;
  const dubious=tableRows(a).find(e=>e.number===31)!;
  assert.equal(dubious.term,'Aid');assert.equal(dubious.review,true);
  assert.equal(formatAuthorMark(dubious),'A31'); // Explicit manual review remains possible.
});
test('field vocabulary restrictions still govern insertion',()=>{
  assert.equal(canInsertAuthorMark('И20',''),true);
  assert.equal(canInsertAuthorMark('И20','',{auto_add:true}),true);
  assert.equal(canInsertAuthorMark('И20','',{auto_add:false,allow_edit:true}),true);
  assert.equal(canInsertAuthorMark('И20','',{auto_add:false}),false);
  assert.equal(canInsertAuthorMark('И20','И20',{auto_add:false}),true);
  assert.equal(canInsertAuthorMark('И20','',{auto_add:false},[{value:'И20'}]),true);
  assert.equal(canInsertAuthorMark('И 20','',{auto_add:false},[{value:'И20'}]),false);
});
test('bundled originals match the supplied PDFs',()=>{
  for(const [name,hash] of [['cyrillic','b3a36b51e2fd262788f98d37dcc4deb9d011b110879452b14fbab1c97af5231d'],['latin','c11446a4d95d6061d58ecdbc86a362f6d2e4267ba3a9f6f22678849a3a0680ed']]){
    assert.equal(createHash('sha256').update(readFileSync(new URL(`../public/author-tables/${name}.pdf`,import.meta.url))).digest('hex'),hash);
  }
});
