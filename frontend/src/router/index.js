import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/',               name: 'dashboard',    component: () => import('../views/DashboardView.vue'),    meta: { title: 'Dashboard' } },
  { path: '/search',         name: 'search',       component: () => import('../views/SearchView.vue'),       meta: { title: 'Marker Search' } },
  { path: '/marker/:symbol', name: 'markerDetail', component: () => import('../views/MarkerDetailView.vue'), meta: { title: 'Marker Detail' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  document.title = `${to.meta.title || 'Page'} — scMarkerMiner`
})

export default router
