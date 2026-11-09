
const timeframes = [
  { id: '1D', label: 'Daily' },
  { id: '1W', label: 'Weekly' },
  { id: '1M', label: 'Monthly' },
  { id: '1Y', label: 'Yearly' },
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
  TRANSITION_UNCERTAIN: 'Transition',
}

function PhaseBreadthSummary({ indices = [], analysis = {} }) {
  const summaries = timeframes.map((timeframe) => {
    const counts = {}
    let classified = 0
    let insufficient = 0

    indices.forEach((index) => {
      const phase =
        analysis[index.code]?.timeframes?.[timeframe.id]
          ?.cycle?.cycle_classification

      if (!phase || phase === 'INSUFFICIENT_DATA') {
        insufficient += 1
        return
      }

      counts[phase] = (counts[phase] || 0) + 1
      classified += 1
    })

    const dominantPhase = Object.entries(counts)
      .sort((a, b) => b[1] - a[1])[0]?.[0] ?? null

    return {
      ...timeframe,
      counts,
      classified,
      insufficient,
      dominantPhase,
    }
  })

  return (
    <section className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold">
          Market Phase Breadth
        </h3>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Distribution of stored classifications across the five market indices
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {summaries.map((summary) => (
          <div
            key={summary.id}
            className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-[#111827]"
          >
            <div className="flex items-center justify-between">
              <h4 className="font-semibold">{summary.label}</h4>
              <span className="text-xs text-slate-500">
                {summary.classified}/{indices.length} classified
              </span>
            </div>

            <div className="mt-4">
              {summary.dominantPhase ? (
                <>
                  <p className="text-xs text-slate-500">
                    Most common phase
                  </p>
                  <p className="mt-1 text-lg font-bold">
                    {phaseLabels[summary.dominantPhase] ??
                      summary.dominantPhase}
                  </p>
                </>
              ) : (
                <p className="text-sm text-slate-500">
                  No classified indices
                </p>
              )}
            </div>

            <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              {Object.entries(summary.counts).map(([phase, count]) => (
                <div
                  key={phase}
                  title={`${phaseLabels[phase] ?? phase}: ${count}`}
                  className={phaseColors[phase] ?? 'bg-slate-400'}
                  style={{
                    width: `${(count / Math.max(indices.length, 1)) * 100}%`,
                  }}
                />
              ))}
            </div>

            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-2">
              {Object.entries(summary.counts).map(([phase, count]) => (
                <span
                  key={phase}
                  className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400"
                >
                  <span
                    className={`h-2 w-2 rounded-full ${
                      phaseColors[phase] ?? 'bg-slate-400'
                    }`}
                  />
                  {phaseLabels[phase] ?? phase}: {count}
                </span>
              ))}
            </div>

            {summary.insufficient > 0 && (
              <p className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500 dark:border-slate-800">
                Insufficient data: {summary.insufficient} indices
              </p>
            )}
          </div>
        ))}
      </div>

      <p className="text-xs text-slate-500 dark:text-slate-400">
        Breadth counts represent indices, not market capitalization or trading
        volume. Insufficient-data records are excluded from phase distribution.
        Transition Uncertain remains a valid classification.
      </p>
    </section>
  )
}

export default PhaseBreadthSummary
