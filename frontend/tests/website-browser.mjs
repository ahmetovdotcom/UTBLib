// Synthetic API only; no staff database.
import {readFile} from 'node:fs/promises';
import {chromium} from 'playwright';
import {createServer} from 'vite';
import assert from 'node:assert/strict';
const schema=JSON.parse(await readFile(new URL('../../backend/app/website_schema.json',import.meta.url),'utf8'));
function blank(s){if(s.type==='locales')return {...Object.fromEntries(['ru','kk','en'].map(l=>[l,blank(s.item)])),...Object.fromEntries(Object.entries(s.fields).map(([k,v])=>[k,blank(v)]))};if(s.type==='object')return Object.fromEntries(Object.entries(s.fields).map(([k,v])=>[k,blank(v)]));if(s.type==='list')return [];if(s.type==='tuple')return s.items.map(blank);return s.nullable?null:'';}
let rows=Object.entries(schema).map(([slug,s],i)=>({id:i+1,kind:'pages',slug,status:'published',version:1,published_at:'2026-01-01T00:00:00Z',assets:{},data:{translations:{ru:{title:slug}},page_content:blank(s.schema)}})),conflict=false;
const server=await createServer({server:{host:'127.0.0.1',port:18144,strictPort:true}});await server.listen();
const browser=await chromium.launch({headless:true,channel:'chrome'}),context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(12000);
await context.route('**/api/**',async route=>{
 const req=route.request(),u=new URL(req.url()),p=u.pathname.slice(4);let data=[],status=200;
 if(p==='/auth/me')data={user:{id:1,role:'admin',display_name:'Тест',permissions:[]},csrf_token:'synthetic'};
 else if(p==='/dictionary')data={fields:[]};else if(p==='/types')data=[{id:1,name:'Книга',config:[]}];
 else if(p==='/site-content/website-schema')data=schema;
 else if(p==='/site-content'&&req.method()==='GET'){const items=rows.filter(i=>i.kind===u.searchParams.get('kind'));data={items,total:items.length,page:1};}
 else if(p==='/site-content'&&req.method()==='POST'){data={...req.postDataJSON(),id:30,version:1,assets:{}};rows.push(data);}
 else if(/^\/site-content\/\d+$/.test(p)){
  const id=Number(p.split('/').at(-1)),row=rows.find(i=>i.id===id);
  if(req.method()==='DELETE'){rows=rows.filter(i=>i.id!==id);data={status:'deleted'};}
  else if(conflict){status=409;data={detail:'Материал изменён другим сотрудником. Откройте его заново.'};conflict=false;}
  else{data={...row,...req.postDataJSON(),version:row.version+1};rows=rows.map(i=>i.id===id?data:i);}
 }else if(/^\/site-content\/\d+\/assets\/image$/.test(p)){
  const row=rows.find(i=>i.id===Number(p.split('/')[2]));row.version++;row.assets={image:{url:'/image',name:'image.jpg',size:100}};data=row;
 }
 await route.fulfill({status,json:data});
});
const button=name=>page.getByRole('button',{name,exact:true}),field=name=>page.getByLabel(name,{exact:true}),save=async()=>{await button('Сохранить').click();await page.getByRole('status').waitFor();};
try{
 await page.goto('http://127.0.0.1:18144/#/site?tab=pages');await page.getByRole('button',{name:/Контакты \/contacts/}).click();
 await field('Адрес: первая строка').fill('Тестовый адрес');await button('Қазақша').click();await field('Адрес: первая строка').fill('Сынақ мекенжайы');await button('Русский').click();assert.equal(await field('Адрес: первая строка').inputValue(),'Тестовый адрес');
 const schedule=page.locator('details').filter({has:page.locator('summary',{hasText:/^Расписание$/})}).first();await schedule.locator('summary').click();await schedule.getByRole('button',{name:'+ Добавить строку',exact:true}).click();
 await schedule.getByLabel('Дни недели',{exact:true}).fill('Понедельник');await schedule.getByLabel('Время работы',{exact:true}).fill('09:00–18:00');await save();
 assert.equal(rows[0].data.page_content.ru.hours_rows.length,1);assert.equal(rows[0].data.page_content.kk.location_address_line_a,'Сынақ мекенжайы');
 if(!await schedule.evaluate(el=>el.open))await schedule.locator('summary').click();await schedule.getByRole('button',{name:'Удалить строку',exact:true}).click();await save();assert.equal(rows[0].data.page_content.ru.hours_rows.length,0);
 await field('Адрес: первая строка').fill('Не сохранено');page.once('dialog',d=>d.dismiss());await button('Сотрудники и руководство').click();assert.equal(await field('Адрес: первая строка').inputValue(),'Не сохранено');
 page.once('dialog',d=>d.accept());await button('Сотрудники и руководство').click();await button('+ Добавить').click();
 await field('ФИО · Русский').fill('Тестовый сотрудник');await field('Должность').fill('Библиотекарь');await field('Показывать в руководстве').check();await page.getByRole('combobox',{name:/^Состояние/}).selectOption('published');await save();assert(rows.find(i=>i.id===30).data.show_leadership);
 await field('Изображение (до 8 МБ)').setInputFiles({name:'test.png',mimeType:'image/png',buffer:Buffer.from('synthetic')});await page.getByRole('status').filter({hasText:'Файл сохранён'}).waitFor();
 await field('Должность').fill('Руководитель');conflict=true;await button('Сохранить').click();await page.getByRole('alert').filter({hasText:'другим сотрудником'}).waitFor();assert.equal(await field('Должность').inputValue(),'Руководитель');await save();
 page.once('dialog',d=>d.dismiss());await button('Удалить карточку').click();assert(rows.some(i=>i.id===30));page.once('dialog',d=>d.accept());await button('Удалить карточку').click();await page.getByRole('status').filter({hasText:'Карточка удалена'}).waitFor();assert(!rows.some(i=>i.id===30));
 await page.setViewportSize({width:390,height:844});await button('Страницы и контакты').click();await page.getByRole('button',{name:/Контакты \/contacts/}).waitFor();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:'/tmp/utblib-website-edit/staff-editor-mobile.png',fullPage:true});assert.deepEqual(errors,[]);
 console.log('Website editor: translations, lists, save, conflicts, unsaved changes, people CRUD, image and mobile layout OK');
}catch(e){await page.screenshot({path:'/tmp/utblib-website-edit/editor-failure.png',fullPage:true});throw e;}finally{await browser.close();await server.close();}
