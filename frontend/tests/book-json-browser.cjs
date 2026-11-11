/* Run only against a disposable API/SQLite instance serving the built frontend. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');

(async()=>{
 const base=process.env.BOOK_JSON_QA_URL;
 if(!base)throw Error('Set BOOK_JSON_QA_URL for an isolated QA instance');
 const address=new URL(base);
 if(!['127.0.0.1','localhost'].includes(address.hostname)||address.port!=='18141')throw Error('Only disposable localhost:18141 is allowed');
 const artifacts=fs.mkdtempSync(path.join(os.tmpdir(),'utblib-book-json-'));
 const browser=await chromium.launch({headless:true,channel:process.env.PHOTO_QA_BROWSER||'chrome'});
 const context=await browser.newContext({viewport:{width:1440,height:1050},permissions:['clipboard-read','clipboard-write']});
 const page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let saves=0,providerCalls=0;
 try{
  const login=await context.request.post(base+'/api/auth/login',{data:{username:'admin',password:'test-secret'}});
  assert(login.ok(),await login.text());const csrf=(await login.json()).csrf_token;
  async function api(p,method='GET',data){
   const r=await context.request.fetch(base+'/api'+p,{method,data,headers:{'X-CSRF-Token':csrf}});
   assert(r.ok(),await r.text());return r.json();
  }
  assert.equal((await api('/book-photos/config')).enabled,false);
  const t=await api('/types','POST',{name:'JSON QA '+Date.now(),config:[
   {tag:'245',required:true,subfields:['a','b']},{tag:'700',subfields:['a','e']},{tag:'020',subfields:['a']}
  ]});
  const title='JSON QA исходная книга '+Date.now();
  const saved=await api('/records','POST',{type_id:t.id,marc:{leader:'00000nam a2200000   4500',fields:[
   {tag:'245',ind1:'0',ind2:'0',subfields:[{code:'a',value:title},{code:'b',value:'Сохранить подзаголовок'}]},
   {tag:'700',ind1:'1',ind2:' ',subfields:[{code:'a',value:'Автор А'},{code:'e',value:'редактор'}]},
   {tag:'999',ind1:' ',ind2:' ',subfields:[{code:'a',value:'Скрытое поле'}]}
  ]}});
  page.on('request',r=>{if(/\/api\/records(?:\/\d+)?$/.test(r.url())&&['POST','PUT'].includes(r.method()))saves++;if(r.url().includes('/book-photos/analyze'))providerCalls++;});
  await page.goto(base);
  await page.locator('button.record-title').filter({hasText:title}).click();
  const openJson=async()=>{
   await page.getByRole('button',{name:'Заполнить по фото',exact:true}).click();
   assert(await page.getByRole('button',{name:'Подключить телефон по QR-коду',exact:true}).isVisible());
   await page.getByRole('button',{name:'Вставить JSON',exact:true}).click();
   await page.getByRole('button',{name:'Скопировать промпт для ИИ',exact:true}).waitFor();
   await page.waitForFunction(()=>!Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='Скопировать промпт для ИИ')?.disabled);
  };
  await openJson();
  await page.getByRole('button',{name:'Скопировать промпт для ИИ',exact:true}).click();
  await page.getByText('Задание скопировано. Вставьте его в чат ИИ вместе с фотографиями книги.',{exact:true}).waitFor();
  const prompt=await page.evaluate(()=>navigator.clipboard.readText());
  assert(prompt.includes('JSON Schema ответа:'));
  const schema=JSON.parse(prompt.split('JSON Schema ответа:\n')[1]);
  assert.equal(schema.properties.type_id.const,t.id);
  const answer=page.getByLabel('JSON-ответ',{exact:true});
  await answer.fill('{broken');await page.getByRole('button',{name:'Проверить JSON',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'Не удалось прочитать JSON'}).waitFor();
  const row=(key,values)=>({key,values,image_numbers:[1],evidence:'Видно на титульном листе',confidence:'clear',basis:'printed'});
  const data={format:'utblib-book-description-v1',type_id:t.id,fields:[row('245$a',['Қазақ тілі']),row('700$a',['Автор А','Автор Б']),row('020$a',['978-601-383-048-3'])],warnings:[]};
  await answer.fill(JSON.stringify({...data,type_id:t.id+1}));await page.getByRole('button',{name:'Проверить JSON',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'другого типа документа'}).waitFor();
  await answer.fill('```json\n'+JSON.stringify(data)+'\n```');await page.getByRole('button',{name:'Проверить JSON',exact:true}).click();
  await page.getByRole('heading',{name:'3. Проверьте и выберите поля'}).waitFor();
  assert.equal(await page.locator('.book-json-dialog input[type=checkbox]:checked').count(),0);
  assert(await page.getByRole('button',{name:'Вставить выбранные поля (0)',exact:true}).isDisabled());
  await page.getByRole('button',{name:'Выбрать прочитанные данные для пустых полей',exact:true}).click();
  assert.equal(await page.locator('.book-json-dialog input[type=checkbox]:checked').count(),1);
  await page.getByLabel('Вставить Заглавие',{exact:true}).check();
  await page.getByLabel('Вставить Другие авторы',{exact:true}).check();
  await page.getByLabel('Заглавие: значение 1',{exact:true}).fill('Қазақ тілі — проверено');
  await page.screenshot({path:path.join(artifacts,'json-preview.png'),fullPage:false});
  await page.getByRole('button',{name:'Вставить выбранные поля (3)',exact:true}).click();
  assert.equal(await page.locator('dialog[open]').count(),0);
  await page.getByText('Есть несохранённые изменения',{exact:true}).waitFor();
  assert.equal(saves,0);assert.equal(providerCalls,0);
  const unchanged=await api('/records/'+saved.id);
  assert.deepEqual(unchanged.marc,saved.marc);assert.equal(unchanged.version,saved.version);
  await page.getByText('Служебные данные записи',{exact:true}).click();
  await page.getByRole('button',{name:'Полная запись JSON',exact:true}).click();
  const marc=JSON.parse(await page.getByLabel('Полная MARC запись',{exact:true}).inputValue());
  const values=(tag,code)=>marc.fields.filter(f=>f.tag===tag).flatMap(f=>(f.subfields||[]).filter(s=>s.code===code).map(s=>s.value));
  assert.deepEqual(values('245','a'),['Қазақ тілі — проверено']);
  assert.deepEqual(values('245','b'),['Сохранить подзаголовок']);
  assert.deepEqual(values('700','a'),['Автор А','Автор Б']);assert.deepEqual(values('700','e'),['редактор']);
  assert.deepEqual(values('999','a'),['Скрытое поле']);
  assert.deepEqual(values('020','a'),['978-601-383-048-3']);
  await page.getByRole('button',{name:'Отмена',exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  await openJson();
  assert.equal(await answer.inputValue(),'');
  await page.evaluate(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined});document.execCommand=()=>false;});
  await page.getByRole('button',{name:'Скопировать промпт для ИИ',exact:true}).click();
  await page.getByText(/Текст задания выделен/).waitFor();
  assert(await page.getByLabel('Промпт для ИИ',{exact:true}).isVisible());
  assert(await page.getByLabel('Промпт для ИИ',{exact:true}).evaluate(e=>e.selectionStart===0&&e.selectionEnd===e.value.length));
  assert(await page.locator('.book-json-dialog').evaluate(e=>e.scrollWidth<=e.clientWidth));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(artifacts,'json-mobile.png'),fullPage:false});
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('dialog[open]').count(),1);
  assert(await page.getByRole('button',{name:'Вставить JSON',exact:true}).evaluate(e=>e===document.activeElement));
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('dialog[open]').count(),0);
  assert.equal(saves,0);assert.equal(providerCalls,0);assert.deepEqual(errors,[]);
  console.log('PASS: no-key prompt/clipboard and fallback, invalid/wrong-type/fenced JSON, explicit selection, draft-only merge with preserved data, nested dialogs/Escape/focus, mobile layout. Artifacts: '+artifacts);
 }catch(e){await page.screenshot({path:path.join(artifacts,'failure.png'),fullPage:false});console.error('Artifacts: '+artifacts);throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
