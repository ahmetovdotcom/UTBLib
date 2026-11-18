// Synthetic API only: never changes a staff database.
import {chromium} from 'playwright';
import {createServer} from 'vite';
import assert from 'node:assert/strict';
const server=await createServer({server:{host:'127.0.0.1',port:18144,strictPort:true}});await server.listen();
const browser=await chromium.launch({headless:true,channel:'chrome'});
const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
const errors=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(10000);
let templates=[],lastDefinition,fail=false;
const labels={number:'№ п/п',inventory:'Инвентарный номер',author:'Автор',title:'Заглавие',subtitle:'Сведения, относящиеся к заглавию',language:'Язык текста',place:'Место издания',publisher:'Издательство',year:'Год издания',udc:'УДК',sigla:'Сигла хранения',price:'Цена за экземпляр',quantity:'Количество экземпляров',amount:'Сумма',titles:'Количество наименований',unpriced:'Экземпляров без цены',primary_specialty:'Основная специальность'};
await context.route('**/api/**',async route=>{
 const req=route.request(),path=new URL(req.url()).pathname.slice(4),body=req.postData()?req.postDataJSON():null;let data={},status=200;
 if(path==='/auth/me')data={user:{id:1,role:'admin',display_name:'Тест',permissions:[]},csrf_token:'test'};
 else if(path==='/dictionary')data={fields:[]};
 else if(path==='/types')data=[];
 else if(path==='/reports/fields')data={fields:Object.entries(labels).map(([key,label])=>({key,label,type:['price','amount'].includes(key)?'money':'text',scope:['number','quantity','amount','titles','unpriced'].includes(key)?'result':['inventory','sigla','price'].includes(key)?'copy':'record',operators:['contains','equals','empty']})),sources:[{key:'copies',label:'Действующий фонд'},{key:'catalog',label:'Каталог'},{key:'receipts',label:'Поступления по КСУ'}],groups:['primary_specialty','language']};
 else if(path==='/reports/templates'){
  if(req.method()==='POST'){data={...body,id:1,version:1};templates.push(data);status=201;}else data=templates;
 }else if(path==='/reports/preview'){
  lastDefinition=body.definition;const empty=body.definition.filters.some(f=>f.value==='Пусто');
  if(fail){status=422;data={detail:'Проверьте условия отбора.'};}
  else data={columns:body.definition.columns.map(c=>({...c,label:c.label||labels[c.key]})),rows:empty?[]:[{number:1,title:'Проверочная книга',inventory:'0001',price:'10.25',quantity:2,amount:'20.50',titles:1,primary_specialty:'Финансы',_record_id:null}],total:empty?0:51,totals:{titles:1,quantity:2,unpriced:1,amounts:{KZT:'20.50'}},generated_at:new Date().toISOString()};
 }else if(path==='/reports/export'){await route.fulfill({status:200,headers:{'Content-Disposition':'attachment; filename="report.xlsx"','Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'},body:Buffer.from('synthetic download')});return;}
 else if(path==='/records')data=[];
 else if(path.startsWith('/book-photos/'))data={enabled:false};
 await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
});
try{
 await page.goto('http://127.0.0.1:18144/#/reports');await page.getByRole('heading',{name:'Отчёт по вашим условиям'}).waitFor();
 await page.getByRole('button',{name:'Сформировать отчёт',exact:true}).click();await page.getByText('Проверочная книга',{exact:true}).waitFor();
 assert.ok(await page.getByRole('columnheader',{name:'Заглавие',exact:true}).evaluate(e=>e.getBoundingClientRect().width)>=300);
 assert.ok(await page.getByRole('columnheader',{name:'№ п/п',exact:true}).evaluate(e=>e.getBoundingClientRect().width)<110);
 await page.getByRole('button',{name:'Далее',exact:true}).click();await page.getByText('Строк: 51 · страница 2 из 2').waitFor();
 await page.getByRole('button',{name:/На весь экран/}).click();assert.equal(await page.locator('.ksu-table-expanded').count(),1);await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'+ Добавить условие',exact:true}).click();await page.getByLabel('Значение',{exact:true}).fill('Книга');
 assert.equal(await page.getByRole('button',{name:/Скачать Excel/}).isDisabled(),true);
 await page.getByRole('button',{name:'Сформировать отчёт',exact:true}).click();await page.getByText('Строк: 51 · страница 1 из 2').waitFor();assert.equal(lastDefinition.filters[0].value,'Книга');
 await page.getByLabel('Название шаблона',{exact:true}).fill('Моя выборка');await page.getByRole('button',{name:'Сохранить шаблон',exact:true}).click();await page.getByText('Шаблон сохранён. Он доступен в вашей учётной записи.').waitFor();assert.equal(templates.length,1);
 const download=page.waitForEvent('download');await page.getByRole('button',{name:/Скачать Excel/}).click();assert.equal((await download).suggestedFilename(),'Отчёт библиотеки.xlsx');
 await page.reload();await page.getByLabel('Открыть шаблон').selectOption('1');assert.equal(await page.getByLabel('Значение',{exact:true}).inputValue(),'Книга');
 await page.getByLabel('Одна строка — это').selectOption('summary');await page.getByRole('button',{name:'Сформировать отчёт',exact:true}).click();await page.getByText('Финансы',{exact:true}).waitFor();assert.equal(lastDefinition.group_by,'primary_specialty');
 await page.getByLabel('Значение',{exact:true}).fill('Пусто');await page.getByRole('button',{name:'Сформировать отчёт',exact:true}).click();await page.getByText(/По этим условиям ничего не найдено/).waitFor();
 fail=true;await page.getByRole('button',{name:'Сформировать отчёт',exact:true}).click();await page.getByRole('alert').waitFor();fail=false;
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/tmp/utblib-reports-mobile.png',fullPage:true});
 assert.equal(await page.locator('.reports-page').evaluate(e=>e.scrollWidth<=e.clientWidth+2),true);
 await page.setViewportSize({width:1440,height:1000});await page.getByRole('button',{name:'Новый отчёт',exact:true}).click();await page.screenshot({path:'/tmp/utblib-reports-desktop.png',fullPage:true});
 assert.deepEqual(errors,[]);console.log('Reports UI: preview, pagination, fullscreen, filters, templates, download, reload, summary, empty/error states, mobile — OK');
}finally{await browser.close();await server.close();}
