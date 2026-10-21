// Run against the disposable restored stack only; never creates production users.
const {chromium}=require('playwright');
(async()=>{
 const base='http://localhost:8097';
 const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 const problems=[];
 async function page(){const context=await browser.newContext({viewport:{width:1440,height:1000}});const p=await context.newPage();p.on('pageerror',e=>problems.push(String(e)));await p.goto(base);return p;}
 async function login(p,name,password){await p.getByLabel('Логин',{exact:true}).fill(name);await p.getByLabel('Пароль',{exact:true}).fill(password);await p.getByRole('button',{name:'Войти в каталог →',exact:true}).click();await p.getByRole('heading',{name:'Каталог записей',exact:true}).waitFor();}
 try{
 const admin=await page();await login(admin,'admin',process.env.AUTH_TEST_PASSWORD||'test-secret');
 await admin.getByRole('button',{name:'Пользователи и права',exact:true}).click();await admin.getByRole('button',{name:'Создать пользователя',exact:true}).click();
 const dialog=admin.locator('dialog[open]');const name='browser'+Date.now();
 await dialog.getByLabel('ФИО пользователя',{exact:true}).fill('Проверка браузера');await dialog.getByLabel('Логин',{exact:true}).fill(name);await dialog.getByLabel('Пароль',{exact:true}).fill('browser-password');
 await dialog.getByRole('button',{name:'Сохранить пользователя'}).click();await admin.getByRole('status').filter({hasText:'Пользователь создан'}).waitFor();
 const viewer=await page();await login(viewer,name,'browser-password');
 if(await viewer.getByRole('button',{name:'＋ Создать запись',exact:true}).count())throw Error('Viewer has create button');
 if(await viewer.getByRole('button',{name:'Пользователи и права',exact:true}).count())throw Error('Viewer has user management');
 await viewer.reload();await viewer.getByRole('heading',{name:'Каталог записей',exact:true}).waitFor();
 await viewer.locator('.record-title').first().click();await viewer.getByText('Режим просмотра',{exact:true}).waitFor();
 if(await viewer.getByRole('button',{name:'✓ Сохранить запись',exact:true}).count())throw Error('Viewer can save');
 if((await viewer.request.get(base+'/api/users')).status()!==403)throw Error('Viewer API not denied');
 await admin.locator('tr').filter({hasText:name}).getByRole('button',{name:'Настроить права'}).click();
 await dialog.getByRole('combobox').selectOption('librarian');await dialog.getByRole('button',{name:'Сохранить пользователя'}).click();await admin.getByRole('status').filter({hasText:'Права обновлены'}).waitFor();
 if((await viewer.request.get(base+'/api/auth/me')).status()!==401)throw Error('Session not revoked');
 await viewer.reload();await login(viewer,name,'browser-password');await viewer.getByRole('button',{name:'＋ Создать запись',exact:true}).waitFor();
 await viewer.getByRole('button',{name:'＋ Создать запись',exact:true}).click();
 const operator=viewer.locator('[data-field="097"] input').first();if(await operator.inputValue()!=='Проверка браузера')throw Error('Operator name not populated');if(await operator.getAttribute('readonly')!==null)throw Error('Operator must be editable');await operator.fill('Другой оператор');if(await operator.inputValue()!=='Другой оператор')throw Error('Operator edit failed');
 await viewer.getByRole('button',{name:'← К списку записей',exact:true}).click();
 await viewer.getByRole('button',{name:'Сменить пароль',exact:true}).click();const passwordDialog=viewer.locator('dialog[open]');
 await passwordDialog.getByLabel('Текущий пароль',{exact:true}).fill('browser-password');await passwordDialog.getByLabel('Новый пароль',{exact:true}).fill('changed-password');await passwordDialog.getByLabel('Повторите новый пароль',{exact:true}).fill('changed-password');await passwordDialog.getByRole('button',{name:'Изменить пароль',exact:true}).click();
 await login(viewer,name,'changed-password');await viewer.getByRole('button',{name:'Выйти',exact:true}).click();await viewer.getByLabel('Логин',{exact:true}).waitFor();
 if((await viewer.request.get(base+'/api/records')).status()!==401)throw Error('Logout failed');
 await admin.getByRole('button',{name:'Обновить список',exact:true}).click();
 await admin.locator('tr').filter({hasText:name}).getByRole('button',{name:'Удалить пользователя '+name,exact:true}).click();
 const deletion=admin.locator('dialog[open]');await deletion.getByRole('button',{name:'Отмена',exact:true}).click();
 await admin.locator('tr').filter({hasText:name}).getByRole('button',{name:'Удалить пользователя '+name,exact:true}).click();
 await deletion.getByRole('button',{name:'Подтвердить удаление',exact:true}).click();await admin.getByRole('status').filter({hasText:'Пользователь удалён'}).waitFor();
 if(await admin.locator('tr').filter({hasText:name}).count())throw Error('Deleted user still listed');
 await admin.getByRole('button',{name:'Удалить пользователя admin',exact:true}).click();await deletion.getByRole('button',{name:'Подтвердить удаление',exact:true}).click();await deletion.getByRole('alert').filter({hasText:'последнего активного администратора'}).waitFor();await deletion.getByRole('button',{name:'Отмена',exact:true}).click();
 if(problems.length)throw Error(problems.join('\n'));
 console.log('Browser auth passed: admin creates staff, viewer restrictions, session reload, permission change revocation, librarian login, password change and logout.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
