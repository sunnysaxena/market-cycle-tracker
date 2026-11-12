
import { useEffect, useMemo, useState } from 'react'
import { FlaskConical, Info, RefreshCw } from 'lucide-react'
import CustomDatePicker from '../CustomDatePicker'
import InfoPopup from './InfoPopup'
import { getForwardReturnsByPhase } from '../../api/client'

const TIMEFRAMES = [
  { value: '1D', label: 'Daily' },
  { value: '1W', label: 'Weekly' },
  { value: '1M', label: 'Monthly' },
  { value: '1Y', label: 'Yearly' },
]

const HORIZONS = [1, 5, 10, 20]

const PHASE_STYLES = {
  ACCUMULATION: 'border-l-emerald-500 text-emerald-400',
  MARKUP: 'border-l-green-500 text-green-400',
  DISTRIBUTION: 'border-l-amber-500 text-amber-400',
  MARKDOWN: 'border-l-red-500 text-red-400',
  SIDEWAYS_CONSOLIDATION: 'border-l-sky-500 text-sky-400',
  TRANSITION_UNCERTAIN: 'border-l-violet-500 text-violet-400',
  INSUFFICIENT_DATA: 'border-l-slate-500 text-slate-400',
}

function formatPercent(value) {
  if (value === null || value === undefined) return '—'

  const number = Number(value)
  if (!Number.isFinite(number)) return '—'

  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

function formatCount(value) {
  return Number(value ?? 0).toLocaleString('en-IN')
}

function getReturnColor(value) {
  if (value === null || value === undefined) return 'text-slate-400'

  const number = Number(value)
  if (!Number.isFinite(number)) return 'text-slate-400'

  if (number > 0) return 'text-emerald-400'
  if (number < 0) return 'text-red-400'

  return 'text-slate-300'
}

function getPhaseLabel(value) {
  return String(value ?? '')
    .replaceAll('_', ' ')
    .toLowerCase()
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function SummaryCard({ label, value, description }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100">
        {value}
      </p>
      {description && (
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {description}
        </p>
      )}
    </div>
  )
}

function HorizonCell({ horizon }) {
  if (!horizon || horizon.sample_count === 0) {
    return (
      <td className="px-4 py-4 text-center text-sm text-slate-500">
        <span>—</span>
        <p className="mt-1 text-xs">No samples</p>
      </td>
    )
  }

  return (
    <td className="px-4 py-4 text-center">
      <p className={`text-sm font-semibold tabular-nums ${getReturnColor(horizon.average_return_pct)}`}>
        {formatPercent(horizon.average_return_pct)}
      </p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        Median {formatPercent(horizon.median_return_pct)}
      </p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        Positive {formatPercent(horizon.positive_return_pct)}
      </p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        n = {formatCount(horizon.sample_count)}
      </p>
      {horizon.unavailable_count > 0 && (
        <p className="mt-1 text-xs text-amber-500">
          {formatCount(horizon.unavailable_count)} unavailable
        </p>
      )}
    </td>
  )
}

export default function ResearchLab({ indices = [] }) {
  const marketIndices = useMemo(
    () => indices.filter((index) => index?.code),
    [indices]
  )

  const [selectedIndex, setSelectedIndex] = useState(
    marketIndices[0]?.code ?? ''
  )
  const [timeframe, setTimeframe] = useState('1D')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [refreshKey, setRefreshKey] = useState(0)
  const [showReturnsInfo, setShowReturnsInfo] = useState(false)

  useEffect(() => {
    if (!marketIndices.length) {
      setSelectedIndex('')
      return
    }

    const selectionExists = marketIndices.some(
      (index) => index.code === selectedIndex
    )

    if (!selectionExists) {
      setSelectedIndex(marketIndices[0].code)
    }
  }, [marketIndices, selectedIndex])

  useEffect(() => {
    if (!selectedIndex) {
      setData(null)
      setLoading(false)
      setError('')
      return
    }

    if (startDate && endDate && startDate > endDate) {
      setData(null)
      setLoading(false)
      setError('Start date cannot be later than end date.')
      return
    }

    let cancelled = false

    async function loadResearch() {
      setLoading(true)
      setError('')
      setData(null)

      try {
        const result = await getForwardReturnsByPhase(selectedIndex, {
          timeframe,
          startDate: startDate || undefined,
          endDate: endDate || undefined,
        })

        if (!cancelled) {
          setData(result)
        }
      } catch (err) {
        if (!cancelled) {
          setData(null)
          setError(
            err?.message || 'Unable to load forward-return research data.'
          )
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadResearch()

    return () => {
      cancelled = true
    }
  }, [selectedIndex, timeframe, startDate, endDate, refreshKey])

  const batchId = data?.batch?.import_batch_id
  const phases = data?.phases ?? []

  const clearDates = () => {
    setStartDate('')
    setEndDate('')
  }

  if (!marketIndices.length) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-8 text-center dark:border-slate-800 dark:bg-slate-900">
        <FlaskConical className="mx-auto h-8 w-8 text-slate-400" />
        <p className="mt-3 font-medium text-slate-800 dark:text-slate-200">
          No market indices available
        </p>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Research Lab requires at least one configured market index.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <FlaskConical className="h-5 w-5 text-violet-500" />
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              Historical Forward Returns
            </h2>
          </div>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Study subsequent index-price performance across market phases.
          </p>
        </div>

        <button
          type="button"
          onClick={() => setRefreshKey((current) => current + 1)}
          disabled={loading}
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="grid grid-cols-1 gap-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900 sm:grid-cols-2 xl:grid-cols-4">
        <div>
          <label
            htmlFor="research-index"
            className="mb-2 block text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400"
          >
            Market Index
          </label>
          <select
            id="research-index"
            value={selectedIndex}
            onChange={(event) => setSelectedIndex(event.target.value)}
            className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-violet-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            {marketIndices.map((index) => (
              <option key={index.code} value={index.code}>
                {index.name || index.code}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="research-timeframe"
            className="mb-2 block text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400"
          >
            Analysis Timeframe
          </label>
          <select
            id="research-timeframe"
            value={timeframe}
            onChange={(event) => setTimeframe(event.target.value)}
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-violet-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            {TIMEFRAMES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label} ({item.value})
              </option>
            ))}
          </select>
        </div>

        <div>
            <CustomDatePicker
                id="research-start-date"
                label="Start Date"
                value={startDate}
                onChange={setStartDate}
            />
        </div>

        <div>
            <CustomDatePicker
                id="research-end-date"
                label="End Date"
                value={endDate}
                onChange={setEndDate}
            />
        </div>

        {(startDate || endDate) && (
          <div className="sm:col-span-2 xl:col-span-4">
            <button
              type="button"
              onClick={clearDates}
              className="text-xs font-medium text-violet-500 hover:text-violet-400"
            >
              Clear date filters
            </button>
          </div>
        )}
      </div>

      {/* Explanation */}
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200">
        Returns shown are for the underlying index, not CE/PE option premiums.
        Each horizon measures the close-to-close return after the selected
        phase-classification candle, using subsequent eligible candles of the
        same timeframe.
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </div>
      )}

      {/* Summary */}
      {data && !error && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard
            label="Classified Candles"
            value={formatCount(data.total_classifications)}
            description="Classification records in selected range"
          />
          <SummaryCard
            label="Eligible Starting Candles"
            value={formatCount(data.eligible_classifications)}
            description="Starting candles included in return analysis"
          />
          <SummaryCard
            label="Import Batch"
            value={batchId ?? '—'}
            description="Resolved completed data batch"
          />
          <SummaryCard
            label="Analysis Timeframe"
            value={data.timeframe ?? timeframe}
            description={data.instrument_code ?? selectedIndex}
          />
        </div>
      )}

      {/* Results table */}
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="flex flex-col gap-1 border-b border-slate-200 px-4 py-4 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-slate-900 dark:text-slate-100">
              Forward Returns by Market Phase
            </h3>

            <button
              type="button"
              onClick={() => setShowReturnsInfo(true)}
              aria-label="Forward returns methodology information"
              className="rounded-full text-slate-400 transition hover:text-violet-500"
            >
              <Info size={16} />
            </button>

            <InfoPopup
              title="Forward Returns by Market Phase"
              open={showReturnsInfo}
              onClose={() => setShowReturnsInfo(false)}
            >
              <div className="space-y-3">
                <p>
                  This analysis measures how the selected index performed after
                  historical market-phase classifications. It helps compare
                  subsequent price behaviour across different market phases.
                </p>

                <div>
                  <p className="font-semibold text-slate-800 dark:text-slate-100">
                    Return calculation
                  </p>
                  <p>
                    Forward return is calculated as the percentage change between
                    the closing price of the starting classification candle and
                    the closing price of a future eligible candle.
                  </p>
                  <p className="mt-1">
                    Return (%) = (Future Close / Starting Close − 1) × 100
                  </p>
                </div>

                <div>
                  <p className="font-semibold text-slate-800 dark:text-slate-100">
                    Forward horizons
                  </p>
                  <p>
                    The 1, 5, 10 and 20 horizons represent subsequent eligible
                    candles in the selected timeframe, not calendar days.
                  </p>
                  <p className="mt-1">
                    For example, a 5-candle horizon on the Weekly timeframe
                    measures the return after five subsequent eligible weekly
                    candles.
                  </p>
                </div>

                <div>
                  <p className="font-semibold text-slate-800 dark:text-slate-100">
                    Performance metrics
                  </p>
                  <ul className="list-disc space-y-1 pl-5">
                    <li><strong>Average Return:</strong> Arithmetic mean of observed forward returns.</li>
                    <li><strong>Median Return:</strong> Middle observed return.</li>
                    <li><strong>Positive Return:</strong> Percentage of observations with returns greater than zero.</li>
                    <li><strong>Samples:</strong> Number of available observations used for that horizon.</li>
                  </ul>
                </div>

                <div>
                  <p className="font-semibold text-slate-800 dark:text-slate-100">
                    Important limitations
                  </p>
                  <ul className="list-disc space-y-1 pl-5">
                    <li>Date filters apply to starting classification candles; future closing candles may fall outside the selected date range.</li>
                    <li>Observations without sufficient future price data are excluded from that horizon.</li>
                    <li>INSUFFICIENT_DATA classifications are excluded from phase return calculations.</li>
                    <li>These are historical underlying-index returns, not CE/PE option premium returns.</li>
                    <li>Historical results do not guarantee future performance.</li>
                  </ul>
                </div>
              </div>
            </InfoPopup>
          </div>

          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Average, median and positive-return percentage for each horizon.
          </p>
        </div>
          {loading && (
            <span className="text-xs text-violet-500">Loading research data…</span>
          )}
        </div>

        {loading && !data ? (
          <div className="p-10 text-center text-sm text-slate-500">
            Loading historical forward returns…
          </div>
        ) : !data ? (
          <div className="p-10 text-center text-sm text-slate-500 dark:text-slate-400">
            Select an index to load research data.
          </div>
        ) : data.availability_status !== 'available' || phases.length === 0 ? (
          <div className="p-10 text-center">
            <p className="font-medium text-slate-700 dark:text-slate-200">
              No research data available
            </p>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {data.availability_message ||
                'There are no eligible classification records for this selection.'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1050px] border-collapse text-left">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:border-slate-800 dark:bg-slate-950/60 dark:text-slate-400">
                  <th className="px-4 py-3 text-left">Market Phase</th>
                  <th className="px-4 py-3 text-center">Classified</th>
                  {HORIZONS.map((horizon) => (
                    <th key={horizon} className="px-4 py-3 text-center">
                      {horizon} Candle{horizon > 1 ? 's' : ''}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {phases.map((phase) => {
                  const phaseName = phase.cycle_classification
                  const phaseStyle =
                    PHASE_STYLES[phaseName] || PHASE_STYLES.INSUFFICIENT_DATA

                  return (
                    <tr
                      key={phaseName}
                      className="border-b border-slate-100 last:border-0 dark:border-slate-800/70"
                    >
                      <td className="px-4 py-4">
                        <div className={`border-l-2 pl-3 text-sm font-semibold ${phaseStyle}`}>
                          {getPhaseLabel(phaseName)}
                        </div>
                      </td>
                      <td className="px-4 py-4 text-center text-sm tabular-nums text-slate-700 dark:text-slate-300">
                        {formatCount(phase.classified_candle_count)}
                      </td>
                      {HORIZONS.map((horizonValue) => {
                        const horizon = phase.horizons?.find(
                          (item) => item.horizon_candles === horizonValue
                        )

                        return (
                          <HorizonCell
                            key={horizonValue}
                            horizon={horizon}
                          />
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Methodology */}
      <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          Research Methodology
        </h3>
        <ul className="mt-3 list-inside list-disc space-y-2 text-xs leading-relaxed text-slate-500 dark:text-slate-400">
          <li>
            Return = (future eligible candle close / classification candle
            close − 1) × 100.
          </li>
          <li>
            The 1, 5, 10 and 20 horizons count subsequent eligible candles,
            not calendar days.
          </li>
          <li>
            Date filters select the starting classification candles. Future
            candles needed to calculate returns may fall after the selected end
            date.
          </li>
          <li>
            Unavailable future observations are excluded from the relevant
            horizon statistics and reported separately.
          </li>
          <li>
            INSUFFICIENT_DATA classifications are displayed separately and
            excluded from return calculations.
          </li>
        </ul>
      </div>
    </div>
  )
}
