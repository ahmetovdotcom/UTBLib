// Synthetic catalogue only; never writes staff data.
import {chromium} from 'playwright';
import {createServer} from 'vite';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
const artifacts=await mkdtemp(join(tmpdir(),'utblib-publication-'));
const server=await createServer({server:{host:'127.0.0.1',port:18145,strictPort:true}});await server.listen();
const browser=await chromium.launch({headless:true,channel:'chrome'}),page=await browser.newPage({viewport:{width:1440,height:1000}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
let saved={id:42,version:1,type_id:1,marc:{leader:'00000nam a2200000   4500',fields:[]},is_faculty_work:false,use_first_page_cover:false,electronic_file:null},saves=0;
await page.route('**/api/**',async route=>{
 const req=route.request(),path=new URL(req.url()).pathname.slice(4);let data=[];
 if(path==='/auth/me')data={user:{id:1,role:'admin',display_name:'Тест',permissions:[]},csrf_token:'synthetic-csrf'};
 else if(path==='/dictionary')data={fields:[]};else if(path==='/types')data=[{id:1,name:'Книга',config:[]}];
 else if(path==='/records/42'&&req.method()==='GET')data=saved;
 else if(path==='/catalog-files'){
  assert.equal(req.headers()['x-csrf-token'],'synthetic-csrf');assert.equal(req.headers()['content-type'],'application/pdf');
  data={token:'synthetic-upload',name:'test.pdf',pages:2,size:3000};
 }else if(path==='/records/42'&&req.method()==='PUT'){
  const body=req.postDataJSON();assert(!('electronic_file' in body));saves++;assert.equal(body.is_faculty_work,true);
  saved={...saved,...body,version:saved.version+1,electronic_file:body.digital_upload===null?null:{name:'test.pdf',pages:2,size:3000}};delete saved.digital_upload;data={...saved,warnings:[]};
 }
 await route.fulfill({json:data});
});
try{
 await page.goto('http://127.0.0.1:18145/#/catalog?record=42');
 await page.getByLabel('Труды ППС',{exact:true}).check();
 await page.locator('input[type=file][accept="application/pdf,.pdf"]').setInputFiles({name:'test.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-synthetic')});
 await page.getByText('test.pdf',{exact:true}).waitFor();
 await page.getByLabel('Взять первую страницу как обложку',{exact:true}).check();
 assert.equal(saves,0);
 await page.getByRole('button',{name:'✓ Сохранить запись',exact:true}).click();
 await page.getByRole('status').filter({hasText:'Запись сохранена'}).waitFor();assert.equal(saves,1);assert(saved.use_first_page_cover);
 await page.reload();await page.getByText('test.pdf',{exact:true}).waitFor();assert(await page.getByLabel('Труды ППС',{exact:true}).isChecked());
 await page.screenshot({path:join(artifacts,'editor.png'),fullPage:true});
 await page.getByRole('button',{name:'Убрать файл',exact:true}).click();assert(!(await page.getByLabel('Взять первую страницу как обложку',{exact:true}).isChecked()));
 assert.equal(saves,1);await page.getByRole('button',{name:'✓ Сохранить запись',exact:true}).click();await page.getByRole('status').filter({hasText:'Запись сохранена'}).waitFor();assert.equal(saves,2);assert.equal(saved.electronic_file,null);
 assert.deepEqual(errors,[]);console.log('Publication checkbox, upload, CSRF, save/reload, file removal: OK',artifacts);
}catch(e){await page.screenshot({path:join(artifacts,'failure.png'),fullPage:true});throw e;}finally{await browser.close();await server.close();}
