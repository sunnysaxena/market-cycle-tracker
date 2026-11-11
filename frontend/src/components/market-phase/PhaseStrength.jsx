
import { useState } from 'react'
import { Info, Activity } from 'lucide-react'
import InfoPopup from './InfoPopup'

const timeframes = [
  { id: '1D', label: 'Daily' },
  { id: '1W', label: 'Weekly' },
  { id: '1M', label: 'Monthly' },
  { id: '1Y', label: 'Yearly' },
]

function formatValue(value, suffix = '') {
  if (value === null || value === undefined || value === '') {
    return 'Unavailable'
  }

  if (typeof value === 'number') {
    return `${value.toFixed(2)}${suffix}`
  }

  return `${value}${suffix}`
}

function PhaseStrength({ indices = [], analysis = {}, loading, error }) {
  const [selectedIndex, setSelectedIndex] = useState('')
  const [selectedTimeframe, setSelectedTimeframe] = useState('1D')
  const [showInfo, setShowInfo] = useState(false)

  const activeIndex = indices.find(
    (index) => index.code === selectedIndex
  ) ?? indices[0]

  const activeCode = activeIndex?.code

  const snapshot = activeCode
    ? analysis[activeCode]?.timeframes?.[selectedTimeframe]
    : null

  const cycle = snapshot?.cycle
  const classification = cycle?.cycle_classification

    // Stored technical indicator values for the selected timeframe
  const indicators = snapshot?.indicators

  const movingAverages = indicators?.moving_averages
  const momentum = indicators?.momentum
  const trend = indicators?.trend
  const macd = indicators?.macd
  const volatility = indicators?.volatility
  const calculation = indicators?.calculation
    // Market structure and configured classification thresholds
  const structure = snapshot?.structure
  const cycleConfig = cycle?.config_json ?? {}

  function toNumber(value) {
    if (value === null || value === undefined || value === '') {
      return null
    }

    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }

  function getThreshold(key, fallback) {
    return toNumber(cycleConfig[key]) ?? fallback
  }

  // Read actual backend thresholds, with verified engine defaults
  const chopSideways = getThreshold('chop_sideways', 61.8)
  const chopTrending = getThreshold('chop_trending', 38.2)
  const adxWeak = getThreshold('adx_weak', 20)
  const adxStrong = getThreshold('adx_strong', 25)
  const bbwLow = getThreshold('bbw_low_percentile', 25)
  const bbwHigh = getThreshold('bbw_high_percentile', 75)

  // Current indicator readings
  const chopValue = toNumber(volatility?.chop_14)
  const adxValue = toNumber(trend?.adx_14)
  const bandwidthPercentile = toNumber(cycle?.bandwidth_percentile)

  // CHOP interpretation
  const chopInterpretation =
    chopValue === null
      ? 'Unavailable'
      : chopValue >= chopSideways
        ? 'High Choppiness'
        : chopValue <= chopTrending
          ? 'Low Choppiness'
          : 'Intermediate Choppiness'

  // ADX interpretation
  const adxInterpretation =
    adxValue === null
      ? 'Unavailable'
      : adxValue < adxWeak
        ? 'Weak Trend Strength'
        : adxValue < adxStrong
          ? 'Moderate Trend Strength'
          : 'Strong Trend Strength'

  // Bollinger Bandwidth percentile interpretation
  const bandwidthInterpretation =
    bandwidthPercentile === null
      ? 'Unavailable'
      : bandwidthPercentile <= bbwLow
        ? 'Compressed Volatility'
        : bandwidthPercentile >= bbwHigh
          ? 'Expanded Volatility'
          : 'Normal Volatility'

  // Sideways evidence conditions used by the existing engine
  const sidewaysConditions = [
    {
      label: 'High choppiness',
      met: chopValue === null ? null : chopValue >= chopSideways,
    },
    {
      label: 'Weak trend strength',
      met: adxValue === null ? null : adxValue < adxWeak,
    },
    {
      label: 'Compressed bandwidth',
      met: bandwidthPercentile === null
        ? null
        : bandwidthPercentile <= bbwLow,
    },
  ]

  const sidewaysEvidenceCount = sidewaysConditions.filter(
    (condition) => condition.met === true
  ).length

  const sidewaysInputsAvailable = sidewaysConditions.every(
    (condition) => condition.met !== null
  )

  const sidewaysIndicatorResult = !sidewaysInputsAvailable
    ? 'Insufficient indicator data'
    : sidewaysEvidenceCount >= 2
      ? 'At least 2 of 3 indicator conditions met'
      : 'Fewer than 2 of 3 indicator conditions met'

  const structureState = structure?.market_structure_state
  const breakoutStatus = structure?.breakout_status
  const rangePosition = structure?.range_position

  const indicatorStatus = calculation?.status ?? 'unavailable'

  const emaValues = [
    { label: 'EMA 9', value: movingAverages?.ema_9 },
    { label: 'EMA 20', value: movingAverages?.ema_20 },
    { label: 'EMA 50', value: movingAverages?.ema_50 },
    { label: 'EMA 100', value: movingAverages?.ema_100 },
    { label: 'EMA 200', value: movingAverages?.ema_200 },
    { label: 'SMA 222', value: movingAverages?.sma_222 },
  ]

  const evidence = cycle?.evidence
  const missingInputs = cycle?.missing_inputs

  function formatItems(items) {
    if (!items) return []

    if (Array.isArray(items)) return items

    if (typeof items === 'object') {
      return Object.entries(items).map(([key, value]) => ({
        key,
        value,
      }))
    }

    return [items]
  }

  function displayItem(item) {
    if (typeof item === 'string') return item

    if (item && typeof item === 'object') {
      return Object.entries(item)
        .map(([key, value]) => `${key}: ${
          typeof value === 'object'
            ? JSON.stringify(value)
            : String(value)
        }`)
        .join(' | ')
    }

    return String(item)
  }

  const evidenceItems = formatItems(evidence)
  const missingItems = formatItems(missingInputs)

  return (
    <div className="space-y-6">

      {loading && (
        <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-[#111827] dark:text-slate-400">
          Loading market strength data...
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      )}

      {!loading && !error && (
        <>
          {/* Selection controls */}
          <div className="flex flex-wrap items-end gap-4 rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]">

            <div className="min-w-48 flex-1">
              <label className="mb-2 block text-xs font-medium text-slate-500 dark:text-slate-400">
                Select Index
              </label>

              <select
                value={activeCode ?? ''}
                onChange={(event) => setSelectedIndex(event.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-blue-500 dark:border-slate-700 dark:bg-[#0b1220] dark:text-slate-100"
              >
                {indices.map((index) => (
                  <option key={index.code} value={index.code}>
                    {index.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="min-w-48 flex-1">
              <label className="mb-2 block text-xs font-medium text-slate-500 dark:text-slate-400">
                Select Timeframe
              </label>

              <select
                value={selectedTimeframe}
                onChange={(event) => setSelectedTimeframe(event.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-blue-500 dark:border-slate-700 dark:bg-[#0b1220] dark:text-slate-100"
              >
                {timeframes.map((timeframe) => (
                  <option key={timeframe.id} value={timeframe.id}>
                    {timeframe.label}
                  </option>
                ))}
              </select>
            </div>

          </div>

          {/* Phase classification */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]">

            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <Activity size={19} className="text-blue-500" />
                  <h4 className="font-semibold text-slate-900 dark:text-slate-100">
                    Phase Strength & Classification
                  </h4>
                </div>

                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  {activeIndex?.name ?? activeCode ?? 'No index'} · {selectedTimeframe}
                </p>
              </div>

              <button
                type="button"
                onClick={() => setShowInfo(true)}
                aria-label="Phase classification information"
                className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <Info size={18} />
              </button>
            </div>

            {!snapshot || !cycle ? (
              <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                Phase classification data is unavailable for this index and timeframe.
              </p>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">

                <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-900">
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Current Market Phase
                  </p>
                  <p className="mt-2 text-lg font-bold text-slate-900 dark:text-slate-100">
                    {classification ?? 'Unavailable'}
                  </p>
                </div>

                <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-900">
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Classification Rule Score
                  </p>
                  <p className="mt-2 text-lg font-bold text-slate-900 dark:text-slate-100">
                    {formatValue(cycle.rule_score)}
                  </p>
                </div>

                <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-900">
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Bandwidth Percentile
                  </p>
                  <p className="mt-2 text-lg font-bold text-slate-900 dark:text-slate-100">
                    {formatValue(cycle.bandwidth_percentile, '%')}
                  </p>
                </div>

              </div>
            )}

            {cycle?.classification_basis && (
              <div className="mt-5">
                <p className="mb-2 text-xs font-medium text-slate-500 dark:text-slate-400">
                  Classification Basis
                </p>
                <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700 dark:bg-slate-900 dark:text-slate-300">
                  {typeof cycle.classification_basis === 'object'
                    ? JSON.stringify(cycle.classification_basis, null, 2)
                    : cycle.classification_basis}
                </p>
              </div>
            )}

            {evidenceItems.length > 0 && (
              <div className="mt-5">
                <p className="mb-2 text-xs font-medium text-slate-500 dark:text-slate-400">
                  Supporting Evidence
                </p>
                <ul className="space-y-2">
                  {evidenceItems.map((item, index) => (
                    <li
                      key={index}
                      className="rounded-lg border border-slate-200 p-3 text-sm text-slate-700 dark:border-slate-800 dark:text-slate-300"
                    >
                      {displayItem(item)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {missingItems.length > 0 && (
              <div className="mt-5">
                <p className="mb-2 text-xs font-medium text-amber-600 dark:text-amber-400">
                  Missing Classification Inputs
                </p>
                <ul className="space-y-2">
                  {missingItems.map((item, index) => (
                    <li
                      key={index}
                      className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950/30 dark:text-amber-300"
                    >
                      {displayItem(item)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

          </div>


          {/* Trend & Momentum */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]">

            <div className="mb-5">
              <h4 className="font-semibold text-slate-900 dark:text-slate-100">
                Trend & Momentum Analysis
              </h4>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Stored technical indicators for the selected index and timeframe
              </p>
            </div>

            {!indicators ? (
              <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                Technical indicator data is unavailable for this selection.
              </p>
            ) : (
              <div className="space-y-6">

                <div>
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h5 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                      Moving Averages
                    </h5>
                    <span className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {indicatorStatus.replace('_', ' ').toUpperCase()}
                    </span>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {emaValues.map((item) => (
                      <div
                        key={item.label}
                        className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900"
                      >
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {item.label}
                        </p>
                        <p className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                          {formatValue(item.value)}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">

                  <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                    <h5 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-200">
                      Momentum — RSI 14
                    </h5>
                    <p className="text-2xl font-bold text-slate-900 dark:text-slate-100">
                      {formatValue(momentum?.rsi_14)}
                    </p>
                    <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                      RSI value on a 0–100 scale. Values are displayed without imposing a trading signal.
                    </p>
                  </div>

                  <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                    <h5 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-200">
                      Trend Strength — ADX 14
                    </h5>

                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { label: 'ADX', value: trend?.adx_14 },
                        { label: '+DI', value: trend?.plus_di_14 },
                        { label: '−DI', value: trend?.minus_di_14 },
                      ].map((item) => (
                        <div key={item.label}>
                          <p className="text-xs text-slate-500 dark:text-slate-400">
                            {item.label}
                          </p>
                          <p className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                            {formatValue(item.value)}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>

                </div>

                <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                  <h5 className="mb-3 text-sm font-semibold text-slate-800 dark:text-slate-200">
                    MACD — 12, 26, 9
                  </h5>

                  <div className="grid gap-3 sm:grid-cols-3">
                    {[
                      { label: 'MACD Line', value: macd?.line_12_26 },
                      { label: 'Signal Line', value: macd?.signal_9 },
                      { label: 'Histogram', value: macd?.histogram },
                    ].map((item) => (
                      <div
                        key={item.label}
                        className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900"
                      >
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {item.label}
                        </p>
                        <p className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                          {formatValue(item.value)}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                {calculation?.version && (
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Indicator calculation version: {calculation.version}
                  </p>
                )}

              </div>
            )}
          </div>


        {/* Sideways-Market Intelligence */}
          <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]">

            <div className="mb-5">
              <h4 className="font-semibold text-slate-900 dark:text-slate-100">
                Sideways-Market Intelligence
              </h4>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Volatility and market-choppiness measurements for the selected timeframe
              </p>
            </div>

            {!volatility ? (
              <p className="rounded-lg bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                Volatility indicator data is unavailable for this selection.
              </p>
            ) : (
              <div className="space-y-5">

                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">

                  {[
                    { label: 'CHOP 14', value: volatility.chop_14 },
                    { label: 'ATR 14', value: volatility.atr_14 },
                    {
                      label: 'Bollinger Bandwidth 20,2',
                      value: volatility.bollinger_bandwidth_20_2,
                    },
                  ].map((item) => (
                    <div
                      key={item.label}
                      className="rounded-lg bg-slate-50 p-4 dark:bg-slate-900"
                    >
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {item.label}
                      </p>
                      <p className="mt-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
                        {formatValue(item.value)}
                      </p>
                    </div>
                  ))}

                </div>

                <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">
                  <h5 className="mb-4 text-sm font-semibold text-slate-800 dark:text-slate-200">
                    Bollinger Bands — 20,2
                  </h5>

                  <div className="grid gap-3 sm:grid-cols-3">

                    {[
                      {
                        label: 'Upper Band',
                        value: volatility.bollinger_upper_20_2,
                      },
                      {
                        label: 'Middle Band',
                        value: volatility.bollinger_middle_20_2,
                      },
                      {
                        label: 'Lower Band',
                        value: volatility.bollinger_lower_20_2,
                      },
                    ].map((item) => (
                      <div
                        key={item.label}
                        className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900"
                      >
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          {item.label}
                        </p>
                        <p className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                          {formatValue(item.value)}
                        </p>
                      </div>
                    ))}

                  </div>
                </div>

              </div>
            )}

                        {/* Market condition interpretations */}
            <div className="mt-6 space-y-4">

              <div>
                <h5 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                  Market Condition Interpretations
                </h5>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Descriptive readings based on the configured engine thresholds
                </p>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">

                {[
                  {
                    label: 'Choppiness',
                    value: chopInterpretation,
                    reading: chopValue,
                    unit: '',
                  },
                  {
                    label: 'Trend Strength',
                    value: adxInterpretation,
                    reading: adxValue,
                    unit: '',
                  },
                  {
                    label: 'Volatility Context',
                    value: bandwidthInterpretation,
                    reading: bandwidthPercentile,
                    unit: '% percentile',
                  },
                ].map((item) => (
                  <div
                    key={item.label}
                    className="rounded-lg border border-slate-200 p-4 dark:border-slate-800"
                  >
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {item.label}
                    </p>

                    <p className="mt-2 font-semibold text-slate-900 dark:text-slate-100">
                      {item.value}
                    </p>

                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      Reading: {formatValue(item.reading, item.unit)}
                    </p>
                  </div>
                ))}

              </div>

              {/* Sideways evidence */}
              <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">

                <h5 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                  Sideways Indicator Evidence
                </h5>

                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  The engine requires at least two of these three indicator conditions.
                </p>

                <div className="mt-4 space-y-3">

                  {sidewaysConditions.map((condition) => (
                    <div
                      key={condition.label}
                      className="flex items-center justify-between gap-3 text-sm"
                    >
                      <span className="text-slate-700 dark:text-slate-300">
                        {condition.label}
                      </span>

                      <span className={
                        condition.met === true
                          ? 'font-medium text-emerald-600 dark:text-emerald-400'
                          : condition.met === false
                            ? 'font-medium text-slate-500 dark:text-slate-400'
                            : 'font-medium text-amber-600 dark:text-amber-400'
                      }>
                        {condition.met === true
                          ? 'Met'
                          : condition.met === false
                            ? 'Not met'
                            : 'Unavailable'}
                      </span>
                    </div>
                  ))}

                </div>

                <p className="mt-4 border-t border-slate-200 pt-3 text-sm font-medium text-slate-800 dark:border-slate-800 dark:text-slate-200">
                  {sidewaysIndicatorResult}
                </p>

              </div>

              {/* Market structure context */}
              <div className="rounded-lg border border-slate-200 p-4 dark:border-slate-800">

                <h5 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                  Market Structure Context
                </h5>

                <div className="mt-4 grid gap-4 sm:grid-cols-3">

                  {[
                    {
                      label: 'Structure State',
                      value: structureState,
                    },
                    {
                      label: 'Breakout Status',
                      value: breakoutStatus,
                    },
                    {
                      label: 'Range Position',
                      value: rangePosition,
                    },
                  ].map((item) => (
                    <div key={item.label}>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        {item.label}
                      </p>
                      <p className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-100">
                        {item.value ?? 'Unavailable'}
                      </p>
                    </div>
                  ))}

                </div>

                <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
                  The official sideways classification also requires
                  MIXED_TRANSITION market structure and NONE breakout status.
                  These requirements are evaluated separately from the
                  three indicator conditions above.
                </p>

              </div>

            </div>

          </div>


          <InfoPopup
            open={showInfo}
            onClose={() => setShowInfo(false)}
            title="Understanding Phase Strength"
          >
            <p>
              The classification rule score represents the score produced by
              the existing Market Cycle Classification Engine. It is not a
              separate composite strength indicator.
            </p>
            <p>
              Bandwidth percentile provides volatility-context information.
              Supporting evidence and missing inputs explain the basis and
              limitations of the current classification.
            </p>
          </InfoPopup>
        </>
      )}

    </div>
  )
}

export default PhaseStrength
