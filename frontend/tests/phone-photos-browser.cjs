/* Run against an isolated QA server; never seed the working catalogue. */
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const base=process.env.PHOTO_QA_URL;if(!base)throw Error('Set PHOTO_QA_URL for the isolated test instance');
 const address=new URL(base);if(!['127.0.0.1','localhost'].includes(address.hostname)||address.port!=='18141')throw Error('Only the disposable QA server on port 18141 is allowed');
 const fs=require('node:fs'),os=require('node:os'),path=require('node:path');const artifacts=fs.mkdtempSync(path.join(os.tmpdir(),'utblib-phone-browser-'));
 const browser=await chromium.launch({headless:true,channel:process.env.PHOTO_QA_BROWSER||'chrome'});
 const desktop=await browser.newPage({viewport:{width:1440,height:1050}});
 const phone=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 const issues=[];for(const p of [desktop,phone])p.on('pageerror',e=>issues.push(e.message));
 let pairings=0;phone.on('request',r=>{if(r.url().endsWith('/mobile/pair'))pairings++;});
 try{
  await desktop.goto(base);
  await desktop.getByLabel('Логин',{exact:true}).fill('admin');await desktop.getByLabel('Пароль',{exact:true}).fill('test-secret');
  await desktop.getByRole('button',{name:'Войти в каталог →'}).click();
  await desktop.getByRole('heading',{name:'Каталог записей'}).waitFor();
  await desktop.evaluate(async()=>{
   const auth=await (await fetch('/api/auth/me')).json();
   const types=await(await fetch('/api/types')).json();
   for(const name of ['QA Book Alpha','QA Book Beta']){
    const existing=await(await fetch('/api/records?q='+encodeURIComponent(name))).json();if(existing.some(r=>r.marc.fields.some(f=>f.tag==='245'&&f.subfields?.some(s=>s.code==='a'&&s.value===name))))continue;
    const r=await fetch('/api/records',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':auth.csrf_token},body:JSON.stringify({type_id:types[0].id,marc:{leader:'00000nam a2200000   4500',fields:[{tag:'245',ind1:'0',ind2:'0',subfields:[{code:'a',value:name}]}]}})});
    if(!r.ok)throw Error(await r.text());
   }
  });
  await desktop.reload();
  await desktop.getByRole('button',{name:/QA Book Alpha/}).click();
  await desktop.getByRole('button',{name:'Заполнить по фото',exact:true}).click();
  await desktop.getByRole('button',{name:'Подключить телефон по QR-коду'}).click();
  const link=await desktop.getByRole('link',{name:'Открыть страницу подключения'}).getAttribute('href');
  assert(link.includes('/phone-photos#pair='));
  await phone.goto(link);
  await phone.getByText('Телефон подключён',{exact:true}).waitFor();
  await phone.getByRole('heading',{name:/QA Book Alpha/}).waitFor();
  assert.equal(await phone.evaluate(()=>location.hash),'');
  const fixtures={};for(const [name,color] of [['qa-a.png','white'],['qa-b.png','lightblue']]){
   const data=await desktop.evaluate(color=>{const c=document.createElement('canvas');c.width=240;c.height=320;const ctx=c.getContext('2d');ctx.fillStyle=color;ctx.fillRect(0,0,240,320);return c.toDataURL('image/png').split(',')[1];},color);
   fixtures[name]={name,mimeType:'image/png',buffer:Buffer.from(data,'base64')};
  }
  let lostReply=true;await phone.route('**/api/photo-transfer/mobile/photos',async route=>{if(lostReply){lostReply=false;await route.fetch();await route.abort('failed');}else await route.continue();});
  const upload=async(name)=>{
   const chooser=phone.waitForEvent('filechooser');await phone.getByRole('button',{name:'Сделать фото',exact:true}).click();
   await(await chooser).setFiles(fixtures[name]);
  };
  await upload('qa-a.png');
  await desktop.locator('.photo-thumbnails figure').first().waitFor();
  await desktop.getByLabel('Выбрать фотографии книги',{exact:true}).setInputFiles(fixtures['qa-b.png']);
  await desktop.waitForFunction(()=>document.querySelectorAll('.photo-thumbnails figure').length===2);
  await desktop.screenshot({path:path.join(artifacts,'desktop.png'),fullPage:false});
  await phone.screenshot({path:path.join(artifacts,'phone.png'),fullPage:true});
  assert(await phone.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  let analyzed=0;
  await desktop.route('**/api/book-photos/analyze',async route=>{
   analyzed++;const body=route.request().postDataJSON();assert.equal(body.images.length,2);
   await route.fulfill({json:{fields:[],warnings:[],usage:null,request_sent:false}});
  });
  await desktop.getByRole('button',{name:'Распознать',exact:true}).click();
  await desktop.getByText('Запрос в OpenAI не отправлялся — расхода на распознавание нет.').waitFor();
  assert.equal(analyzed,1);
  // Open camera on A, then change the desktop to B BEFORE the shutter/file returns.
  const oldChooser=phone.waitForEvent('filechooser');await phone.getByRole('button',{name:'Сделать фото',exact:true}).click();
  const held=await oldChooser;
  await desktop.getByRole('button',{name:'Закрыть распознавание'}).click();
  await desktop.getByRole('button',{name:'← К списку записей',exact:true}).click();
  await desktop.getByRole('button',{name:/QA Book Beta/}).click();
  await desktop.getByRole('button',{name:'Заполнить по фото',exact:true}).click();
  await phone.getByRole('heading',{name:/QA Book Beta/}).waitFor();
  await held.setFiles(fixtures['qa-a.png']);
  await phone.getByRole('alert').filter({hasText:'выбрана другая книга'}).waitFor();
  assert.equal(await desktop.locator('.photo-thumbnails figure').count(),0);
  await upload('qa-b.png');
  await desktop.locator('.photo-thumbnails figure').first().waitFor();
  assert.equal(pairings,1);
  await phone.reload();await phone.getByRole('heading',{name:/QA Book Beta/}).waitFor();
  assert.equal(pairings,1);
  await desktop.getByRole('button',{name:'Удалить фото 1'}).click();
  await phone.getByText('Снимков пока нет.',{exact:true}).waitFor();
  await desktop.getByRole('button',{name:'Отключить телефон',exact:true}).click();
  await phone.getByRole('alert').filter({hasText:'Подключение завершено'}).waitFor();
  assert.deepEqual(issues,[]);
  console.log('PASS: pairing, lost-response retry, phone/manual uploads, recognition, stale camera rejection, next book without new QR, reload, remove, disconnect, mobile layout');
 }catch(e){console.log('Desktop:',(await desktop.locator('body').innerText()).slice(-1800));console.log('Phone:',(await phone.locator('body').innerText()).slice(-1500));throw e;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
