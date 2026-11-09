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
    classification,
    classificationBasis,
    limit = 2000,
    offset = 0,
  } = options

  if (timeframe) params.set('timeframe', timeframe)

  if (importBatchId !== undefined && importBatchId !== null) {
    params.set('import_batch_id', String(importBatchId))
  }

  if (startDate) params.set('start_date', startDate)
  if (endDate) params.set('end_date', endDate)

  if (classification) {
    params.set('classification', classification)
  }

  if (classificationBasis) {
    params.set('classification_basis', classificationBasis)
  }

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
  const { sortOrder = 'asc', ...queryOptions } = options
  const params = new URLSearchParams(buildQuery(queryOptions))

  params.set('sort_order', sortOrder)

  const endpoint =
    `/market/${encodeURIComponent(instrument)}/history?${params.toString()}`

  return request(endpoint)
}

export function getTechnicalIndicators(instrument, options = {}) {
  const query = buildQuery(options)

  const endpoint =
    `/market/${encodeURIComponent(instrument)}/indicators?${query}`

  return request(endpoint)
}

export function getMarketCycles(instrument, options = {}) {
  const query = buildQuery(options)

  const endpoint =
    `/market/${encodeURIComponent(instrument)}/cycles?${query}`

  return request(endpoint)
}

export async function getAllMarketCycles(instrument, options = {}) {
  const pageSize = options.limit ?? 2000
  const records = []

  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 2000) {
    throw new Error('Market cycle page size must be between 1 and 2000.')
  }

  let offset = options.offset ?? 0
  let expectedTotal = null
  let batchId = null

  while (expectedTotal === null || offset < expectedTotal) {
    const response = await getMarketCycles(instrument, {
      ...options,
      limit: pageSize,
      offset,
    })

    const pageRecords = response.records ?? []
    const pagination = response.pagination

    if (!pagination) {
      throw new Error('Market cycle API returned missing pagination metadata.')
    }

    if (pageRecords.length !== pagination.returned_count) {
      throw new Error('Market cycle API returned an inconsistent record count.')
    }

    if (expectedTotal === null) {
      expectedTotal = pagination.total_records
      batchId = response.batch?.import_batch_id ?? null
    } else if (pagination.total_records !== expectedTotal) {
      throw new Error('Market cycle history changed during pagination.')
    }

    if (batchId !== (response.batch?.import_batch_id ?? null)) {
      throw new Error('Market cycle import batch changed during pagination.')
    }

    if (pageRecords.length === 0 && offset < expectedTotal) {
      throw new Error('Market cycle pagination ended before all records were retrieved.')
    }

    records.push(...pageRecords)
    offset += pageRecords.length
  }

  return {
    instrument_code: instrument,
    timeframe: options.timeframe,
    batch: { import_batch_id: batchId },
    records,
    pagination: {
      total_records: expectedTotal ?? 0,
      returned_count: records.length,
    },
  }
}