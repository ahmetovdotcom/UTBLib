<script setup lang="ts">
import {computed,onMounted,ref} from 'vue';
const props=defineProps<{api:(path:string,method?:string,body?:any)=>Promise<any>,csrf:string}>();
const sections:Record<string,string>={resources:'Ресурсы',repository:'Репозиторий',news:'Новости',events:'События'};
const kind=ref('resources'),items=ref<any[]>([]),total=ref(0),page=ref(1),q=ref(''),busy=ref(false),error=ref(''),message=ref(''),editor=ref<any>(null),locale=ref('ru'),baseline=ref('');
const languages:Record<string,string>={ru:'Русский',kk:'Қазақша',en:'English'};
const statuses:Record<string,string>={draft:'Черновик',published:'Опубликовано',archived:'Архив'};
const contentTypes:Record<string,string>={electronic_books:'Электронные книги',scientific_articles:'Научные статьи',dissertations:'Диссертации',research_reports:'Научные отчёты',faculty_works:'Труды преподавателей',journals:'Журналы',research_data:'Данные исследований',educational_materials:'Учебные материалы',multimedia:'Мультимедиа',braille_books:'Книги Брайля',audiobooks:'Аудиокниги',catalogues:'Каталоги'};
const workTypes:Record<string,string>={bachelor_thesis:'Дипломная работа',master_thesis:'Магистерская диссертация',phd_dissertation:'Докторская диссертация',scientific_article:'Научная статья',research_report:'Научный отчёт',university_publication:'Издание университета',thesis_abstract:'Автореферат'};
const repositoryFields:Record<string,string>={faculty:'Факультет',department:'Кафедра',educational_programme:'Специальность',supervisor:'Научный руководитель',udc_code:'УДК',university:'Университет',doi:'DOI',source:'Источник',rights_holder:'Правообладатель',licence_type:'Лицензия'};
const text=computed(()=>editor.value?.data.translations[locale.value]);
function title(item:any){return item.data.translations.ru?.title||item.data.translations.kk?.title||item.data.translations.en?.title||item.slug;}
async function run(fn:()=>Promise<void>){busy.value=true;error.value='';message.value='';try{await fn();}catch(e){error.value=String(e).replace(/^Error: /,'');}finally{busy.value=false;}}
async function load(){const r=await props.api(`/site-content?kind=${kind.value}&page=${page.value}&q=${encodeURIComponent(q.value)}`);items.value=r.items;total.value=r.total;}
function open(item?:any){editor.value=item?JSON.parse(JSON.stringify(item)):{kind:kind.value,slug:'',status:'draft',published_at:null,data:{translations:{},featured:false,url:'',resource_type:'open_access',access_type:'open',category:'',authors:[],keywords:[],content_types:[],audiences:[],work_type:'scientific_article',language:'ru',access_policy:'metadata_only'},assets:{}};for(const l of Object.keys(languages))editor.value.data.translations[l]??={title:'',description:'',body:'',instructions:'',venue:'',image_alt:''};locale.value='ru';baseline.value=JSON.stringify(editor.value);error.value='';message.value='';}
function close(){if(JSON.stringify(editor.value)!==baseline.value&&!window.confirm('Закрыть без сохранения изменений?'))return;editor.value=null;error.value='';}
async function save(){await run(async()=>{const e=editor.value;if(e.data.year==='')e.data.year=null;const saved=await props.api('/site-content'+(e.id?'/'+e.id:''),e.id?'PUT':'POST',{kind:e.kind,slug:e.slug,status:e.status,version:e.version,published_at:e.published_at||null,data:e.data});open(saved);await load();message.value=saved.status==='published'?'Сохранено. Материал доступен на сайте после наступления даты публикации.':'Материал сохранён.';});}
async function switchSection(k:string){if(editor.value){close();if(editor.value)return;}kind.value=k;page.value=1;q.value='';await run(load);}
function changeList(key:string,event:Event){editor.value.data[key]=(event.target as HTMLTextAreaElement).value.split('\n').map(v=>v.trim()).filter(Boolean);}
function localDate(value:string|null){if(!value)return '';const d=new Date(value);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}
function setDate(key:string,event:Event){const value=(event.target as HTMLInputElement).value;const target=key==='published_at'?editor.value:editor.value.data;target[key]=value?new Date(value).toISOString():null;}
async function upload(slot:string,event:Event){const input=event.target as HTMLInputElement,file=input.files?.[0];if(!file)return;await run(async()=>{if(file.size>(slot==='pdf'?25:8)*1024*1024)throw new Error('Файл слишком большой: изображение до 8 МБ, PDF до 25 МБ');const e=editor.value;const response=await fetch(`/api/site-content/${e.id}/assets/${slot}?version=${e.version}`,{method:'PUT',headers:{'X-CSRF-Token':props.csrf,'Content-Type':file.type||'application/octet-stream'},body:file});const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Не удалось загрузить файл');open(data);await load();message.value='Файл сохранён.';});input.value='';}
async function removeAsset(slot:string){await run(async()=>{const e=editor.value;open(await props.api(`/site-content/${e.id}/assets/${slot}?version=${e.version}`,'DELETE'));await load();});}
const cleanEditor=computed(()=>JSON.stringify(editor.value)===baseline.value);
onMounted(()=>run(load));
</script>

<template>
<section class="site-content">
 <header class="page-heading"><div><h1>Сайт библиотеки</h1><p>Материалы для посетителей. Публикации появятся на готовом сайте библиотеки.</p></div><button v-if="!editor" class="primary" @click="open()" :disabled="busy">+ Добавить</button></header>
 <nav class="site-tabs" aria-label="Разделы сайта"><button v-for="(name,key) in sections" :key="key" :class="{selected:kind===key}" :disabled="busy" @click="switchSection(key)">{{name}}</button></nav>
 <p v-if="error" role="alert" class="error">{{error}}</p><p v-if="message" role="status" class="site-success">{{message}}</p>
 <template v-if="!editor">
  <form class="site-search" @submit.prevent="page=1;run(load)"><input v-model="q" placeholder="Найти материал" aria-label="Поиск материалов"><button :disabled="busy">Найти</button><span>{{total}} материалов</span></form>
  <div class="site-card"><table><thead><tr><th>Название</th><th>Состояние</th><th>Адрес страницы</th><th></th></tr></thead><tbody><tr v-for="item in items" :key="item.id"><td>{{title(item)}}</td><td>{{statuses[item.status]}}</td><td>{{item.slug}}</td><td><button @click="open(item)" :disabled="busy">Открыть</button></td></tr><tr v-if="!items.length"><td colspan="4">Пока нет материалов. Добавьте первую публикацию.</td></tr></tbody></table></div>
  <div class="site-search"><button :disabled="busy||page===1" @click="page--;run(load)">Назад</button><span>Страница {{page}}</span><button :disabled="busy||page*30>=total" @click="page++;run(load)">Далее</button></div>
 </template>
 <form v-else @submit.prevent="save" class="site-card site-editor">
  <div class="site-search"><h2>{{editor.id?'Редактирование':'Новый материал'}} · {{sections[kind]}}</h2><button type="button" @click="close" :disabled="busy">К списку</button></div>
  <fieldset :disabled="busy"><div class="site-grid">
   <label>Адрес страницы (латиница, цифры, дефис)<input v-model="editor.slug" required maxlength="160" pattern="[a-z0-9][a-z0-9-]*" placeholder="library-news-2026"></label>
   <label>Состояние<select v-model="editor.status"><option v-for="(name,key) in statuses" :value="key">{{name}}</option></select></label>
   <label>Дата публикации<input type="datetime-local" :value="localDate(editor.published_at)" @input="setDate('published_at',$event)"><small>Пусто — при публикации. Будущая дата откладывает показ на сайте.</small></label>
   <label class="site-checkbox"><input type="checkbox" v-model="editor.data.featured">Показывать на главной / выделить</label>
  </div>
  <nav class="site-tabs" aria-label="Язык материала"><button type="button" v-for="(name,key) in languages" :class="{selected:locale===key}" @click="locale=key">{{name}}</button></nav>
  <p class="muted">Достаточно заполнить один язык. На сайте при отсутствии перевода будет показан имеющийся текст.</p>
  <label>Название · {{languages[locale]}}<input v-model="text.title" maxlength="500"></label>
  <label>{{kind==='repository'?'Аннотация':'Краткое описание'}}<textarea v-model="text.description" rows="3" maxlength="5000"></textarea></label>
  <template v-if="kind==='news'||kind==='events'"><label>Текст публикации<textarea v-model="text.body" rows="10" maxlength="100000"></textarea><small>Абзацы разделяйте пустой строкой.</small></label><label>Описание изображения<input v-model="text.image_alt" maxlength="500"></label></template>
  <label v-if="kind==='resources'">Условия и инструкция доступа<textarea v-model="text.instructions" rows="4" maxlength="10000"></textarea></label>
  <label v-if="kind==='events'">Место проведения<input v-model="text.venue" maxlength="500"></label>
  <div v-if="kind==='resources'" class="site-grid">
   <label>Ссылка на ресурс<input type="url" v-model="editor.data.url" maxlength="2000"></label><label>Поставщик / организация<input v-model="editor.data.provider" maxlength="300"></label>
   <label>Тип ресурса<select v-model="editor.data.resource_type"><option value="open_access">Открытый</option><option value="licensed">Лицензионный</option><option value="partner">Партнёрский</option><option value="internal">Внутренний</option></select></label>
   <label>Доступ<select v-model="editor.data.access_type"><option value="open">Для всех</option><option value="campus">В сети университета</option><option value="remote_auth">После входа на сайт</option></select></label>
   <label>Доступ действует до<input type="date" v-model="editor.data.expires_on"></label>
   <label>Категория<select v-model="editor.data.category"><option value="">Не указана</option><option value="research_database">Научная база</option><option value="electronic_library">Электронная библиотека</option><option value="open_access">Открытый доступ</option><option value="analytics">Аналитика и СМИ</option></select></label>
  </div>
  <div v-if="kind==='resources'" class="site-grid"><label v-for="(name,key) in contentTypes" class="site-checkbox"><input type="checkbox" :value="key" v-model="editor.data.content_types">{{name}}</label></div>
  <label v-if="kind==='news'">Тип публикации<select v-model="editor.data.news_type"><option value="announcement">Объявление</option><option value="update">Обновление</option></select></label>
  <div v-if="kind==='events'" class="site-grid"><label>Начало<input type="datetime-local" :value="localDate(editor.data.starts_at)" @input="setDate('starts_at',$event)"></label><label>Окончание<input type="datetime-local" :value="localDate(editor.data.ends_at)" @input="setDate('ends_at',$event)"></label><label>Регистрация<input type="url" v-model="editor.data.registration_url"></label><label>Онлайн-трансляция<input type="url" v-model="editor.data.online_url"></label><label>Организатор<input v-model="editor.data.organizer" maxlength="500"></label></div>
  <div v-if="kind==='repository'" class="site-grid">
   <label>Вид работы<select v-model="editor.data.work_type"><option v-for="(name,key) in workTypes" :value="key">{{name}}</option></select></label><label>Год<input type="number" v-model.number="editor.data.year" min="1000" max="2200"></label>
   <label>Язык работы<select v-model="editor.data.language"><option v-for="(name,key) in languages" :value="key">{{name}}</option><option value="other">Другой</option></select></label>
   <label>Авторы (по одному в строке)<textarea :value="editor.data.authors.join('\n')" @input="changeList('authors',$event)"></textarea></label><label>Ключевые слова (по одному в строке)<textarea :value="editor.data.keywords.join('\n')" @input="changeList('keywords',$event)"></textarea></label>
   <label v-for="(name,key) in repositoryFields">{{name}}<input v-model="editor.data[key]" :maxlength="key==='source'?1000:key==='udc_code'?100:500"></label>
   <label>Доступ к PDF<select v-model="editor.data.access_policy"><option value="metadata_only">Только описание, PDF закрыт</option><option value="full_public">Открытый PDF для всех</option></select></label>
   <label>Не открывать PDF до<input type="datetime-local" :value="localDate(editor.data.embargo_until)" @input="setDate('embargo_until',$event)"></label>
  </div>
  <div v-if="editor.id" class="site-files"><h3>Файлы</h3><p v-if="!cleanEditor" class="muted">Сначала сохраните изменения текста, затем прикрепите файл.</p><label>Изображение (до 8 МБ)<input type="file" accept="image/jpeg,image/png,image/webp" :disabled="!cleanEditor" @change="upload('image',$event)"></label><div v-if="editor.assets.image">Изображение загружено · <a :href="`/api/site-content/${editor.id}/assets/image`" target="_blank" rel="noopener">Просмотреть</a> <button type="button" :disabled="!cleanEditor" @click="removeAsset('image')">Убрать</button></div><template v-if="kind==='repository'"><label>Полный текст PDF (до 25 МБ)<input type="file" accept="application/pdf" :disabled="!cleanEditor" @change="upload('pdf',$event)"></label><div v-if="editor.assets.pdf">PDF загружен · {{Math.ceil(editor.assets.pdf.size/1024)}} КБ · <a :href="`/api/site-content/${editor.id}/assets/pdf`" target="_blank" rel="noopener">Просмотреть</a> <button type="button" :disabled="!cleanEditor" @click="removeAsset('pdf')">Убрать</button></div></template></div>
  <p v-else class="muted">После первого сохранения можно загрузить изображение и PDF работы.</p>
  <button class="primary" :disabled="busy">{{busy?'Сохранение…':'Сохранить'}}</button>
  </fieldset>
 </form>
</section>
</template>

<style scoped>
.page-heading,.site-search{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.site-tabs{display:flex;gap:8px;border-bottom:1px solid #dce5ed;padding:14px 0;margin-bottom:20px}.site-tabs .selected{background:#00233e;color:white}.site-card{border:1px solid #dce5ed;background:white;border-radius:20px;overflow:auto;margin:20px 0}.site-editor{padding:28px}.site-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.site-editor label{display:flex;flex-direction:column;gap:8px;margin-bottom:20px;font-weight:600}.site-editor input,.site-editor select,.site-editor textarea{width:100%;box-sizing:border-box}.site-editor .site-checkbox{flex-direction:row;align-items:center}.site-checkbox input{width:auto}.site-editor fieldset{border:0;padding:0;min-width:0}.site-editor small,.muted{font-weight:400;color:#66758b}.site-files{border-top:1px solid #dce5ed;padding-top:18px;margin:20px 0}.site-success{background:#eafbf2;color:#146443;padding:14px;border-radius:12px}.site-content table{width:100%}.site-content th,.site-content td{text-align:left;padding:18px;border-bottom:1px solid #e4ebf2}.site-content th{background:#f3f6fa}.site-search input{min-width:260px;flex:1}@media(max-width:800px){.site-grid{grid-template-columns:1fr}.site-tabs{flex-wrap:wrap}.site-editor{padding:16px}}
</style>
