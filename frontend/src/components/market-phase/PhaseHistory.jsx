import { useEffect, useMemo, useState } from 'react'
import { Info, RefreshCw } from 'lucide-react'
import { getAllMarketCycles } from '../../api/client'
import InfoPopup from './InfoPopup'

const TIMEFRAMES = [
  { id: '1D', label: 'Daily' },
  { id: '1W', label: 'Weekly' },
  { id: '1M', label: 'Monthly' },
  { id: '1Y', label: 'Yearly' },
]

const PHASES = [
  'ACCUMULATION',
  'MARKUP',
  'DISTRIBUTION',
  'MARKDOWN',
  'SIDEWAYS_CONSOLIDATION',
  'TRANSITION_UNCERTAIN',
  'INSUFFICIENT_DATA',
]

const PHASE_COLORS = {
  ACCUMULATION: 'bg-blue-500',
  MARKUP: 'bg-green-500',
  DISTRIBUTION: 'bg-orange-500',
  MARKDOWN: 'bg-red-500',
  SIDEWAYS_CONSOLIDATION: 'bg-yellow-500',
  TRANSITION_UNCERTAIN: 'bg-purple-500',
  INSUFFICIENT_DATA: 'bg-slate-400',
}

function getValidPhase(phase) {
  if (!phase || phase === 'INSUFFICIENT_DATA') {
    return null
  }

  return PHASES.includes(phase) ? phase : null
}

function formatPhaseName(phase) {
  return phase
    .split('_')
    .map((word) => word.charAt(0) + word.slice(1).toLowerCase())
    .join(' ')
}

function formatDate(date) {
  if (!date) return '—'

  return new Date(`${date}T00:00:00`).toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export default function PhaseHistory({ indices = [] }) {
  const [history, setHistory] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedIndex, setSelectedIndex] = useState('ALL')
  const [selectedTimeframe, setSelectedTimeframe] = useState('1D')
  const [durationTimeframe, setDurationTimeframe] = useState('1D')
  const [durationIndex, setDurationIndex] = useState('ALL')

  const [individualIndex, setIndividualIndex] = useState(
    indices[0]?.code ?? 'NIFTY50'
  )
  const [individualTimeframe, setIndividualTimeframe] = useState('1D')

  const [individualPage, setIndividualPage] = useState(1)
  const individualPageSize = 50


  const [showDistributionInfo, setShowDistributionInfo] = useState(false)
  const [showCalendarInfo, setShowCalendarInfo] = useState(false)
  const [showDurationInfo, setShowDurationInfo] = useState(false)
  const [showIndexHistoryInfo, setShowIndexHistoryInfo] = useState(false)


  const [calendarYear, setCalendarYear] = useState(
    new Date().getFullYear()
  )
  const [calendarMonth, setCalendarMonth] = useState(
    new Date().getMonth()
  )
  
  const loadHistory = async () => {
    if (!indices.length) {
      setHistory({})
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)

    try {
      const requests = indices.flatMap((index) =>
        TIMEFRAMES.map(async (timeframe) => {
          const response = await getAllMarketCycles(index.code, {
            timeframe: timeframe.id,
            importBatchId: 5,
            limit: 2000,
          })

          return {
            key: `${index.code}_${timeframe.id}`,
            records: response.records ?? [],
          }
        })
      )

      const results = await Promise.all(requests)

      const nextHistory = Object.fromEntries(
        results.map((result) => [result.key, result.records])
      )

      setHistory(nextHistory)
    } catch (err) {
      setError(err.message || 'Unable to load historical phase data.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadHistory()
  }, [])


useEffect(() => {
  setIndividualPage(1)
}, [individualIndex, individualTimeframe])


  const availableRecords = useMemo(() => {
    return Object.values(history).flat()
  }, [history])


  const distributionStats = useMemo(() => {
    const counts = Object.fromEntries(
      PHASES.filter((phase) => phase !== 'INSUFFICIENT_DATA').map(
        (phase) => [phase, 0]
      )
    )

    let insufficientCount = 0
    let totalRecords = 0

    const selectedIndices =
      selectedIndex === 'ALL'
        ? indices
        : indices.filter((index) => index.code === selectedIndex)

    selectedIndices.forEach((index) => {
      const records =
        history[`${index.code}_${selectedTimeframe}`] ?? []

      records.forEach((record) => {
        totalRecords += 1

        const phase = record.cycle_classification

        if (phase === 'INSUFFICIENT_DATA') {
          insufficientCount += 1
          return
        }

        const validPhase = getValidPhase(phase)

        if (validPhase) {
          counts[validPhase] += 1
        }
      })
    })

    const classifiedCount = Object.values(counts).reduce(
      (total, count) => total + count,
      0
    )

    return {
      counts,
      insufficientCount,
      totalRecords,
      classifiedCount,
    }
  }, [history, indices, selectedIndex, selectedTimeframe])



  const calendarData = useMemo(() => {
    const records = []

    const selectedIndices =
      selectedIndex === 'ALL'
        ? indices
        : indices.filter((index) => index.code === selectedIndex)

    selectedIndices.forEach((index) => {
      const dailyRecords = history[`${index.code}_1D`] ?? []

      dailyRecords.forEach((record) => {
        const date = record.period_start
        const phase = record.cycle_classification

        if (!date || !getValidPhase(phase)) return

        const recordDate = new Date(`${date}T00:00:00`)

        if (recordDate.getFullYear() !== calendarYear) return

        records.push({
          date,
          indexCode: index.code,
          indexName: index.name ?? index.display_name ?? index.code,
          phase,
          ruleScore: record.rule_score,
        })
      })
    })

    return records.sort((a, b) => a.date.localeCompare(b.date))
  }, [history, indices, selectedIndex, calendarYear])

  const calendarCells = useMemo(() => {
    const firstDay = new Date(calendarYear, calendarMonth, 1).getDay()
    const daysInMonth = new Date(
      calendarYear,
      calendarMonth + 1,
      0
    ).getDate()

    const recordsByDate = new Map()

    calendarData.forEach((record) => {
      if (!recordsByDate.has(record.date)) {
        recordsByDate.set(record.date, [])
      }

      recordsByDate.get(record.date).push(record)
    })

    const cells = Array(firstDay).fill(null)

    for (let day = 1; day <= daysInMonth; day += 1) {
      const date = [
        calendarYear,
        String(calendarMonth + 1).padStart(2, '0'),
        String(day).padStart(2, '0'),
      ].join('-')

      cells.push({
        day,
        date,
        records: recordsByDate.get(date) ?? [],
      })
    }

    return cells
  }, [calendarYear, calendarMonth, calendarData])



  const durationStats = useMemo(() => {
    const stats = []

    const selectedIndices =
      selectedIndex === 'ALL'
        ? indices
        : indices.filter((index) => index.code === selectedIndex)

    selectedIndices.forEach((index) => {
      TIMEFRAMES.forEach((timeframe) => {
        const records = [
          ...(history[`${index.code}_${timeframe.id}`] ?? []),
        ].sort((a, b) =>
          a.period_start.localeCompare(b.period_start)
        )

        const groups = []
        let currentGroup = null

        records.forEach((record) => {
          const phase = getValidPhase(record.cycle_classification)

          // An explicit insufficient-data record breaks continuity.
          if (!phase) {
            currentGroup = null
            return
          }

          if (currentGroup && currentGroup.phase === phase) {
            currentGroup.endDate = record.period_end
            currentGroup.records += 1
          } else {
            currentGroup = {
              phase,
              startDate: record.period_start,
              endDate: record.period_end,
              records: 1,
            }

            groups.push(currentGroup)
          }
        })

        const phaseGroups = PHASES
          .filter((phase) => phase !== 'INSUFFICIENT_DATA')
          .map((phase) => {
            const periods = groups.filter(
              (group) => group.phase === phase
            )

            const durations = periods.map(
              (group) => group.records
            )

            return {
              phase,
              periods: periods.length,
              averageDuration: durations.length
                ? durations.reduce((sum, value) => sum + value, 0) /
                  durations.length
                : 0,
              longestDuration: durations.length
                ? Math.max(...durations)
                : 0,
              shortestDuration: durations.length
                ? Math.min(...durations)
                : 0,
            }
          })

        stats.push({
          indexCode: index.code,
          indexName: index.name ?? index.display_name ?? index.code,
          timeframe: timeframe.id,
          timeframeLabel: timeframe.label,
          phaseGroups,
        })
      })
    })

    return stats
  }, [history, indices, selectedIndex])




  const selectedDurationStats = useMemo(
    () =>
      durationStats.filter(
        (item) =>
          item.timeframe === durationTimeframe &&
          (durationIndex === 'ALL' ||
            item.indexCode === durationIndex)
      ),
    [durationStats, durationTimeframe, durationIndex]
  )


  const durationSummary = useMemo(() => {
    const phaseTotals = PHASES
      .filter((phase) => phase !== 'INSUFFICIENT_DATA')
      .map((phase) => {
        const periods = selectedDurationStats.flatMap((item) =>
          item.phaseGroups
            .filter((group) => group.phase === phase)
            .flatMap((group) => Array(group.periods).fill(group.averageDuration))
        )

        return {
          phase,
          periods: periods.length,
          averageDuration: periods.length
            ? periods.reduce((sum, value) => sum + value, 0) /
              periods.length
            : 0,
        }
      })

    return phaseTotals
  }, [selectedDurationStats])



  const individualHistory = useMemo(() => {
    const records = history[
      `${individualIndex}_${individualTimeframe}`
    ] ?? []

    return [...records].sort((a, b) =>
      b.period_start.localeCompare(a.period_start)
    )
  }, [history, individualIndex, individualTimeframe])


  const individualTotalPages = Math.max(
    1,
    Math.ceil(individualHistory.length / individualPageSize)
  )

  const individualPageRecords = individualHistory.slice(
    (individualPage - 1) * individualPageSize,
    individualPage * individualPageSize
  )


  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              Historical Phase Analysis
            </h3>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Historical market-cycle classifications across five indices
            </p>
          </div>

          <button
            type="button"
            onClick={loadHistory}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900">
            <p className="text-xs text-slate-500">Indices</p>
            <p className="mt-1 text-xl font-semibold text-slate-900 dark:text-slate-100">
              {indices.length}
            </p>
          </div>

          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900">
            <p className="text-xs text-slate-500">Historical Records</p>
            <p className="mt-1 text-xl font-semibold text-slate-900 dark:text-slate-100">
              {availableRecords.length.toLocaleString('en-IN')}
            </p>
          </div>

          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900">
            <p className="text-xs text-slate-500">Timeframes</p>
            <p className="mt-1 text-xl font-semibold text-slate-900 dark:text-slate-100">
              {TIMEFRAMES.length}
            </p>
          </div>
        </div>

        {error && (
          <p className="mt-3 text-sm text-rose-500">{error}</p>
        )}
      </div>

      
      {/* Historical Phase Distribution */}
      <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-[#111827]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-5 dark:border-slate-800">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                Historical Phase Distribution
              </h3>

              <button
                type="button"
                onClick={() => setShowDistributionInfo(true)}
                aria-label="Historical Phase Distribution information"
                title="About Historical Phase Distribution"
                className="rounded-full p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-blue-500 dark:hover:bg-slate-800 dark:hover:text-blue-400"
              >
                <Info size={16} />
              </button>
            </div>

            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Classification frequency across selected indices and timeframe
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              Index
              <select
                value={selectedIndex}
                onChange={(event) => setSelectedIndex(event.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
              >
                <option value="ALL">All Indices</option>
                {indices.map((index) => (
                  <option key={index.code} value={index.code}>
                    {index.name ?? index.display_name ?? index.code}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              Timeframe
              <select
                value={selectedTimeframe}
                onChange={(event) => setSelectedTimeframe(event.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
              >
                {TIMEFRAMES.map((timeframe) => (
                  <option key={timeframe.id} value={timeframe.id}>
                    {timeframe.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 p-5 sm:grid-cols-3">
          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900">
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Classified Records
            </p>
            <p className="mt-1 text-xl font-semibold text-slate-900 dark:text-slate-100">
              {distributionStats.classifiedCount.toLocaleString('en-IN')}
            </p>
          </div>

          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900">
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Insufficient Data
            </p>
            <p className="mt-1 text-xl font-semibold text-slate-900 dark:text-slate-100">
              {distributionStats.insufficientCount.toLocaleString('en-IN')}
            </p>
          </div>

          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900">
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Total Records
            </p>
            <p className="mt-1 text-xl font-semibold text-slate-900 dark:text-slate-100">
              {distributionStats.totalRecords.toLocaleString('en-IN')}
            </p>
          </div>
        </div>

        <div className="space-y-4 px-5 pb-5">
          {Object.entries(distributionStats.counts).map(([phase, count]) => {
            const percentage =
              distributionStats.classifiedCount > 0
                ? (count / distributionStats.classifiedCount) * 100
                : 0

            return (
              <div key={phase}>
                <div className="mb-1 flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                    {formatPhaseName(phase)}
                  </span>

                  <span className="text-sm tabular-nums text-slate-500 dark:text-slate-400">
                    {count.toLocaleString('en-IN')} ({percentage.toFixed(1)}%)
                  </span>
                </div>

                <div className="h-2.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <div
                    className={`h-full rounded-full ${PHASE_COLORS[phase]}`}
                    style={{ width: `${percentage}%` }}
                  />
                </div>
              </div>
            )
          })}

          {!loading && distributionStats.totalRecords === 0 && (
            <p className="py-4 text-center text-sm text-slate-500 dark:text-slate-400">
              No historical records are available for this selection.
            </p>
          )}
        </div>

        <div className="border-t border-slate-200 px-5 py-3 dark:border-slate-800">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Percentages are calculated using valid classifications only.
            Insufficient Data records are reported separately.
          </p>
        </div>

        <InfoPopup
          open={showDistributionInfo}
          onClose={() => setShowDistributionInfo(false)}
          title="Understanding Historical Phase Distribution"
        >
          <div>
            <h4 className="mb-2 font-semibold text-slate-900 dark:text-slate-100">
              Calculation Method
            </h4>
            <ul className="space-y-2">
              <li><strong>Classified Records:</strong> Records with one of the six valid market-cycle classifications.</li>
              <li><strong>Insufficient Data:</strong> Records without enough information for a valid phase classification. They are excluded from phase percentages.</li>
              <li><strong>Total Records:</strong> All retrieved records for the selected index and timeframe.</li>
              <li><strong>Phase Percentage:</strong> Number of records in a phase divided by total valid classified records, multiplied by 100.</li>
            </ul>
          </div>

          <div>
            <h4 className="mb-2 font-semibold text-slate-900 dark:text-slate-100">
              Important Interpretation
            </h4>
            <p>
              This distribution describes historical classification frequency.
              It does not measure market capitalization, trading volume,
              probability of a future phase, or expected returns.
            </p>
            <p className="mt-2">
              Transition Uncertain is included as a valid classification.
            </p>
          </div>
        </InfoPopup>
      </section>

      
      {/* Phase Calendar Heatmap */}
      <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-5 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              Phase Calendar Heatmap
            </h3>
            <button
              type="button"
              onClick={() => setShowCalendarInfo(true)}
              className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
              aria-label="About Phase Calendar Heatmap"
            >
              <Info size={16} />
            </button>
          </div>



          <div className="flex flex-wrap items-center gap-3">
            {/* Index and Year filters */}
            <div className="flex items-center gap-2">
              <select
                value={selectedIndex}
                onChange={(event) => setSelectedIndex(event.target.value)}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
              >
                <option value="ALL">All Indices</option>
                {indices.map((index) => (
                  <option key={index.code} value={index.code}>
                    {index.name ?? index.code}
                  </option>
                ))}
              </select>

              <select
                value={calendarYear}
                onChange={(event) => setCalendarYear(Number(event.target.value))}
                className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
              >
                {Array.from(
                  { length: new Date().getFullYear() - 2010 + 1 },
                  (_, i) => 2010 + i
                ).map((year) => (
                  <option key={year} value={year}>
                    {year}
                  </option>
                ))}
              </select>
            </div>

            {/* Compact month navigation */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() =>
                  setCalendarMonth((month) => (month + 11) % 12)
                }
                className="rounded-md border border-slate-300 px-2 py-2 text-sm dark:border-slate-700"
                aria-label="Previous month"
              >
                ←
              </button>

              <span className="min-w-24 text-center text-sm font-medium text-slate-800 dark:text-slate-200">
                {new Date(calendarYear, calendarMonth).toLocaleDateString(
                  'en-IN',
                  { month: 'long' }
                )}
              </span>

              <button
                type="button"
                onClick={() =>
                  setCalendarMonth((month) => (month + 1) % 12)
                }
                className="rounded-md border border-slate-300 px-2 py-2 text-sm dark:border-slate-700"
                aria-label="Next month"
              >
                →
              </button>
            </div>
          </div>

        </div>

        <div className="p-5">
          <div className="grid grid-cols-7 gap-2">
            {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(
              (day) => (
                <div
                  key={day}
                  className="py-2 text-center text-xs font-semibold text-slate-500"
                >
                  {day}
                </div>
              )
            )}

            {calendarCells.map((cell, index) => (
              <div
                key={cell?.date ?? `empty-${index}`}
                title={
                  cell
                    ? `${cell.date}: ${
                        cell.records.length
                          ? cell.records
                              .map(
                                (record) =>
                                  `${record.indexCode}: ${formatPhaseName(record.phase)}`
                              )
                              .join(' | ')
                          : 'No classified record'
                      }`
                    : undefined
                }
                className={`flex min-h-14 flex-col items-center justify-center rounded-lg border p-1 ${
                  cell
                    ? 'border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-900'
                    : 'border-transparent'
                }`}
              >
                {cell && (
                  <>
                    <span className="text-xs text-slate-600 dark:text-slate-300">
                      {cell.day}
                    </span>

                    <div className="mt-1 flex flex-wrap justify-center gap-1">
                      {cell.records.map((record) => (
                        <span
                          key={record.indexCode}
                          className={`h-2.5 w-2.5 rounded-sm ${PHASE_COLORS[record.phase]}`}
                        />
                      ))}
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>

          <div className="mt-5 flex flex-wrap gap-3">
            {PHASES.filter((phase) => phase !== 'INSUFFICIENT_DATA').map(
              (phase) => (
                <div key={phase} className="flex items-center gap-2">
                  <span
                    className={`h-3 w-3 rounded-sm ${PHASE_COLORS[phase]}`}
                  />
                  <span className="text-xs text-slate-600 dark:text-slate-400">
                    {formatPhaseName(phase)}
                  </span>
                </div>
              )
            )}
          </div>

          <p className="mt-4 text-xs text-slate-500 dark:text-slate-400">
            Each colored marker represents a stored daily phase
            classification. When All Indices is selected, multiple markers
            can appear on the same date.
          </p>
        </div>

        <InfoPopup
          open={showCalendarInfo}
          onClose={() => setShowCalendarInfo(false)}
          title="Phase Calendar Heatmap"
        >
          <p>
            This calendar displays stored daily market-cycle classifications
            by date. Each color represents a market phase.
          </p>
          <p>
            When All Indices is selected, each date can contain multiple
            markers, one for each index with a valid classification.
          </p>
          <p>
            Weekends and dates without classified records remain empty.
            INSUFFICIENT_DATA records are excluded from the heatmap.
          </p>
          <p>
            TRANSITION_UNCERTAIN is a valid classification. Rule scores are
            not probabilities or forecasts.
          </p>
        </InfoPopup>
      </section>

      
      {/* Phase Duration Analysis */}
      <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-5 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              Phase Duration Analysis
            </h3>
            <button
              type="button"
              onClick={() => setShowDurationInfo(true)}
              className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
              aria-label="About Phase Duration Analysis"
            >
              <Info size={16} />
            </button>
          </div>


          
          <div className="flex items-center gap-2">
            <select
              value={durationIndex}
              onChange={(event) => setDurationIndex(event.target.value)}
              className="w-40 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            >
              <option value="ALL">All Indices</option>
              {indices.map((index) => (
                <option key={index.code} value={index.code}>
                  {index.name ?? index.code}
                </option>
              ))}
            </select>

            <select
              value={durationTimeframe}
              onChange={(event) => setDurationTimeframe(event.target.value)}
              className="w-32 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            >
              {TIMEFRAMES.map((timeframe) => (
                <option key={timeframe.id} value={timeframe.id}>
                  {timeframe.label}
                </option>
              ))}
            </select>
          </div>
        </div>


        <div className="grid grid-cols-1 gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
          {durationSummary.map((item) => (
            <div
              key={item.phase}
              className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900"
            >
              <div className="flex items-center gap-2">
                <span
                  className={`h-3 w-3 rounded-sm ${PHASE_COLORS[item.phase]}`}
                />
                <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                  {formatPhaseName(item.phase)}
                </p>
              </div>
              <p className="mt-2 text-xl font-semibold text-slate-900 dark:text-slate-100">
                {item.averageDuration.toFixed(1)}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Average duration · {item.periods} observed periods
              </p>
            </div>
          ))}
        </div>

        <div className="overflow-x-auto border-t border-slate-200 dark:border-slate-800">
          <table className="w-full min-w-[700px] text-left text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500 dark:bg-slate-900 dark:text-slate-400">
              <tr>
                <th className="px-4 py-3">Index</th>
                <th className="px-4 py-3">Market Phase</th>
                <th className="px-4 py-3 text-right">Periods</th>
                <th className="px-4 py-3 text-right">Average</th>
                <th className="px-4 py-3 text-right">Shortest</th>
                <th className="px-4 py-3 text-right">Longest</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {selectedDurationStats.flatMap((item) =>
                item.phaseGroups
                  .filter((group) => group.periods > 0)
                  .map((group) => (
                    <tr
                      key={`${item.indexCode}_${item.timeframe}_${group.phase}`}
                      className="text-slate-700 dark:text-slate-300"
                    >
                      <td className="px-4 py-3 font-medium">
                        {item.indexCode}
                      </td>
                      <td className="px-4 py-3">
                        <span className="flex items-center gap-2">
                          <span
                            className={`h-2.5 w-2.5 rounded-sm ${PHASE_COLORS[group.phase]}`}
                          />
                          {formatPhaseName(group.phase)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {group.periods}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {group.averageDuration.toFixed(1)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {group.shortestDuration}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        {group.longestDuration}
                      </td>
                    </tr>
                  ))
              )}
            </tbody>
          </table>

          {selectedDurationStats.every((item) =>
            item.phaseGroups.every((group) => group.periods === 0)
          ) && (
            <p className="p-6 text-center text-sm text-slate-500">
              No classified phase-duration history is available.
            </p>
          )}
        </div>

        <div className="p-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Daily duration is measured in calendar days. Weekly, Monthly and
            Yearly duration is measured in stored classified candles.
            Statistics describe completed observed phase periods.
          </p>
        </div>

        <InfoPopup
          open={showDurationInfo}
          onClose={() => setShowDurationInfo(false)}
          title="Phase Duration Analysis"
        >
          <p>
            This analysis groups consecutive stored classifications into
            historical phase periods for each index and timeframe.
          </p>
          <p>
            Average, shortest and longest durations are calculated from
            observed periods. Daily duration uses calendar days; other
            timeframes use classified candles.
          </p>
          <p>
            INSUFFICIENT_DATA records are excluded. Missing records can affect
            the continuity of historical periods, so these statistics should
            be interpreted as estimates from available stored history.
          </p>
          <p>
            Historical durations do not predict how long the current or next
            market phase will last.
          </p>
        </InfoPopup>
      </section>

      
      {/* Individual Index Phase History */}
      <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-950">
        
        
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-5 dark:border-slate-800">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                Individual Index Phase History
              </h3>

              <button
                type="button"
                onClick={() => setShowIndexHistoryInfo(true)}
                className="rounded-md p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                aria-label="About individual index phase history"
              >
                <Info size={16} />
              </button>
            </div>

            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Chronological record of stored market-cycle classifications.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={individualIndex}
              onChange={(event) => setIndividualIndex(event.target.value)}
              className="w-40 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            >
              {indices.map((index) => (
                <option key={index.code} value={index.code}>
                  {index.name ?? index.display_name ?? index.code}
                </option>
              ))}
            </select>

            <select
              value={individualTimeframe}
              onChange={(event) => setIndividualTimeframe(event.target.value)}
              className="w-32 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
            >
              {TIMEFRAMES.map((timeframe) => (
                <option key={timeframe.id} value={timeframe.id}>
                  {timeframe.label}
                </option>
              ))}
            </select>
          </div>
        </div>


        <div className="overflow-x-auto">
          <table className="w-full min-w-[1000px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500 dark:bg-slate-900 dark:text-slate-400">
              <tr>
                <th className="px-4 py-3">Period Start</th>
                <th className="px-4 py-3">Period End</th>
                <th className="px-4 py-3">Market Phase</th>
                <th className="px-4 py-3">Rule Score</th>
                <th className="px-4 py-3">Classification Basis</th>
                <th className="px-4 py-3">Calculation Version</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {individualPageRecords.map((record, index) => {
                const phase = record.cycle_classification
                const score = Number(record.rule_score)

                return (
                  <tr
                    key={`${record.period_start}-${index}`}
                    className="text-slate-700 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-900"
                  >
                    <td className="whitespace-nowrap px-4 py-3">
                      {formatDate(record.period_start)}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {formatDate(record.period_end)}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center gap-2 whitespace-nowrap">
                        <span
                          className={`h-2.5 w-2.5 rounded-full ${PHASE_COLORS[phase] ?? 'bg-slate-400'}`}
                        />
                        {phase ? formatPhaseName(phase) : 'Unavailable'}
                      </span>
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {record.rule_score != null && Number.isFinite(score)
                        ? score.toFixed(1)
                        : '—'}
                    </td>
                    <td className="px-4 py-3">
                      {record.classification_basis
                        ? formatPhaseName(record.classification_basis)
                        : '—'}
                    </td>
                    <td
                      className="max-w-[220px] truncate px-4 py-3 text-xs"
                      title={record.calculation_version ?? ''}
                    >
                      {record.calculation_version ?? '—'}
                    </td>
                  </tr>
                )
              })}

              {individualPageRecords.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-10 text-center text-slate-500 dark:text-slate-400"
                  >
                    No phase history is available for this selection.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 p-4 dark:border-slate-800">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {individualHistory.length === 0
              ? 'No records'
              : `Showing ${(individualPage - 1) * individualPageSize + 1}–${Math.min(individualPage * individualPageSize, individualHistory.length)} of ${individualHistory.length} records`}
          </p>

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={individualPage <= 1}
              onClick={() => setIndividualPage((page) => page - 1)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
            >
              Previous
            </button>

            <span className="text-xs text-slate-500 dark:text-slate-400">
              Page {individualPage} of {individualTotalPages}
            </span>

            <button
              type="button"
              disabled={individualPage >= individualTotalPages}
              onClick={() => setIndividualPage((page) => page + 1)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-300"
            >
              Next
            </button>
          </div>
        </div>

        <div className="p-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Latest classifications are displayed first. INSUFFICIENT_DATA
            records are retained to show historical data coverage.
          </p>
        </div>

        <InfoPopup
          open={showIndexHistoryInfo}
          onClose={() => setShowIndexHistoryInfo(false)}
          title="Individual Index Phase History"
        >
          <p>
            This table displays stored market-cycle classifications for the
            selected index and timeframe, with the latest period first.
          </p>
          <p>
            Period start and end identify the classified candle period.
            Rule Score is a rule-based score, not a probability, confidence
            percentage or forecast.
          </p>
          <p>
            Classification Basis and Calculation Version identify the
            classification context and engine version used to generate
            each stored record.
          </p>
          <p>
            INSUFFICIENT_DATA records are displayed for transparency but
            do not represent a directional market phase.
          </p>
        </InfoPopup>
      </section>

    </div>
  )
}
