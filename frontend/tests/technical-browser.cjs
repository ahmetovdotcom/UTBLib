// Read-only browser regression: fills an unsaved record, never modifies stored data.
const {chromium}=require('playwright');
const fs=require('fs'),assert=require('node:assert/strict');
(async()=>{
 const key=fs.readFileSync('../.env','utf8').match(/^ADMIN_KEY=(.+)$/m)[1];
 const base=process.env.BASE_URL||'http://localhost:8096';
 const get=async path=>(await fetch(base+'/api'+path,{headers:{'X-Admin-Key':key}})).json();
 const dict=await get('/dictionary'),types=await get('/types');
 const b=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const p=await b.newPage({viewport:{width:1512,height:1100}}),errors=[];p.on('pageerror',e=>errors.push(String(e)));
 try{
 await p.goto(base);await p.getByLabel('Ключ доступа',{exact:true}).fill(key);await p.getByRole('button',{name:'Войти в каталог →',exact:true}).click();
 await p.getByRole('button',{name:'＋ Создать запись',exact:true}).click();
 for(const t of types){await p.getByLabel('Тип документа',{exact:true}).selectOption(String(t.id));assert.deepEqual(await p.locator('[data-field]').evaluateAll(ns=>ns.map(n=>n.dataset.field)),dict.default_config.map(c=>c.tag));}
 for(const tag of ['000','001','005','008','990'])assert.ok(await p.locator('[data-field="'+tag+'"] input.value-input').first().getAttribute('readonly')!==null);
 await p.locator('[data-field="001"] .field-row').click({button:'right'});assert.ok(await p.getByRole('menuitem',{name:/Удалить поле/}).isDisabled());await p.keyboard.press('Escape');
 await p.getByRole('button',{name:'Настроить характеристики',exact:true}).click();
 await p.getByLabel('Характер даты',{exact:true}).selectOption('s');
 await p.getByLabel('Первый год (4 позиции)',{exact:true}).fill('2026');await p.getByLabel('Первый год (4 позиции)',{exact:true}).press('Tab');
 await p.getByLabel('Язык',{exact:true}).selectOption('kaz');
 await p.getByLabel('Место издания',{exact:true}).selectOption('kz ');
 const coded=await p.locator('[data-field="008"] input.value-input').inputValue();assert.equal(coded.length,40);assert.equal(coded.slice(7,11),'2026');assert.equal(coded.slice(15,18),'kz ');assert.equal(coded.slice(35,38),'kaz');
 await p.screenshot({path:'../preview-technical.png',fullPage:true});assert.deepEqual(errors,[]);console.log('Passed: readonly system fields, protected menu, Russian 008 editor and exact positions; no records saved.');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exit(1)});
