import axios from 'axios'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 8000,
  headers: {
    'Content-Type': 'application/json',
  },
})

function unwrap(response) {
  const body = response.data
  return body && body.status === 'success' && 'data' in body ? body.data : body
}

export const gatewayApi = {
  async getSettings() {
    return unwrap(await http.get('/api/v1/settings'))
  },

  async updateSettings(settings) {
    return unwrap(await http.put('/api/v1/settings', settings))
  },

  async setActuator({ channel, intensity }) {
    return unwrap(
      await http.put('/integration/v1/control', {
        channel,
        value: intensity,
        unit: '%',
      }),
    )
  },

  async emergencyStop() {
    return unwrap(
      await http.post('/api/v1/estop', {
        source: 'cyber_telemetry_dashboard',
        reason: 'operator_emergency_stop',
        timestamp: Date.now() / 1000,
      }),
    )
  },

  async listPlayWaves() {
    return unwrap(await http.get('/api/v1/play/waves'))
  },

  async savePlaybook(playbook) {
    return unwrap(await http.post('/api/v1/playbooks', playbook))
  },

  async listFeatures() {
    return unwrap(await http.get('/api/v1/features'))
  },

  async updateFeatures(updates) {
    return unwrap(await http.put('/api/v1/features', updates))
  },

  async scanBle(timeout = 4) {
    return unwrap(
      await http.get('/api/v1/discovery/ble/scan', { params: { timeout } }),
    )
  },

  async listDevices() {
    return unwrap(await http.get('/api/v1/discovery/registry'))
  },

  async registerDevice({ address, name, kind }) {
    return unwrap(
      await http.post(`/api/v1/discovery/registry/${encodeURIComponent(address)}`, {
        name,
        kind,
      }),
    )
  },

  async unregisterDevice(address) {
    return unwrap(
      await http.delete(`/api/v1/discovery/registry/${encodeURIComponent(address)}`),
    )
  },

  async clearDevices() {
    return unwrap(await http.delete('/api/v1/discovery/registry'))
  },

  async probeDevice(address) {
    return unwrap(
      await http.post(`/api/v1/discovery/ble/${encodeURIComponent(address)}/probe`),
    )
  },

  async listBindings() {
    return unwrap(await http.get('/api/v1/monitor/bindings'))
  },

  async getCandidates() {
    return unwrap(await http.get('/api/v1/monitor/candidates'))
  },

  async saveBindings(payload) {
    return unwrap(await http.put('/api/v1/monitor/bindings', payload))
  },

  async reloadBindings() {
    return unwrap(await http.post('/api/v1/monitor/reload'))
  },
}

export function getApiError(error, fallback = '请求失败') {
  return (
    error?.response?.data?.error?.message ||
    error?.response?.data?.message ||
    error?.message ||
    fallback
  )
}
