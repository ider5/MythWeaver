import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { installUiPrefs } from './composables/useUiPrefs'
import './assets/main.css'

installUiPrefs()

createApp(App).use(createPinia()).use(router).mount('#app')
