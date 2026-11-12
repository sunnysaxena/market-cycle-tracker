import { useCallback, useEffect, useMemo, useState } from 'react'
import PriceChart from './PriceChart'
import { getLatestChartData } from '../api/chartData'
import CustomDatePicker from './CustomDatePicker'
import TechnicalIndicatorCharts from './TechnicalIndicatorCharts'
import {
  Activity,
  BarChart3,
  CalendarDays,
  ChartNoAxesCombined,
  Layers3,
  ShieldAlert,
} from 'lucide-react'

const TIMEFRAMES = [
  { key: '1D', label: 'Daily' },
  { key: '1W', label: 'Weekly' },
  { key: '1M', label: 'Monthly' },
  { key: '1Y', label: 'Yearly' },
]

const DATE_RANGES = [
  { key: '1M', label: '1M', months: 1 },
  { key: '3M', label: '3M', months: 3 },
  { key: '6M', label: '6M', months: 6 },
  { key: '1Y', label: '1Y', months: 12 },
  { key: '3Y', label: '3Y', months: 36 },
  { key: '5Y', label: '5Y', months: 60 },
  { key: 'ALL', label: 'All' },
]

function subtractMonths(dateString, months) {
  const [year, month, day] = dateString.split('-').map(Number)

  const targetMonth = month - 1 - months
  const targetYear = year + Math.floor(targetMonth / 12)
  const normalizedMonth = ((targetMonth % 12) + 12) % 12

  const lastDay = new Date(
    targetYear,
    normalizedMonth + 1,
    0,
  ).getDate()

  const adjustedDay = Math.min(day, lastDay)

  return [
    targetYear,
    String(normalizedMonth + 1).padStart(2, '0'),
    String(adjustedDay).padStart(2, '0'),
  ].join('-')
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined) return '—'

  const number = Number(value)
  if (!Number.isFinite(number)) return '—'

  return new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(number)
}

function formatDate(value) {
  if (!value) return '—'

  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) return '—'

  return date.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

function formatLabel(value) {
  if (!value) return 'Unavailable'

  return String(value)
    .toLowerCase()
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function StatusBadge({ status }) {
  const styles = {
    available:
      'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300',
    partial:
      'bg-yellow-100 text-yellow-700 dark:bg-yellow-950 dark:text-yellow-300',
    no_data:
      'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
  }

  return (
    <span className={`rounded-full px-3 py-1 text-xs font-medium ${styles[status] || styles.no_data}`}>
      {formatLabel(status || 'no_data')}
    </span>
  )
}

function Metric({ label, value }) {
  return (
    <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/60">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 break-words text-sm font-semibold">
        {value ?? '—'}
      </p>
    </div>
  )
}

function SectionCard({ title, icon: Icon, children }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]">
      <div className="mb-4 flex items-center gap-2">
        <Icon size={18} className="text-primary" />
        <h3 className="font-semibold">{title}</h3>
      </div>
      {children}
    </div>
  )
}


function TimeframePanel({ timeframe, snapshot, expanded, onToggle }) {
  const market = snapshot?.market_data
  const indicators = snapshot?.indicators
  const structure = snapshot?.structure
  const cycle = snapshot?.cycle
  const availability = snapshot?.availability

  const movingAverages = indicators?.moving_averages
  const momentum = indicators?.momentum
  const trend = indicators?.trend
  const macd = indicators?.macd
  const volatility = indicators?.volatility

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition-colors dark:border-slate-800 dark:bg-[#111827]">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className={`flex w-full flex-wrap items-center justify-between gap-3 p-4 text-left transition-colors sm:p-5 ${
          expanded
            ? 'bg-slate-50 dark:bg-slate-900/50'
            : 'hover:bg-slate-50 dark:hover:bg-slate-900/50'
        }`}
      >
        <div className="flex min-w-0 items-center gap-3">
          <div
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-sm font-bold ${
              expanded
                ? 'bg-primary-soft text-primary dark:bg-primary-soft dark:text-primary'
                : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
            }`}
          >
            {timeframe.key}
          </div>

          <div className="min-w-0">
            <h3 className="font-semibold text-slate-900 dark:text-slate-100">
              {timeframe.label}
              <span className="ml-2 text-xs font-normal text-slate-400">
                {timeframe.key}
              </span>
            </h3>

            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {snapshot?.period
                ? `${formatDate(snapshot.period.period_start)} – ${formatDate(snapshot.period.period_end)}`
                : 'No eligible source record'}
            </p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <StatusBadge status={availability?.status} />

          <span className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-200 dark:hover:bg-slate-700">
            <svg
              className={`h-4 w-4 transition-transform duration-200 ${
                expanded ? 'rotate-180' : ''
              }`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </span>
        </div>
      </button>

      <div
        hidden={!expanded}
        className="border-t border-slate-100 dark:border-slate-800"
      >
        <div className="space-y-5 p-4 sm:p-5">
          {availability?.message && (
            <div className="rounded-lg bg-yellow-50 p-3 text-sm text-yellow-800 dark:bg-yellow-950/30 dark:text-yellow-300">
              {availability.message}
            </div>
          )}

          {!market && !indicators && !structure && !cycle ? (
            <div className="rounded-lg bg-slate-50 p-5 text-sm text-slate-500 dark:bg-slate-800/50">
              No data is available for this timeframe in the selected batch.
            </div>
          ) : (
            <>
              <SectionCard title="Market Data" icon={BarChart3}>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Metric label="Open" value={formatNumber(market?.open)} />
                  <Metric label="High" value={formatNumber(market?.high)} />
                  <Metric label="Low" value={formatNumber(market?.low)} />
                  <Metric label="Close" value={formatNumber(market?.close)} />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <Metric label="Volume" value={formatNumber(market?.volume, 0)} />
                  <Metric label="Volume status" value={formatLabel(market?.volume_status)} />
                  <Metric label="Source status" value={formatLabel(market?.source_status)} />
                </div>
              </SectionCard>

              <SectionCard title="Technical Indicators" icon={Activity}>
                <div className="mb-4">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Moving averages
                  </p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <Metric label="EMA 9" value={formatNumber(movingAverages?.ema_9)} />
                    <Metric label="EMA 20" value={formatNumber(movingAverages?.ema_20)} />
                    <Metric label="EMA 50" value={formatNumber(movingAverages?.ema_50)} />
                    <Metric label="EMA 100" value={formatNumber(movingAverages?.ema_100)} />
                    <Metric label="EMA 200" value={formatNumber(movingAverages?.ema_200)} />
                    <Metric label="SMA 222" value={formatNumber(movingAverages?.sma_222)} />
                  </div>
                </div>

                <div className="mb-4">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Momentum and trend
                  </p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <Metric label="RSI 14" value={formatNumber(momentum?.rsi_14)} />
                    <Metric label="ADX 14" value={formatNumber(trend?.adx_14)} />
                    <Metric label="+DI 14" value={formatNumber(trend?.plus_di_14)} />
                    <Metric label="-DI 14" value={formatNumber(trend?.minus_di_14)} />
                  </div>
                </div>

                <div className="mb-4">
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    MACD
                  </p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <Metric label="MACD line" value={formatNumber(macd?.line_12_26)} />
                    <Metric label="Signal 9" value={formatNumber(macd?.signal_9)} />
                    <Metric label="Histogram" value={formatNumber(macd?.histogram)} />
                  </div>
                </div>

                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Volatility
                  </p>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <Metric label="ATR 14" value={formatNumber(volatility?.atr_14)} />
                    <Metric label="CHOP 14" value={formatNumber(volatility?.chop_14)} />
                    <Metric label="Bollinger bandwidth" value={formatNumber(volatility?.bollinger_bandwidth_20_2)} />
                    <Metric label="Bollinger upper" value={formatNumber(volatility?.bollinger_upper_20_2)} />
                    <Metric label="Bollinger middle" value={formatNumber(volatility?.bollinger_middle_20_2)} />
                    <Metric label="Bollinger lower" value={formatNumber(volatility?.bollinger_lower_20_2)} />
                  </div>
                </div>

                <p className="mt-4 text-xs text-slate-400">
                  Calculation status: {formatLabel(indicators?.calculation?.status)}
                  {indicators?.calculation?.version
                    ? ` · ${indicators.calculation.version}`
                    : ''}
                </p>
              </SectionCard>

              <SectionCard title="Market Structure" icon={Layers3}>
                {structure ? (
                  <>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                      <Metric label="Structure state" value={formatLabel(structure.market_structure_state)} />
                      <Metric label="Breakout status" value={formatLabel(structure.breakout_status)} />
                      <Metric label="Range position" value={formatLabel(structure.range_position)} />
                      <Metric label="Support" value={formatNumber(structure.support?.price)} />
                      <Metric label="Resistance" value={formatNumber(structure.resistance?.price)} />
                      <Metric label="Source close" value={formatNumber(structure.source_close)} />
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-3">
                      <Metric label="Support classification" value={formatLabel(structure.support?.classification)} />
                      <Metric label="Resistance classification" value={formatLabel(structure.resistance?.classification)} />
                    </div>
                  </>
                ) : (
                  <p className="text-sm text-slate-500">Structure data unavailable.</p>
                )}
              </SectionCard>

              <SectionCard title="Market Cycle" icon={ChartNoAxesCombined}>
                {cycle ? (
                  <>
                    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                      <Metric label="Classification" value={formatLabel(cycle.cycle_classification)} />
                      <Metric label="Rule score" value={formatNumber(cycle.rule_score, 0)} />
                      <Metric label="Bandwidth percentile" value={formatNumber(cycle.bandwidth_percentile)} />
                      <Metric label="Classification basis" value={formatLabel(cycle.classification_basis)} />
                      <Metric label="Calculation version" value={cycle.calculation_version} />
                    </div>

                    {cycle.evidence?.length > 0 && (
                      <div className="mt-4">
                        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                          Evidence
                        </p>
                        <ul className="list-inside list-disc space-y-1 text-sm text-slate-600 dark:text-slate-300">
                          {cycle.evidence.map((item, index) => (
                            <li key={`${index}-${item}`}>{formatLabel(item)}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {cycle.missing_inputs?.length > 0 && (
                      <div className="mt-4 rounded-lg bg-yellow-50 p-3 dark:bg-yellow-950/30">
                        <p className="mb-2 flex items-center gap-2 text-xs font-semibold text-yellow-800 dark:text-yellow-300">
                          <ShieldAlert size={15} />
                          Missing inputs
                        </p>
                        <p className="text-sm text-yellow-800 dark:text-yellow-300">
                          {cycle.missing_inputs.map(formatLabel).join(', ')}
                        </p>
                      </div>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-slate-500">Cycle classification unavailable.</p>
                )}
              </SectionCard>
            </>
          )}

          <div className="flex flex-wrap gap-x-5 gap-y-2 border-t border-slate-100 pt-3 text-xs text-slate-400 dark:border-slate-800">
            <span>Indicators: {availability?.indicator_status || 'unavailable'}</span>
            <span>Structure: {availability?.structure_available ? 'Available' : 'Unavailable'}</span>
            <span>Cycle: {availability?.cycle_available ? 'Available' : 'Unavailable'}</span>
          </div>
        </div>
      </div>
    </section>
  )
}


export default function MultiTimeframePage({
  indices,
  selectedInstrument,
  onSelectInstrument,
  analysis,
  loading,
  error,
  isDark = true,
})
  {
    const selectedIndex = indices.find(
      (item) => item.code === selectedInstrument,
    )

    const [expandedTimeframes, setExpandedTimeframes] = useState({
      '1D': true,
      '1W': false,
      '1M': false,
      '1Y': false,
    })

    const [dateRange, setDateRange] = useState('ALL')
    const [customStartDate, setCustomStartDate] = useState('')
    const [customEndDate, setCustomEndDate] = useState('')

    const timeframes = analysis?.timeframes
    const importBatchId = analysis?.batch?.import_batch_id

    const [chartTimeframe, setChartTimeframe] = useState('1D')
    const [chartData, setChartData] = useState(null)
    const [chartLoading, setChartLoading] = useState(false)
    const [chartError, setChartError] = useState(null)
    const [chartFitKey, setChartFitKey] = useState(0)
    const [visibleLogicalRange, setVisibleLogicalRange] = useState(null)

    const handleVisibleRangeChange = useCallback((range) => {
      setVisibleLogicalRange((current) => {
        if (!range && !current) return current

        if (
          range &&
          current &&
          range.from === current.from &&
          range.to === current.to
        ) {
          return current
        }

        return range
      })
    }, [])

    const filteredCandles = useMemo(() => {
      const candles = chartData?.candles ?? []

      if (candles.length === 0) return []

      const sortedCandles = [...candles].sort(
        (a, b) => a.time.localeCompare(b.time)
      )

      const latestDate = sortedCandles[sortedCandles.length - 1].time
      const earliestDate = sortedCandles[0].time

      let startDate = earliestDate
      let endDate = latestDate

      if (dateRange === 'CUSTOM') {
        startDate = customStartDate || earliestDate
        endDate = customEndDate || latestDate
      } else if (dateRange !== 'ALL') {
        const selectedRange = DATE_RANGES.find(
          (range) => range.key === dateRange
        )

        if (selectedRange?.months) {
          startDate = subtractMonths(latestDate, selectedRange.months)
        }
      }

      if (startDate > endDate) return []

      return sortedCandles.filter(
        (candle) => candle.time >= startDate && candle.time <= endDate
      )
    }, [chartData, dateRange, customStartDate, customEndDate])

    // Reset the visible indicator range and refit the chart
    // whenever the selected date range changes.
    useEffect(() => {
      setVisibleLogicalRange(null)
      setChartFitKey((current) => current + 1)
    }, [dateRange, customStartDate, customEndDate])

    useEffect(() => {
      if (!selectedInstrument || !importBatchId) {
        setChartData(null)
        setChartError(null)
        setChartLoading(false)
        setVisibleLogicalRange(null)
        return
      }

      let cancelled = false

      async function loadChart() {
        setChartLoading(true)
        setChartError(null)
        setChartData(null)

        try {
          const result = await getLatestChartData(
            selectedInstrument,
            chartTimeframe,
            2000,
            importBatchId,
          )

          if (!cancelled) {
          setChartData(result)
          setVisibleLogicalRange(null)
          setChartFitKey((current) => current + 1)
        }
        } catch (err) {
          if (!cancelled) {
            setChartError(
              err?.message || 'Unable to load historical chart data.',
            )
          }
        } finally {
          if (!cancelled) {
            setChartLoading(false)
          }
        }
      }

      loadChart()

      return () => {
        cancelled = true
      }
      }, [selectedInstrument, chartTimeframe, importBatchId])

    return (

    <div>
      <div className="mb-6 space-y-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100">
            Multi-Timeframe Analysis
          </h2>

          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Historical price action, technical indicators and market structure
            across multiple timeframes
          </p>
        </div>


      <div className="rounded-xl border border-slate-200 bg-slate-50 p-2 dark:border-slate-800 dark:bg-slate-900/50">
        <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
          Select Market Index
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
          {indices.map((item) => {
            const active = selectedInstrument === item.code

            return (
              <button
                key={item.code}
                type="button"
                onClick={() => onSelectInstrument(item.code)}
                aria-pressed={active}
                title={item.name || item.code}
                className={`relative flex min-h-[64px] flex-col items-start justify-center rounded-lg border px-3 py-2.5 text-left transition-all ${
                  active
                    ? 'border-primary bg-primary-soft shadow-sm dark:border-primary dark:bg-primary-soft'
                    : 'border-transparent bg-white hover:border-primary hover:bg-primary-soft dark:bg-slate-800/70 dark:hover:border-primary dark:hover:bg-primary-soft'
                }`}
              >
                <span
                  className={`text-sm font-bold tracking-wide ${
                    active
                      ? 'text-primary dark:text-primary'
                      : 'text-slate-800 dark:text-slate-200'
                  }`}
                >
                  {item.code}
                </span>

                <span className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                  {item.name || item.code}
                </span>

                {active && (
                  <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-primary" />
                )}
              </button>
            )
          })}
        </div>
      </div>

      </div>
      {error && (
        <div className="mb-5 rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          <strong>Unable to load analysis:</strong> {error}
        </div>
      )}

      {loading && (
        <div className="mb-5 rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500 dark:border-slate-800 dark:bg-[#111827]">
          Loading multi-timeframe analysis...
        </div>
      )}

      {!loading && !error && !analysis && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500 dark:border-slate-800 dark:bg-[#111827]">
          Select a market index to view its analysis.
        </div>
      )}

      {analysis && !error && (
        <>
          <div className="mb-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Instrument" value={selectedIndex?.name || selectedInstrument} />
            <Metric label="Instrument code" value={analysis.instrument_code} />
            <Metric label="Import batch" value={analysis.batch?.import_batch_id ?? '—'} />
            <Metric label="Timeframes returned" value={Object.keys(timeframes || {}).length} />
          </div>

            {/* Historical Candlestick Chart */}
          <section className="mb-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-[#111827]">

            <div className="mb-4 flex flex-col gap-4">
              {/* Chart Heading */}
              <div>
                <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                  Historical Price Chart
                </h3>
                <p className="mt-1 text-xs text-slate-500">
                  {selectedIndex?.name || selectedInstrument}
                  {' · '}
                  Batch {importBatchId}
                </p>
              </div>

              {/* Unified Chart Controls */}
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/60">

                {/* Timeframe Selector */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="mr-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
                    Timeframe
                  </span>

                  {[
                    { key: '1D', label: 'Daily' },
                    { key: '1W', label: 'Weekly' },
                    { key: '1M', label: 'Monthly' },
                    { key: '1Y', label: 'Yearly' },
                  ].map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setChartTimeframe(item.key)}
                      aria-pressed={chartTimeframe === item.key}
                      className={`inline-flex h-9 min-w-[76px] items-center justify-center rounded-md border px-3 text-xs font-medium transition-colors ${
                        chartTimeframe === item.key
                          ? 'border-primary bg-primary text-white dark:text-slate-950'
                          : 'border-slate-300 bg-white text-slate-700 hover:border-primary hover:bg-primary-soft hover:text-primary dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:border-primary dark:hover:bg-primary-soft dark:hover:text-primary'
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>

                {/* Divider */}
                <div className="my-3 border-t border-slate-200 dark:border-slate-700" />

                {/* Date Range and Custom Dates */}
                <div className="flex flex-wrap items-end justify-between gap-4">

                  {/* Quick Date Ranges */}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="mr-1 text-xs font-semibold text-slate-500 dark:text-slate-400">
                      Date Range
                    </span>

                    {DATE_RANGES.map((item) => (
                      <button
                        key={item.key}
                        type="button"
                        onClick={() => setDateRange(item.key)}
                        aria-pressed={dateRange === item.key}
                        className={`inline-flex h-9 min-w-[48px] items-center justify-center rounded-md border px-3 text-xs font-medium transition-colors ${
                          dateRange === item.key
                            ? 'border-primary bg-primary text-white dark:text-slate-950'
                            : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                        }`}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>

                  {/* Custom Date Inputs and Reset */}
                  <div className="flex flex-wrap items-end gap-3">
                      <CustomDatePicker
                        id="chart-start-date"
                        label="From"
                        value={customStartDate}
                        onChange={(date) => {
                          setCustomStartDate(date)
                          setDateRange('CUSTOM')
                        }}
                      />

                      <CustomDatePicker
                        id="chart-end-date"
                        label="To"
                        value={customEndDate}
                        onChange={(date) => {
                          setCustomEndDate(date)
                          setDateRange('CUSTOM')
                        }}
                      />

                      <button
                        type="button"
                        onClick={() => {
                          setCustomStartDate('')
                          setCustomEndDate('')
                          setDateRange('ALL')
                        }}
                        className="inline-flex h-9 min-w-[76px] items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-xs font-medium text-slate-700 transition-colors hover:border-primary hover:bg-primary-soft dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:border-primary dark:hover:bg-primary-soft"
                                                                                                                                                                                                                                                                                                                                                         >
                        Reset
                      </button>
                    </div>


                </div>
              </div>
            </div>


            <PriceChart
              data={filteredCandles}
              loading={chartLoading}
              error={chartError}
              timeframe={chartTimeframe}
              isDark={isDark}
              fitContentKey={chartFitKey}
              onVisibleRangeChange={handleVisibleRangeChange}
            />
          </section>

          {/* Technical Indicator Charts */}
          <TechnicalIndicatorCharts
              data={filteredCandles}
              loading={chartLoading}
              visibleLogicalRange={visibleLogicalRange}
          />

          <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {TIMEFRAMES.map((timeframe) => {
              const snapshot = timeframes?.[timeframe.key]

              return (
                <div
                  key={timeframe.key}
                  className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-[#111827]"
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-semibold">{timeframe.label}</p>
                    <StatusBadge status={snapshot?.availability?.status} />
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    {snapshot?.period
                      ? `As of ${formatDate(snapshot.period.period_end)}`
                      : 'No eligible record'}
                  </p>
                </div>
              )
            })}
          </div>

          <div className="mb-5 flex items-center gap-2">
            <CalendarDays size={17} className="text-slate-400" />
            <p className="text-xs text-slate-500">
              Each timeframe uses its latest eligible source record. Period end dates may differ.
            </p>
          </div>

          <div className="space-y-6">

            {TIMEFRAMES.map((timeframe) => {
              const snapshot = timeframes?.[timeframe.key]

              return (
                <TimeframePanel
                  key={timeframe.key}
                  timeframe={timeframe}
                  snapshot={snapshot}
                  expanded={!!expandedTimeframes[timeframe.key]}
                  onToggle={() =>
                    setExpandedTimeframes((current) => ({
                      ...current,
                      [timeframe.key]: !current[timeframe.key],
                    }))
                  }
                />
              )
            })}

          </div>
        </>
      )}
    </div>
  )
}


