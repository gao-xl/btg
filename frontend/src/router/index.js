import { createRouter, createWebHistory } from 'vue-router'

import DashboardHome from '../views/DashboardHome.vue'
import PlaybookDesigner from '../views/PlaybookDesigner.vue'
import SettingsPanel from '../views/SettingsPanel.vue'
import DeviceCenter from '../views/DeviceCenter.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: DashboardHome,
      meta: { title: '实时监控' },
    },
    {
      path: '/devices',
      name: 'devices',
      component: DeviceCenter,
      meta: { title: '设备中心' },
    },
    {
      path: '/playbooks',
      name: 'playbooks',
      component: PlaybookDesigner,
      meta: { title: '剧本设计器' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: SettingsPanel,
      meta: { title: '全局配置' },
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  document.title = `${to.meta.title} // BTG Cyber Telemetry`
})

export default router
