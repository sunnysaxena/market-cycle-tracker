import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Info, RefreshCw } from 'lucide-react'
import { getAllMarketCycles } from '../../api/client'
import InfoPopup from './InfoPopup'

const TIMEFRAMES = [
  { id: '1D', label: 'Daily' },
  { id: '1W', label: 'Weekly' },
  { id: '1M', label: 'Monthly' },
]

const CLASSIFICATION_LABELS = {
  ACCUMULATION: 'Accumulation',
  MARKUP: 'Markup',
  DISTRIBUTION: 'Distribution',
  MARKDOWN: 'Markdown',
  SIDEWAYS_CONSOLIDATION: 'Sideways Consolidation',
  TRANSITION_UNCERTAIN: 'Transition Uncertain',
  INSUFFICIENT_DATA: 'Insufficient Data',
}

function formatDate(value) {
  if (!value) return 'â€”'

  const date = new Date(`${value}T00:00:00`)

  if (Number.isNaN(date.getTime())) return value

  return date.toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

function getTransitionType(previousPhase, currentPhase) {
  if (
    previousPhase === 'MARKDOWN' &&
    currentPhase === 'MARKUP'
  ) {
    return 'Bullish Reversal'
  }

  if (
    previousPhase === 'MARKUP' &&
    currentPhase === 'MARKDOWN'
  ) {
    return 'Bearish Reversal'
  }

  if (
    previousPhase === 'TRANSITION_UNCERTAIN' ||
    currentPhase === 'TRANSITION_UNCERTAIN'
  ) {
    return 'Uncertain Transition'
  }

  if (currentPhase === 'ACCUMULATION') {
    return 'Moving into Accumulation'
  }

  if (currentPhase === 'DISTRIBUTION') {
    return 'Moving into Distribution'
  }

  if (currentPhase === 'SIDEWAYS_CONSOLIDATION') {
    return 'Entering Sideways'
  }

  return 'Other Phase Change'
}

function PhaseLabel({ phase }) {
  const colors = {
    ACCUMULATION:
      'bg-sky-500/10 text-sky-400 border-sky-500/20',
    MARKUP:
      'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    DISTRIBUTION:
      'bg-amber-500/10 text-amber-400 border-amber-500/20',
    MARKDOWN:
      'bg-rose-500/10 text-rose-400 border-rose-500/20',
    SIDEWAYS_CONSOLIDATION:
      'bg-violet-500/10 text-violet-400 border-violet-500/20',
    TRANSITION_UNCERTAIN:
      'bg-orange-500/10 text-orange-400 border-orange-500/20',
  }

  return (
    <span
      className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${
        colors[phase] ??
        'border-slate-500/20 bg-slate-500/10 text-slate-400'
      }`}
    >
      {CLASSIFICATION_LABELS[phase] ?? phase}
    </span>
  )
}

export default function RecentPhaseChanges({ indices = [] }) {
  const [changes, setChanges] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [selectedIndex, setSelectedIndex] = useState('ALL')
  const [selectedTimeframe, setSelectedTimeframe] = useState('ALL')
  const [showInfo, setShowInfo] = useState(false)


  const filteredChanges = useMemo(
    () =>
      changes.filter((change) => {
        const matchesIndex =
          selectedIndex === 'ALL' ||
          change.indexCode === selectedIndex

        const matchesTimeframe =
          selectedTimeframe === 'ALL' ||
          change.timeframe === selectedTimeframe

        return matchesIndex && matchesTimeframe
      }),
    [changes, selectedIndex, selectedTimeframe]
  )

  const indexKey = useMemo(
    () => indices.map((index) => index.code).join('|'),
    [indices]
  )

  const [refreshing, setRefreshing] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const handleRefresh = () => {
    setRefreshing(true)
    setRefreshKey((previous) => previous + 1)
  }

  useEffect(() => {
    let cancelled = false

    async function loadChanges() {
      setLoading(true)
      setError('')

      try {
        const activeIndices = indices.filter((index) => index.code)

        const requests = activeIndices.flatMap((index) =>
          TIMEFRAMES.map(async (timeframe) => {
            const response = await getAllMarketCycles(index.code, {
              timeframe: timeframe.id,
              importBatchId: 5,
              limit: 2000,
            })

            return {
              indexCode: index.code,
              indexName: index.name ?? index.display_name ?? index.code,
              timeframe: timeframe.label,
              records: response.records ?? [],
            }
          })
        )

        const results = await Promise.allSettled(requests)

        const datasets = results
          .filter((result) => result.status === 'fulfilled')
          .map((result) => result.value)

        const failedRequests = results.filter(
          (result) => result.status === 'rejected'
        )

        if (datasets.length === 0 && failedRequests.length > 0) {
          throw failedRequests[0].reason
        }

        if (cancelled) return

        const detectedChanges = []

        datasets.forEach((dataset) => {
          const records = [...dataset.records].sort((a, b) =>
            String(a.period_start).localeCompare(String(b.period_start))
          )

          for (let i = 1; i < records.length; i += 1) {
            const previous = records[i - 1]
            const current = records[i]

            const previousPhase = previous.cycle_classification
            const currentPhase = current.cycle_classification

            if (
              !previousPhase ||
              !currentPhase ||
              previousPhase === 'INSUFFICIENT_DATA' ||
              currentPhase === 'INSUFFICIENT_DATA' ||
              previousPhase === currentPhase
            ) {
              continue
            }

            detectedChanges.push({
              id: `${dataset.indexCode}-${dataset.timeframe}-${current.period_start}`,
              indexCode: dataset.indexCode,
              indexName: dataset.indexName,
              timeframe: dataset.timeframe,
              date: current.period_start,
              previousPhase,
              currentPhase,
              transitionType: getTransitionType(
                previousPhase,
                currentPhase
              ),
              ruleScore: current.rule_score,
            })
          }
        })

        detectedChanges.sort((a, b) =>
          String(b.date).localeCompare(String(a.date))
        )

        if (!cancelled) {
          setChanges(detectedChanges)

          if (failedRequests.length > 0) {
            setError(
              `${failedRequests.length} of ${requests.length} index/timeframe requests failed. Showing available results.`
            )
          }
        }
        } catch (err) {
          if (!cancelled) {
            setError(
              err.message || 'Unable to load historical phase changes.'
            )
          }
        } finally {
          if (!cancelled) {
            setLoading(false)
            setRefreshing(false)
          }
        }
        }

    loadChanges()

    return () => {
      cancelled = true
    }
  }, [indexKey, refreshKey])

  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-[#111827]">
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Loading historical phase changes...
        </p>
      </div>
    )
  }

 if (error && changes.length === 0) {
    return (
      <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-5">
        <p className="text-sm font-medium text-rose-400">
          Unable to load phase changes
        </p>
        <p className="mt-1 text-sm text-slate-500">{error}</p>
      </div>
    )
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-[#111827]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-5 dark:border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              Recent Phase Changes
            </h3>
            <button
              type="button"
              onClick={() => setShowInfo(true)}
              aria-label="Recent Phase Changes information"
              title="About Recent Phase Changes"
              className="rounded-full p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-primary-hover dark:hover:bg-slate-800 dark:hover:text-primary-hover"
            >
              <Info size={16} />
            </button>
          </div>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Historical transitions across {indices.length} registered market indices and three timeframes
          </p>
        </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
              Index
              <select
                value={selectedIndex}
                onChange={(event) => setSelectedIndex(event.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-primary dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
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
                className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-primary dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
              >
                <option value="ALL">All Timeframes</option>
                <option value="Daily">Daily</option>
                <option value="Weekly">Weekly</option>
                <option value="Monthly">Monthly</option>
              </select>
            </label>

            <span className="text-xs text-slate-500 dark:text-slate-400">
              {filteredChanges.length} transitions
            </span>

            <button
              type="button"
              onClick={handleRefresh}
              disabled={loading || refreshing}
              title="Refresh phase changes"
              aria-label="Refresh phase changes"
              className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <RefreshCw
                size={15}
                className={refreshing ? 'animate-spin' : ''}
              />
              Refresh
            </button>
          </div>
      </div>

      {filteredChanges.length === 0 ? (
        <div className="p-8 text-center">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No phase transitions match the selected filters.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[850px] text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
              <tr>
                <th className="px-5 py-3 font-medium">Date</th>
                <th className="px-5 py-3 font-medium">Index</th>
                <th className="px-5 py-3 font-medium">Timeframe</th>
                <th className="px-5 py-3 font-medium">Transition Type</th>
                <th className="px-5 py-3 font-medium">Previous Phase</th>
                <th className="px-5 py-3 font-medium">New Phase</th>
                <th className="px-5 py-3 text-right font-medium">
                  Rule Score
                </th>
              </tr>
            </thead>

            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {filteredChanges.slice(0, 30).map((change) => (
                <tr
                  key={change.id}
                  className="transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/40"
                >
                  <td className="whitespace-nowrap px-5 py-4 text-slate-600 dark:text-slate-300">
                    {formatDate(change.date)}
                  </td>

                  <td className="px-5 py-4 font-medium text-slate-900 dark:text-slate-100">
                    {change.indexName}
                  </td>

                  <td className="px-5 py-4 text-slate-600 dark:text-slate-300">
                    {change.timeframe}
                  </td>

                  <td className="px-5 py-4">
                    <span className="inline-flex rounded-md border border-primary/20 bg-primary-soft px-2 py-1 text-xs font-medium text-primary">
                      {change.transitionType}
                    </span>
                  </td>

                  <td className="px-5 py-4">
                    <PhaseLabel phase={change.previousPhase} />
                  </td>

                  <td className="px-5 py-4">
                    <div className="flex items-center gap-2">
                      <PhaseLabel phase={change.currentPhase} />
                      <ArrowRight
                        size={14}
                        className="text-slate-400"
                      />
                    </div>
                  </td>

                  <td className="px-5 py-4 text-right font-semibold tabular-nums text-slate-700 dark:text-slate-200">
                    {change.ruleScore ?? 'â€”'}
                    {change.ruleScore != null ? '/100' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="border-t border-slate-200 px-5 py-3 dark:border-slate-800">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Only changes between consecutive valid classifications are shown.
          Insufficient Data records are excluded. Rule scores are classification
          scores, not transition probabilities.
        </p>
      </div>
          <InfoPopup
            open={showInfo}
            onClose={() => setShowInfo(false)}
            title="Understanding Recent Phase Changes"
          >
        <div>
          <h4 className="mb-2 font-semibold text-slate-900 dark:text-slate-100">
            Field Information
          </h4>

          <ul className="space-y-2">
            <li><strong>Date:</strong> Start date of the period in which the phase change was detected.</li>
            <li><strong>Index:</strong> Market index associated with the classification.</li>
            <li><strong>Timeframe:</strong> Daily, Weekly or Monthly analysis period.</li>
            <li><strong>Transition Type:</strong> Category describing the movement between two consecutive phases.</li>
            <li><strong>Previous Phase:</strong> Valid classification from the preceding period.</li>
            <li><strong>New Phase:</strong> Classification detected in the current period.</li>
            <li><strong>Rule Score:</strong> Classification score from 0â€“100, not a probability or prediction.</li>
          </ul>
        </div>

        <div>
          <h4 className="mb-3 font-semibold text-slate-900 dark:text-slate-100">
            Transition Type Definitions
          </h4>

          <div className="space-y-3">
            <p><strong>Bullish Reversal:</strong> Markdown â†’ Markup.</p>
            <p><strong>Bearish Reversal:</strong> Markup â†’ Markdown.</p>
            <p><strong>Moving into Accumulation:</strong> Another valid phase â†’ Accumulation.</p>
            <p><strong>Moving into Distribution:</strong> Another valid phase â†’ Distribution.</p>
            <p><strong>Entering Sideways:</strong> Another valid phase â†’ Sideways Consolidation.</p>
            <p><strong>Uncertain Transition:</strong> Entering or leaving Transition Uncertain.</p>
            <p><strong>Other Phase Change:</strong> Any remaining valid phase transition.</p>
          </div>
        </div>

        <div className="rounded-lg bg-slate-100 p-3 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          <strong>Important:</strong> Insufficient Data classifications are excluded from transition detection. Transition Uncertain indicates mixed or incomplete evidence; it does not confirm a bullish or bearish reversal.
        </div>
      </InfoPopup>
    </section>
  )
}
