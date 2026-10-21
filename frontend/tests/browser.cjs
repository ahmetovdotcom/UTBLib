// Run from frontend; creates a separate test type and record, never edits existing records.
const {chromium}=require('playwright');
const fs=require('fs');
const assert=require('node:assert/strict');
(async()=>{
 const env=fs.readFileSync('../.env','utf8'),key=env.match(/^ADMIN_KEY=(.+)$/m)[1];
 const base=process.env.BASE_URL||'http://localhost:8096';
 async function api(path,method='GET',body){const r=await fetch(base+'/api'+path,{method,headers:{'Content-Type':'application/json','X-Admin-Key':key},body:body?JSON.stringify(body):undefined});assert.ok(r.ok,await r.clone().text());return r.json();}
 const t=await api('/types','POST',{name:'Проверка интерфейса '+Date.now(),config:['245','100','264','650','080','084'].map(tag=>({tag,label:'',required:tag==='245',subfields:[]}))});
 const created={type_id:t.id};fs.writeFileSync('../test-created.json',JSON.stringify(created));
 const b=await chromium.launch({...process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{},headless:true});
 const p=await b.newPage({viewport:{width:1512,height:1100}});p.setDefaultTimeout(15000);const errors=[];p.on('pageerror',e=>errors.push(String(e)));
 try{
 await p.goto(base);await p.getByLabel('Ключ доступа',{exact:true}).fill(key);await p.getByRole('button',{name:'Войти в каталог →',exact:true}).click();await p.getByRole('heading',{name:'Каталог записей',exact:true}).waitFor();
 await p.getByRole('button',{name:'＋ Создать запись',exact:true}).click();await p.getByLabel('Тип документа',{exact:true}).selectOption(String(t.id));
 assert.deepEqual(await p.locator('[data-field]').evaluateAll(nodes=>nodes.map(n=>n.dataset.field)),['245','100','264','650','080','084']);
 await p.getByLabel('245 Основное заглавие',{exact:true}).fill('История Казахстана');await p.getByLabel('100 Фамилия, имя автора',{exact:true}).fill('Асанов, Марат');
 await p.locator('[data-field="264"] .expand-button').click();await p.getByLabel('264 Место издания',{exact:true}).fill('Алматы');await p.getByLabel('264$b Издательство',{exact:true}).fill('Университет');await p.getByLabel('264$c Год издания',{exact:true}).fill('2026');
 await p.getByLabel('650 Предметная рубрика',{exact:true}).fill('История Казахстана');
 await p.locator('[data-field="245"] .field-row').click({button:'right'});assert.equal(await p.getByRole('menuitem',{name:/Дублировать поле/}).isDisabled(),true);assert.equal(await p.getByRole('menuitem',{name:/Удалить поле/}).isDisabled(),true);await p.keyboard.press('Escape');
 await p.locator('[data-field="650"] .field-row').click({button:'right'});await p.getByRole('menuitem',{name:'⧉ Дублировать поле',exact:true}).click();assert.equal(await p.locator('[data-field="650"]').count(),2);await p.getByLabel('650 Предметная рубрика',{exact:true}).nth(1).fill('Культура Казахстана');
 await p.getByRole('button',{name:'Действия с полем 080',exact:true}).click();await p.getByRole('menuitem',{name:'× Удалить поле',exact:true}).click();assert.equal(await p.locator('[data-field="080"]').count(),0);
 await p.getByRole('button',{name:'⚙ Настроить рабочий лист',exact:true}).click();await p.getByRole('button',{name:'Поднять поле 264',exact:true}).click();await p.getByRole('button',{name:'Поднять поле 264',exact:true}).click();
 await Promise.all([p.waitForResponse(r=>r.url().endsWith('/api/types/'+t.id)&&r.request().method()==='PUT'),p.getByRole('button',{name:'Сохранить настройки',exact:true}).click()]);
 await p.getByRole('button',{name:'Каталогизация и классификация',exact:true}).click();await p.getByRole('button',{name:'Продолжить ввод',exact:true}).click();assert.equal(await p.locator('[data-field]').first().getAttribute('data-field'),'264');
 await Promise.all([p.waitForResponse(r=>r.url().endsWith('/api/records')&&r.request().method()==='POST'),p.getByRole('button',{name:'✓ Сохранить запись',exact:true}).click()]);await p.getByRole('status').filter({hasText:'Запись сохранена'}).waitFor();
 const recs=await api('/records?type_id='+t.id);assert.equal(recs.length,1);let saved=recs[0];fs.writeFileSync('../test-created.json',JSON.stringify({type_id:t.id,record_id:saved.id}));assert.deepEqual(saved.marc.fields.map(f=>f.tag).sort(),['100','245','264','650','650']);assert.equal(saved.marc.fields.find(f=>f.tag==='264').subfields.length,3);assert.ok(!saved.marc.fields.some(f=>f.tag==='084'||f.tag==='080'));
 await p.getByText('Служебные данные записи',{exact:true}).click();await p.getByRole('button',{name:'Полная запись JSON',exact:true}).click();const raw=p.getByLabel('Полная MARC запись');const marc=JSON.parse(await raw.inputValue());marc.fields.push({tag:'999',ind1:' ',ind2:' ',subfields:[{code:'a',value:'  Скрытые сведения  '},{code:'a',value:'Повтор'}]});await raw.fill(JSON.stringify(marc));await p.getByRole('button',{name:'Применить к рабочему листу',exact:true}).click();
 await Promise.all([p.waitForResponse(r=>r.url().endsWith('/api/records/'+saved.id)&&r.request().method()==='PUT'),p.getByRole('button',{name:'✓ Сохранить запись',exact:true}).click()]);await p.getByRole('status').filter({hasText:'Запись сохранена'}).waitFor();saved=await api('/records/'+saved.id);assert.deepEqual(saved.marc.fields.at(-1),marc.fields.at(-1));
 await p.locator('[data-field="264"] .expand-button').click();await p.locator('[data-field="245"] .expand-button').click();await p.getByRole('button',{name:'Закрыть сообщение',exact:true}).click();await p.screenshot({path:'../preview.png',fullPage:true});
 await p.setViewportSize({width:760,height:1000});await p.screenshot({path:'../preview-mobile.png',fullPage:true});await p.setViewportSize({width:1512,height:1100});
 await p.getByRole('button',{name:'Показать подразделы каталогизации',exact:true}).click();await p.getByRole('button',{name:'☷ Настройка ввода',exact:true}).click();await p.screenshot({path:'../preview-settings.png',fullPage:true});
 await p.getByRole('button',{name:'▧ Справочник полей',exact:true}).click();await p.getByLabel('Поиск по справочнику',{exact:true}).fill('заглавие');assert.ok((await p.locator('.picker-list button').count())>0);assert.equal(errors.length,0,errors.join('\n'));
 console.log('Browser passed: Russian worksheet, all rows, right-click repeat/delete guards, optional delete, profile ordering, clean save, hidden data preservation, Russian search, mobile rendering.');
 }catch(e){await p.screenshot({path:'../test-failure.png',fullPage:true});console.error('Browser errors:',errors);throw e;}finally{await b.close();}
})().catch(e=>{console.error(e);process.exit(1)});
