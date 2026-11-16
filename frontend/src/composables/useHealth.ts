import { ref } from 'vue'
import { healthApi, type HealthReport } from '@/api'
import { useSettingsCopy } from '@/lib/settingsCopy'

export function useHealth() {
  const copy = useSettingsCopy()
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
      else error.value = copy.value.healthNoResponse
    } catch {
      if (id !== seq) return
      error.value = copy.value.healthNoResponse
    } finally {
      if (id === seq) {
        loading.value = false
        probing.value = false
      }
    }
  }

  return { report, loading, probing, error, load }
}
