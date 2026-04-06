import axios from 'axios'

function toQueryString(params) {
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === '') continue
    if (Array.isArray(value)) {
      value.forEach(v => sp.append(key, v))
    } else {
      sp.append(key, String(value))
    }
  }
  return sp.toString()
}

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  paramsSerializer: (params) => toQueryString(params),
})

export const getOverview       = ()           => api.get('/stats/overview')
export const getFilters        = (params)     => api.get('/stats/filters', { params })
export const searchMarkers     = (params)     => api.get('/markers/search', { params })
export const getMarkerDetail   = (symbol)     => api.get(`/markers/${symbol}`)
export const getBubbleData     = (params)     => api.get('/stats/bubble', { params })
export const getDistribution   = ()           => api.get('/stats/distribution')

export const exportCSV  = (params) => `/api/export/csv?${toQueryString(params)}`
export const exportXLSX = (params) => `/api/export/xlsx?${toQueryString(params)}`
