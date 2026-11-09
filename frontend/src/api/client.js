const API_BASE_URL = '/api/v1'

async function request(endpoint) {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    method: 'GET',
    headers: {
      Accept: 'application/json',
    },
  })

  const data = await response.json().catch(() => null)

  if (!response.ok) {
    const message =
      data?.error?.message ||
      data?.detail ||
      `API request failed (${response.status})`

    throw new Error(message)
  }

  return data
}

function buildQuery(options = {}) {
  const params = new URLSearchParams()

  const {
    timeframe,
    importBatchId,
    startDate,
    endDate,
    limit = 2000,
    offset = 0,
  } = options

  if (timeframe) params.set('timeframe', timeframe)

  if (importBatchId !== undefined && importBatchId !== null) {
    params.set('import_batch_id', String(importBatchId))
  }

  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)

  params.set('limit', String(limit))
  params.set('offset', String(offset))

  return params.toString()
}

export function getIndices() {
  return request('/indices?active_only=true')
}

export function getMultiTimeframeAnalysis(instrument, importBatchId) {
  const params = new URLSearchParams()

  if (importBatchId !== undefined && importBatchId !== null) {
    params.set('import_batch_id', String(importBatchId))
  }

  const query = params.toString()
  const endpoint = `/market/${encodeURIComponent(instrument)}/multi-timeframe`

  return request(query ? `${endpoint}?${query}` : endpoint)
}

export function getMarketHistory(instrument, options = {}) {
  const query = buildQuery(options)

  const endpoint =
    `/market/${encodeURIComponent(instrument)}/history?${query}`

  return request(endpoint)
}

export function getTechnicalIndicators(instrument, options = {}) {
  const query = buildQuery(options)

  const endpoint =
    `/market/${encodeURIComponent(instrument)}/indicators?${query}`

  return request(endpoint)
}
