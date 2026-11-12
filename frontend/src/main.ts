import {createApp} from 'vue';
import App from './App.vue';
import PhonePhotos from './PhonePhotos.vue';
import {makeRouter} from './navigation';
import './style.css';
import './theme.css';
if(location.pathname==='/phone-photos')createApp(PhonePhotos).mount('#app');
else {
 const router=makeRouter();
 const app=createApp(App).use(router);
 router.isReady().then(()=>app.mount('#app'));
}
