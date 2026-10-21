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
 await p.getByLabel('Вид описания',{exact:true}).selectOption('single');
 for(const [label,value] of Object.entries({'245 Заглавие':'История Казахстана','245$c Сведения об ответственности':'М. Асанов','260 Место издания':'Алматы','260$b Издательство':'Университет','260$c Дата издания':'2026','300 Объем':'120 с.','245$z Вид и характеристики содержания и средство доступа':'Текст : непосредственный'}))await p.getByLabel(label,{exact:true}).fill(value);
 assert.equal(await p.locator('[data-field="653"] input.value-input').count(),3);
 await p.locator('[data-field="245"] .field-row').click({button:'right'});assert.ok(await p.getByRole('menuitem',{name:/Дублировать поле/}).isDisabled());assert.ok(await p.getByRole('menuitem',{name:/Удалить поле/}).isDisabled());await p.keyboard.press('Escape');
 await p.getByRole('button',{name:'Сформировать описание',exact:true}).click();await p.locator('.gost-panel blockquote').waitFor();assert.match(await p.locator('.gost-panel blockquote').innerText(),/История Казахстана \/ М. Асанов/);
 await p.screenshot({path:'../preview.png',fullPage:true});
 await p.getByLabel('773 Название журнала или сборника',{exact:true}).fill('Вестник университета');await p.getByLabel('773$g Год, том, номер и страницы',{exact:true}).fill('2026, № 1, с. 10–20');await p.getByLabel('Вид описания',{exact:true}).selectOption('component');
 await Promise.all([p.waitForResponse(r=>r.url().endsWith('/api/gost/preview')),p.getByRole('button',{name:'Сформировать описание',exact:true}).click()]);assert.match(await p.locator('.gost-panel blockquote').innerText(),/\/\/ Вестник университета/);
 await p.locator('.gost-panel').screenshot({path:'../preview-gost.png'});assert.deepEqual(errors,[]);console.log('Passed: identical profiles, literal Russian rows, three keyword slots, required-field menu guards, book and article GOST previews; no stored records changed.');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exit(1)});
