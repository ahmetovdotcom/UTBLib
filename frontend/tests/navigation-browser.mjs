// Synthetic API only. Does not access a staff database or production server.
import {chromium} from 'playwright';
import {createServer} from 'vite';
import assert from 'node:assert/strict';
const server=await createServer({server:{host:'127.0.0.1',port:18143,strictPort:true}});await server.listen();
const browser=await chromium.launch({headless:true,channel:'chrome'}),context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(12000);
let logged=true,role='admin',slowRecord=false;
const record=id=>({id,type_id:1,version:1,marc:{leader:'00000nam a2200000   4500',fields:[{tag:'245',ind1:'0',ind2:'0',subfields:[{code:'a',value:'Книга '+id}]}]}});
const reader=id=>({id,full_name:'Тестовый читатель '+id,ticket_number:'T'+id,barcode:'T'+id,category:'student',status:'active',field_owners:{},manual_overrides:[],branch_ids:[],identities:[],problems:[],visits:[],website_logins:[],circulation:{loans:[],reservations:[],fines:[],incidents:[]}});
const branch={id:1,name:'Абонемент 1',active:true},loan={id:11,title:'Книга 1',reader_id:7,reader_name:'Тестовый читатель 7',inventory_number:'001',status:'overdue',issued_at:'2026-01-01',due_at:'2026-02-01',days_remaining:-1,events:[],incidents:[]};
const ksu={id:1,number:1,year:2026,registered_on:'2026-01-01',source:'Тест',metrics:{titles:1,copies:1,on_amount:'100',off_amount:'0'},status:'complete',issues:[]};
const event={id:1,title:'Тестовое мероприятие',date_from:'2026-11-12',date_to:'2026-11-12',participants:1,status:'planned'};
const report=u=>({filters:{...Object.fromEntries(u.searchParams),group_by:'day',breakdown:'faculty'},timezone:'Asia/Almaty',rules:'',columns:[],rows:[],months:[],totals:{visits:1,unique:1,categories:{}},summary:{selected_days:1,active_days:1,average_per_day:1,visits_per_reader:1,peak:null},breakdown:[],hours:[],weekdays:[]});
await context.route('**/api/**',async route=>{
 const req=route.request(),u=new URL(req.url()),p=u.pathname.slice(4);requests.push(p+u.search);let data,status=200;
 if(['/auth/me','/auth/login'].includes(p)){if(p==='/auth/login')logged=true;if(!logged){status=401;data={detail:'Login required'};}else data={user:{id:1,role,display_name:'Тест',permissions:role==='admin'?[]:['readers.registry.view']},csrf_token:'synthetic'};}
 else if(p==='/auth/logout'){logged=false;data={};}
 else if(p==='/dictionary')data={fields:[{tag:'245',label:'Title',repeatable:false,indicators:[],subfields:[{code:'a',label:'Title',repeatable:false}]}]};
 else if(p==='/types')data=[{id:1,name:'Книга',config:[{tag:'245',required:true,subfields:['a']}]}];
 else if(p==='/types/1/vocabulary')data=[];
 else if(p==='/records')data=req.method()==='POST'?{...record(99),warnings:[]}:Array.from({length:50},(_,i)=>record(Number(u.searchParams.get('offset')||0)+i+1));
 else if(/^\/records\/\d+$/.test(p)){if(slowRecord)await new Promise(r=>setTimeout(r,300));data=req.method()==='PUT'?{...JSON.parse(req.postData()),id:1,warnings:[]}:record(Number(p.split('/').at(-1)));}
 else if(p==='/records/1/holdings')data={items:[],total:0,summary:{}};
 else if(p.startsWith('/book-photos/'))data={enabled:false,phone_enabled:false};
 else if(p==='/readers/options')data={categories:{student:'Студент'},statuses:{active:'Активен'}};
 else if(p==='/reader-branches')data=[branch];
 else if(p==='/readers')data={items:[reader(7),reader(8)],total:2};
 else if(/^\/readers\/\d+$/.test(p))data=reader(Number(p.split('/').at(-1)));
 else if(p==='/circulation/options')data={branches:[branch],history_branches:[branch]};
 else if(p==='/circulation/dashboard')data={open:1,overdue:1,issued_today:1,returned_today:1,issued_week:1,date:'2026-11-12',week_from:'2026-11-09'};
 else if(p==='/circulation/loans')data={items:[loan],total:1};
 else if(p==='/circulation/loans/11')data=loan;
 else if(p==='/circulation/readers/7')data={...reader(7),used:0,max_loans:10,loans:[],fines:[],reservations:[],incidents:[]};
 else if(p==='/ksu/options')data={};else if(p==='/ksu/rules')data={items:[]};
 else if(p==='/ksu/report')data={year:2026,rows:[ksu],totals:ksu.metrics,columns:[],next_number:2};
 else if(p==='/ksu/entries/1/copies')data={entry:ksu,items:[{id:1,record_id:1,title:'Книга 1',inventory_number:'001',status:'active'}],total:1,totals:{}};
 else if(p==='/ksu/specialties/report')data={rows:[],columns:[],total:{titles:0,copies:0,amount:0,unpriced_count:0},date_from:'2026-01-01',date_to:'2026-12-31'};
 else if(p==='/events/options')data={branches:[branch],formats:[],statuses:{planned:'Запланировано'}};
 else if(p==='/events')data={items:[event],total:1,participants:1};else if(p==='/events/1')data=event;
 else if(p.includes('/report/options')||p==='/statistics/attendance/options')data={filters:{},dimensions:{faculty:'Факультет'}};
 else if(p.includes('/report/journal')||p==='/statistics/attendance/journal')data={items:[{id:1,reader_id:7,full_name:'Тестовый читатель 7',visited_at:'2026-11-12T00:00:00Z'}],total:1};
 else if(p==='/events/1/report'||p==='/statistics/attendance')data=report(u);
 else if(p==='/acquisitions')data={items:[],total:0};
 else if(p==='/acquisitions/1')data={id:1,version:1,invoice:'QA',source:'Тест',received_on:'2026-11-12',lines:[],copies:[]};
 else if(p==='/visits')data={items:[{id:1,reader_id:7,full_name:'Тестовый читатель 7',scanned_at:'2026-11-12T00:00:00Z'}],total:1};
 else if(p==='/visits/analytics')data={today:{visits:1,unique:1},visits:1,unique:1,branches:[],categories:[],days:[]};
 else if(p==='/site-content')data={items:[],total:0};
 else {data={detail:'Unhandled synthetic API '+p};status=404;}
 await route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
});
const heading=s=>page.getByRole('heading',{name:s,exact:true});
const nav=async name=>page.locator('.module-nav').getByRole('button',{name:new RegExp(name+'$')}).click();
const back=()=>page.goBack();
try{
 await page.goto('http://127.0.0.1:18143');await heading('Каталог записей').waitFor();
 await page.getByLabel('Поиск',{exact:true}).fill('сохранённый поиск');await page.getByRole('button',{name:'Найти',exact:true}).click();
 await page.getByRole('button',{name:'Далее →',exact:true}).first().click();await page.waitForURL('**/#/catalog?offset=50');
 await page.locator('.record-title').first().click();await heading('Редактирование записи').waitFor();assert(page.url().includes('record=51'));
 await back();await page.locator('.record-title').filter({hasText:'Книга 51'}).waitFor();assert.equal(await page.getByLabel('Поиск',{exact:true}).inputValue(),'сохранённый поиск');
 await page.goForward();await heading('Редактирование записи').waitFor();await page.reload();await heading('Редактирование записи').waitFor();
 await nav('Читатели');await heading('Читатели').waitFor();await page.getByRole('button',{name:'Тестовый читатель 7',exact:true}).click();await heading('Тестовый читатель 7').waitFor();
 await page.getByRole('button',{name:'Книги',exact:true}).click();await page.waitForURL('**/readers?reader=7&tab=books');await page.reload();await heading('Тестовый читатель 7').waitFor();
 await nav('Книговыдача');await page.getByRole('button',{name:/Просроченные/}).first().click();await page.waitForURL('**/circulation?tab=history&metric=overdue**');
 await page.getByRole('button',{name:'Тестовый читатель 7',exact:true}).click();await heading('Тестовый читатель 7').waitFor();await back();await heading('Просроченные').waitFor();
 await nav('КСУ');await page.getByRole('button',{name:'Экземпляры',exact:true}).click();await page.locator('dialog[open]').waitFor();
 await page.locator('dialog[open]').getByRole('button',{name:/Книга 1/}).click();await heading('Редактирование записи').waitFor();await back();await page.locator('dialog[open]').waitFor();await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.querySelector('dialog[open]'));
 await nav('Мероприятия');await page.getByRole('button',{name:'Тестовое мероприятие',exact:true}).click();await heading('Тестовое мероприятие').waitFor();
 await page.getByRole('button',{name:'Открыть журнал →',exact:true}).click();await page.getByRole('button',{name:'Тестовый читатель 7',exact:true}).click();await heading('Тестовый читатель 7').waitFor();await back();await heading('Тестовое мероприятие').waitFor();await heading('Детализация посещений').waitFor();
 await nav('Каталогизация и классификация');await page.locator('.record-title').first().click();await heading('Редактирование записи').waitFor();const title=page.locator('[data-field="245"] input').first();await title.fill('Несохранённое');
 page.once('dialog',d=>d.dismiss());await back();await page.waitForTimeout(100);await heading('Редактирование записи').waitFor();assert.equal(await title.inputValue(),'Несохранённое');
 page.once('dialog',d=>d.accept());await back();await heading('Каталог записей').waitFor();
 await page.getByRole('button',{name:'＋ Создать запись',exact:true}).click();await heading('Новая запись').waitFor();await title.fill('Новая книга');await page.getByRole('button',{name:'✓ Сохранить запись',exact:true}).click();await page.waitForURL('**/catalog?record=99&tab=description');await heading('Редактирование записи').waitFor();
 slowRecord=true;await nav('Каталогизация и классификация');await page.locator('.record-title').first().click();await nav('Читатели');await heading('Читатели').waitFor();await page.waitForTimeout(400);slowRecord=false;await nav('Каталогизация и классификация');await heading('Каталог записей').waitFor();
 // Scroll restoration waits for the list and avoids jumping to the start.
 await page.locator('.record-title').nth(20).scrollIntoViewIfNeeded();const beforeScroll=await page.evaluate(()=>scrollY);
 await page.locator('.record-title').nth(20).click();await heading('Редактирование записи').waitFor();await back();await heading('Каталог записей').waitFor();await page.waitForFunction(y=>Math.abs(scrollY-y)<5,beforeScroll);
 // A new search on a later page must reset both list pagination and its URL.
 await page.getByRole('button',{name:'Далее →',exact:true}).first().click();await page.waitForURL('**/catalog?offset=50');await page.getByRole('button',{name:'Найти',exact:true}).click();await page.waitForURL('**/#/catalog');
 await nav('Поступления');await page.getByRole('button',{name:'＋ Новое поступление',exact:true}).click();await heading('Новое поступление').waitFor();
 await page.getByLabel('Накладная',{exact:true}).fill('Черновик');page.once('dialog',d=>d.dismiss());await back();await page.waitForTimeout(100);assert.equal(await page.getByLabel('Накладная',{exact:true}).inputValue(),'Черновик');
 page.once('dialog',d=>d.accept());await back();await page.waitForFunction(()=>!document.querySelector('dialog[open]'));
 await page.goto('http://127.0.0.1:18143/#/acquisitions?receipt=1');await page.reload();await heading('Изменить поступление №1').waitFor();await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.querySelector('dialog[open]'));
 await nav('КСУ');await page.getByRole('button',{name:'Поступления по специальностям',exact:true}).click();await heading('Поступления по специальностям').waitFor();await nav('Читатели');await back();await heading('Поступления по специальностям').waitFor();
 await nav('Посещения');await page.getByRole('button',{name:'Тестовый читатель 7',exact:true}).click();await heading('Тестовый читатель 7').waitFor();await page.getByRole('button',{name:'Назад к предыдущей странице',exact:true}).click();await page.getByRole('button',{name:'Тестовый читатель 7',exact:true}).waitFor();
 await nav('Сайт');await page.getByRole('button',{name:'Новости',exact:true}).click();await page.waitForURL('**/site?tab=news');await nav('Читатели');await back();assert(page.url().endsWith('/site?tab=news'));
 logged=false;await page.goto('http://127.0.0.1:18143/#/catalog?record=1');await page.reload();await page.getByLabel('Логин',{exact:true}).fill('qa');await page.getByLabel('Пароль',{exact:true}).fill('synthetic');await page.getByRole('button',{name:'Войти в каталог →',exact:true}).click();await heading('Редактирование записи').waitFor();
 await page.goto('http://127.0.0.1:18143/#/missing');await heading('Страница не найдена').waitFor();role='viewer';await page.goto('http://127.0.0.1:18143/#/catalog?record=1');await page.reload();await heading('Читатели').waitFor();assert(page.url().endsWith('#/readers'));
 await page.goto('http://127.0.0.1:18143/#readers');await page.reload();await heading('Читатели').waitFor();assert(page.url().endsWith('#/readers'));
 assert.deepEqual(errors,[]);console.log('PASS: routing, Back/Forward, reload/login, filters, KSU/catalog, event report/reader, unsaved forms, new-record URL, late requests, access and legacy hashes.');
}catch(e){console.error('URL',page.url(),'Page errors',errors,'Recent API requests',requests.slice(-15));await page.screenshot({path:'/tmp/utblib-navigation-failure.png'});throw e;}
finally{await context.close();await browser.close();await server.close();}
