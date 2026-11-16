import { ref } from 'vue'
import { healthApi, type HealthReport } from '@/api'

export function useHealth() {
  const report = ref<HealthReport | null>(null)
  const loading = ref(false)
  const probing = ref(false)
  const error = ref('')
  let seq = 0

  async function load(probe = false) {
    const id = ++seq
    if (probe) probing.value = true
    else if (!report.value) loading.value = true
    error.value = ''
    try {
      const { data } = await healthApi.get(probe)
      if (id !== seq) return
      if (data?.checks) report.value = data
      else error.value = '接口没有响应'
    } catch {
      if (id !== seq) return
      error.value = '接口没有响应'
    } finally {
      if (id === seq) {
        loading.value = false
        probing.value = false
      }
    }
  }

  return { report, loading, probing, error, load }
}
