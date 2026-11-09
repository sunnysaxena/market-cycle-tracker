
const timeframes = [
  { id: '1D', label: 'Daily' },
  { id: '1W', label: 'Weekly' },
  { id: '1M', label: 'Monthly' },
]

const phaseColors = {
  ACCUMULATION: 'bg-blue-500',
  MARKUP: 'bg-green-500',
  DISTRIBUTION: 'bg-orange-500',
  MARKDOWN: 'bg-red-500',
  SIDEWAYS_CONSOLIDATION: 'bg-yellow-500',
  TRANSITION_UNCERTAIN: 'bg-purple-500',
}

const phaseLabels = {
  ACCUMULATION: 'Accumulation',
  MARKUP: 'Markup',
  DISTRIBUTION: 'Distribution',
  MARKDOWN: 'Markdown',
  SIDEWAYS_CONSOLIDATION: 'Sideways',
  TRANSITION_UNCERTAIN: 'Transition Uncertain',
}

function getPhase(snapshot) {
  const phase = snapshot?.cycle?.cycle_classification

  if (!phase || phase === 'INSUFFICIENT_DATA') {
    return null
  }

  return phase
}

function calculateSynchronization(indices, analysis, timeframe) {
  const counts = {}

  indices.forEach((index) => {
    const snapshot = analysis[index.code]?.timeframes?.[timeframe]
    const phase = getPhase(snapshot)

    if (phase) {
      counts[phase] = (counts[phase] || 0) + 1
    }
  })

  const entries = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])

  const classified = entries.reduce((total, entry) => total + entry[1], 0)
  const dominant = entries[0] ?? null

  return {
    counts,
    classified,
    insufficient: indices.length - classified,
    dominantPhase: dominant?.[0] ?? null,
    dominantCount: dominant?.[1] ?? 0,
    percentage: classified
      ? Math.round((dominant[1] / classified) * 100)
      : 0,
    dispersion: entries.length,
  }
}

function PhaseSynchronization({ indices = [], analysis = {} }) {
  const summaries = timeframes.map((timeframe) => ({
    ...timeframe,
    ...calculateSynchronization(indices, analysis, timeframe.id),
  }))

  const alignmentRows = indices.map((index) => {
    const phases = timeframes.map((timeframe) =>
      getPhase(
        analysis[index.code]?.timeframes?.[timeframe.id]
      )
    )

    const validPhases = phases.filter(Boolean)
    const distinctPhases = new Set(validPhases)

    return {
      ...index,
      phases,
      aligned:
        validPhases.length === timeframes.length &&
        distinctPhases.size === 1,
      classified: validPhases.length,
    }
  })

  return (
    <section className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">
          Market Synchronization
        </h3>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Measures how consistently the five indices share the same
          classification across timeframes
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {summaries.map((summary) => (
          <div
            key={summary.id}
            className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]"
          >
            <div className="flex items-center justify-between">
              <h4 className="font-semibold">{summary.label}</h4>
              <span className="text-xs text-slate-500">
                {summary.classified}/{indices.length} classified
              </span>
            </div>

            <p className="mt-4 text-3xl font-bold tabular-nums">
              {summary.classified
                ? `${summary.percentage}%`
                : 'N/A'}
            </p>

            <p className="mt-1 text-xs text-slate-500">
              Dominant-phase synchronization
            </p>

            <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className="h-full rounded-full bg-purple-500"
                style={{ width: `${summary.percentage}%` }}
              />
            </div>

            <div className="mt-4 space-y-2 text-sm">
              <div className="flex justify-between gap-2">
                <span className="text-slate-500">Dominant phase</span>
                <span className="font-medium text-right">
                  {phaseLabels[summary.dominantPhase] ?? 'Unavailable'}
                </span>
              </div>

              <div className="flex justify-between">
                <span className="text-slate-500">Matching indices</span>
                <span className="font-medium">
                  {summary.dominantCount}
                </span>
              </div>

              <div className="flex justify-between">
                <span className="text-slate-500">Distinct phases</span>
                <span className="font-medium">
                  {summary.dispersion}
                </span>
              </div>

              <div className="flex justify-between">
                <span className="text-slate-500">Insufficient data</span>
                <span className="font-medium">
                  {summary.insufficient}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
        <div className="border-b border-slate-200 p-4 dark:border-slate-800">
          <h4 className="font-semibold">
            Cross-Timeframe Alignment
          </h4>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Compares Daily, Weekly and Monthly classifications for each index
          </p>
        </div>

        <table className="w-full min-w-[650px] text-left">
          <thead className="bg-slate-50 dark:bg-slate-900/70">
            <tr>
              <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                INDEX
              </th>
              {timeframes.map((timeframe) => (
                <th
                  key={timeframe.id}
                  className="px-4 py-3 text-xs font-semibold text-slate-500"
                >
                  {timeframe.label.toUpperCase()}
                </th>
              ))}
              <th className="px-4 py-3 text-xs font-semibold text-slate-500">
                ALIGNMENT
              </th>
            </tr>
          </thead>

          <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
            {alignmentRows.map((row) => (
              <tr key={row.code}>
                <td className="px-4 py-4 font-semibold">
                  {row.code}
                </td>

                {row.phases.map((phase, index) => (
                  <td key={timeframes[index].id} className="px-4 py-4">
                    {phase ? (
                      <span className="flex items-center gap-2 text-xs font-medium">
                        <span
                          className={`h-2.5 w-2.5 shrink-0 rounded-full ${
                            phaseColors[phase] ?? 'bg-slate-400'
                          }`}
                        />
                        {phaseLabels[phase] ?? phase}
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400">
                        Insufficient data
                      </span>
                    )}
                  </td>
                ))}

                <td className="px-4 py-4">
                  <span
                    className={`rounded-lg px-2.5 py-1 text-xs font-medium ${
                      row.aligned
                        ? 'bg-green-500/10 text-green-600 dark:text-green-400'
                        : 'bg-slate-500/10 text-slate-500'
                    }`}
                  >
                    {row.aligned ? 'Aligned' : 'Not aligned'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400">
        Synchronization measures agreement on the most common classification;
        it does not indicate bullish or bearish direction. Alignment requires
        valid and identical classifications across all three timeframes.
        Insufficient-data records are excluded from these calculations.
      </p>
    </section>
  )
}

export default PhaseSynchronization
