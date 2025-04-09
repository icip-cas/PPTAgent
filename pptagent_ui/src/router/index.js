import { createRouter, createWebHistory } from 'vue-router'
import UploadComponent from '../components/Upload.vue'
import GenerateComponent from '../components/Generate.vue'

// ... existing routes ...

const routes = [
  {
    path: '/',
    name: 'Upload',
    component: UploadComponent
  },
  // Removed Doc route
  {
    path: '/generate',
    name: 'Generate',
    component: GenerateComponent
  }
]

const router = createRouter({
  history: createWebHistory(process.env.BASE_URL),
  routes
})

export default router
