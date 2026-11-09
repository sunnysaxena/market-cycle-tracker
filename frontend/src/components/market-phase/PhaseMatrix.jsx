
const timeframes = [
  { id: '1D', label: 'Daily' },
  { id: '1W', label: 'Weekly' },
  { id: '1M', label: 'Monthly' },
  { id: '1Y', label: 'Yearly' },
]

const phaseStyles = {
  ACCUMULATION: 'border-blue-500/40 bg-blue-500/10 text-blue-600 dark:text-blue-400',
  MARKUP: 'border-green-500/40 bg-green-500/10 text-green-600 dark:text-green-400',
  DISTRIBUTION: 'border-orange-500/40 bg-orange-500/10 text-orange-600 dark:text-orange-400',
  MARKDOWN: 'border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400',
  SIDEWAYS_CONSOLIDATION: 'border-yellow-500/40 bg-yellow-500/10 text-yellow-700 dark:text-yellow-400',
  TRANSITION_UNCERTAIN: 'border-purple-500/40 bg-purple-500/10 text-purple-600 dark:text-purple-400',
  INSUFFICIENT_DATA: 'border-slate-400/40 bg-slate-500/10 text-slate-500 dark:text-slate-400',
}

function formatPhase(value) {
  if (!value) return 'Unavailable'

  return value
    .split('_')
    .map((word) => word.charAt(0) + word.slice(1).toLowerCase())
    .join(' ')
}

function formatPeriod(period) {
  if (!period?.period_start) return 'Period unavailable'

  if (period.period_start === period.period_end) {
    return period.period_start
  }

  return `${period.period_start} – ${period.period_end}`
}

function PhaseCell({ snapshot, timeframe }) {
  const cycle = snapshot?.cycle
  const phase = cycle?.cycle_classification
  const style = phaseStyles[phase] ?? phaseStyles.INSUFFICIENT_DATA
  const status = snapshot?.availability?.status ?? 'unavailable'
  const ruleScore = cycle?.rule_score

  return (
    <div className={`min-w-36 rounded-lg border p-3 ${style}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-xs font-semibold opacity-75">
          {timeframe.label}
        </span>
        <span className="text-[10px] uppercase opacity-70">
          {status}
        </span>
      </div>

      <p className="text-sm font-bold leading-5">
        {formatPhase(phase)}
      </p>

      <p className="mt-2 text-[11px] opacity-75">
        {formatPeriod(snapshot?.period)}
      </p>

      {typeof ruleScore === 'number' && (
        <p className="mt-2 text-xs font-medium">
          Rule score: {ruleScore}/100
        </p>
      )}
    </div>
  )
}

function PhaseMatrix({ indices, analysis, loading, error }) {
  if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 p-8 text-center dark:border-slate-800">
        <p className="text-sm text-slate-500">
          Loading index-wise market phases...
        </p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-300 bg-red-50 p-5 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
        Unable to load the phase matrix: {error}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-lg font-semibold">
            Index-wise Phase Matrix
          </h3>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Current stored classification across five indices and four timeframes
          </p>
        </div>

        <span className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-500 dark:border-slate-700">
          5 Indices · 4 Timeframes
        </span>
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
        <table className="w-full min-w-[1050px] border-collapse text-left">
          <thead className="bg-slate-50 dark:bg-slate-900/70">
            <tr>
              <th className="w-36 px-4 py-4 text-xs font-semibold text-slate-500">
                INDEX
              </th>

              {timeframes.map((timeframe) => (
                <th
                  key={timeframe.id}
                  className="px-3 py-4 text-xs font-semibold text-slate-500"
                >
                  {timeframe.label.toUpperCase()}
                </th>
              ))}
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
            {indices.map((index) => {
              const snapshots = analysis[index.code]?.timeframes

              return (
                <tr key={index.code}>
                  <td className="px-4 py-4 align-top">
                    <p className="font-semibold">{index.code}</p>
                    <p className="mt-1 text-xs text-slate-500">
                      {index.name}
                    </p>
                  </td>

                  {timeframes.map((timeframe) => (
                    <td
                      key={timeframe.id}
                      className="px-3 py-3 align-top"
                    >
                      <PhaseCell
                        snapshot={snapshots?.[timeframe.id]}
                        timeframe={timeframe}
                      />
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400">
        Note: Rule score is the classification engine's rule score, not a probability.
        Partial availability does not automatically mean the phase classification
        is missing. Yearly periods show the actual stored period, not an assumed
        current-year classification.
      </p>
    </div>
  )
}

export default PhaseMatrix
