import {
  getMarketHistory,
  getTechnicalIndicators,
} from './client'

const MAX_CHART_RECORDS = 2000

function getTotalRecords(response) {
  const total = response?.pagination?.total_records

  if (Number.isFinite(Number(total))) {
    return Number(total)
  }

  return response?.records?.length ?? 0
}

async function getLatestPage(fetcher, instrument, options, limit) {
  // First request: discover the total number of matching records.
  const metadata = await fetcher(instrument, {
    ...options,
    limit: 1,
    offset: 0,
  })

  const totalRecords = getTotalRecords(metadata)
  const recordLimit = Math.min(limit, totalRecords)

  if (recordLimit === 0) {
    return metadata
  }

  // The API sorts records oldest-first, so move the offset
  // forward to retrieve the most recent records.
  const offset = Math.max(0, totalRecords - recordLimit)

  return fetcher(instrument, {
    ...options,
    limit: recordLimit,
    offset,
  })
}

function toNumber(value) {
  if (value === null || value === undefined || value === '') {
    return null
  }

  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function getCandleDate(record, timeframe) {
  return timeframe === '1D'
    ? record.candle_date
    : record.period_start
}

function buildChartCandles(historyRecords, indicatorRecords, timeframe) {
  const indicatorsByDate = new Map()

  for (const record of indicatorRecords) {
    if (record.period_start) {
      indicatorsByDate.set(record.period_start, record)
    }
  }

  return historyRecords
    .map((record) => {
      const date = getCandleDate(record, timeframe)

      if (!date) return null

      const open = toNumber(record.open)
      const high = toNumber(record.high)
      const low = toNumber(record.low)
      const close = toNumber(record.close)

      if (
        open === null ||
        high === null ||
        low === null ||
        close === null
      ) {
        return null
      }

      const indicator = indicatorsByDate.get(date)
      const movingAverages = indicator?.moving_averages ?? {}

      return {
        time: date,
        open,
        high,
        low,
        close,

        volume: toNumber(record.volume),
        volumeStatus: record.volume_status ?? 'unavailable',

        ema9: toNumber(movingAverages.ema_9),
        ema20: toNumber(movingAverages.ema_20),
        ema50: toNumber(movingAverages.ema_50),
        ema100: toNumber(movingAverages.ema_100),
        ema200: toNumber(movingAverages.ema_200),
        sma222: toNumber(movingAverages.sma_222),

        rsi14: toNumber(indicator?.momentum?.rsi_14),
        adx14: toNumber(indicator?.trend?.adx_14),
        plusDi14: toNumber(indicator?.trend?.plus_di_14),
        minusDi14: toNumber(indicator?.trend?.minus_di_14),

        macd: toNumber(indicator?.macd?.line_12_26),
        macdSignal: toNumber(indicator?.macd?.signal_9),
        macdHistogram: toNumber(indicator?.macd?.histogram),

        atr14: toNumber(indicator?.volatility?.atr_14),
        chop14: toNumber(indicator?.volatility?.chop_14),
        bollingerBandwidth: toNumber(
          indicator?.volatility?.bollinger_bandwidth_20_2,
        ),
      }
    })
    .filter(Boolean)
}

export async function getLatestChartData(
  instrument,
  timeframe,
  limit = MAX_CHART_RECORDS,
  importBatchId,
) {
  const safeLimit = Math.min(
    Math.max(1, Number(limit) || MAX_CHART_RECORDS),
    MAX_CHART_RECORDS,
  )

  // Resolve the current batch from the historical market-data API.
  // Resolve or confirm the selected import batch.
  const historyMetadata = await getMarketHistory(instrument, {
    timeframe,
    importBatchId,
    limit: 1,
    offset: 0,
  })

  const resolvedImportBatchId =
    importBatchId ?? historyMetadata?.batch?.import_batch_id

  if (!resolvedImportBatchId) {
    throw new Error('The market history API did not return a batch ID.')
  }

  const historyTotal = getTotalRecords(historyMetadata)
  const historyLimit = Math.min(safeLimit, historyTotal)
  const historyOffset = Math.max(0, historyTotal - historyLimit)

  // Fetch the latest history page and indicator metadata for the
  // same batch. Each endpoint has its own record count and offset.
  const [historyResponse, indicatorMetadata] = await Promise.all([
    historyLimit > 0
      ? getMarketHistory(instrument, {
        timeframe,
        importBatchId: resolvedImportBatchId,
        limit: historyLimit,
        offset: historyOffset,
        })
      : Promise.resolve(historyMetadata),

    getTechnicalIndicators(instrument, {
    timeframe,
    importBatchId: resolvedImportBatchId,
    limit: 1,
    offset: 0,
    })
  ])

  const indicatorTotal = getTotalRecords(indicatorMetadata)
  const indicatorLimit = Math.min(safeLimit, indicatorTotal)
  const indicatorOffset = Math.max(0, indicatorTotal - indicatorLimit)

  const indicatorResponse =
    indicatorLimit > 0
      ? await getTechnicalIndicators(instrument, {
            timeframe,
            importBatchId: resolvedImportBatchId,
            limit: indicatorLimit,
            offset: indicatorOffset,
            })
      : indicatorMetadata

  const historyRecords = historyResponse?.records ?? []
  const indicatorRecords = indicatorResponse?.records ?? []

  return {
    instrumentCode: instrument,
    timeframe,
    batch: historyResponse?.batch ?? historyMetadata.batch,

    candles: buildChartCandles(
      historyRecords,
      indicatorRecords,
      timeframe,
    ),

    history: {
      totalRecords: historyTotal,
      returnedRecords: historyRecords.length,
      availability: historyResponse?.availability,
    },

    indicators: {
      totalRecords: indicatorTotal,
      returnedRecords: indicatorRecords.length,
      availability: indicatorResponse?.availability,
    },
  }
}