import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('@/views/NovelList.vue') },
    { path: '/create', name: 'create', component: () => import('@/components/BlankNovelForm.vue') },
    { path: '/import', name: 'import', component: () => import('@/views/ImportWizard.vue') },
    {
      path: '/settings/providers',
      name: 'provider-settings',
      component: () => import('@/views/ProviderSettings.vue'),
    },
    {
      path: '/settings/health',
      name: 'health',
      component: () => import('@/views/HealthSettings.vue'),
    },
    {
      path: '/settings/appearance',
      name: 'appearance',
      component: () => import('@/views/AppearanceSettings.vue'),
    },
    {
      path: '/settings/skills',
      name: 'writing-skills',
      component: () => import('@/views/WritingSkills.vue'),
    },
    {
      path: '/novels/:id/ingest/:taskId',
      name: 'ingest',
      component: () => import('@/views/IngestProgress.vue'),
    },
    {
      path: '/novels/:id',
      name: 'novel',
      component: () => import('@/views/NovelWorkspace.vue'),
      children: [
        { path: '', redirect: { name: 'bible' } },
        { path: 'bible', name: 'bible', component: () => import('@/views/StoryBible.vue') },
        { path: 'outline', name: 'outline', component: () => import('@/views/OutlineWorkbench.vue') },
        { path: 'write', name: 'write', component: () => import('@/views/WriteWorkbench.vue') },
        { path: 'costs', name: 'costs', component: () => import('@/views/CostBoard.vue') },
        { path: 'tasks', name: 'tasks', component: () => import('@/views/TaskHistory.vue') },
      ],
    },
  ],
})

export default router
