import { useState } from 'react'
import { Info } from 'lucide-react'
import InfoPopup from './InfoPopup'

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
  const dominantCount = entries[0]?.[1] ?? 0

  const dominantPhases =
    dominantCount > 0
      ? entries
          .filter(([, count]) => count === dominantCount)
          .map(([phase]) => phase)
      : []

  return {
    counts,
    classified,
    insufficient: indices.length - classified,
    dominantPhases,
    dominantCount,
    percentage: classified
      ? Math.round((dominantCount / classified) * 100)
      : 0,
    dispersion: entries.length,
  }
}

function PhaseSynchronization({ indices = [], analysis = {} }) {
  const [showSyncInfo, setShowSyncInfo] = useState(false)
  const [showAlignmentInfo, setShowAlignmentInfo] = useState(false)
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
      status:
        validPhases.length !== timeframes.length
          ? 'Insufficient data'
          : distinctPhases.size === 1
            ? 'Aligned'
            : 'Different phases',
      classified: validPhases.length,
    }
  })

  return (
    <section className="space-y-4">
      <div>
      <div className="flex items-center gap-2">
          <h3 className="text-lg font-semibold">
            Market Synchronization
          </h3>

          <button
            type="button"
            onClick={() => setShowSyncInfo(true)}
            aria-label="Market Synchronization information"
            title="About Market Synchronization"
            className="rounded-full p-1 text-slate-400 transition hover:bg-slate-100 hover:text-primary-hover dark:hover:bg-slate-800"
          >
            <Info size={16} />
          </button>
        </div>

        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Measures how consistently the {indices.length} registered market indices share the same classification across timeframes
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
                  {summary.dominantPhases.length > 0
                    ? summary.dominantPhases
                        .map((phase) => phaseLabels[phase] ?? phase)
                        .join(', ')
                    : 'Unavailable'}
                </span>
              </div>

              <div className="flex justify-between">
                <span className="text-slate-500">Indices per leading phase</span>
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
          <div className="flex items-center gap-2">
            <h4 className="font-semibold">
              Cross-Timeframe Alignment
            </h4>

            <button
              type="button"
              onClick={() => setShowAlignmentInfo(true)}
              aria-label="Cross-Timeframe Alignment information"
              title="About Cross-Timeframe Alignment"
              className="rounded-full p-1 text-slate-400 transition hover:bg-slate-100 hover:text-primary-hover dark:hover:bg-slate-800"
            >
              <Info size={16} />
            </button>
          </div>

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
                      row.status === 'Aligned'
                        ? 'bg-green-500/10 text-green-600 dark:text-green-400'
                        : row.status === 'Different phases'
                          ? 'bg-orange-500/10 text-orange-600 dark:text-orange-400'
                          : 'bg-slate-500/10 text-slate-500'
                    }`}
                  >
                    {row.status}
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
        Insufficient-data records are excluded from synchronization percentages
        and shown separately in the alignment table.
      </p>

      <InfoPopup
        open={showSyncInfo}
        onClose={() => setShowSyncInfo(false)}
        title="Understanding Market Synchronization"
      >
        <div>
          <h4 className="font-semibold text-slate-900 dark:text-slate-100">
            What is Market Synchronization?
          </h4>
          <p>
            It measures how consistently the tracked indices share the same
            market-phase classification within a timeframe. It helps assess
            whether indices are moving through similar market conditions.
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-slate-900 dark:text-slate-100">
            Dominant Phase
          </h4>
          <p>
            The phase or phases with the highest number of classified indices.
            When multiple phases share the highest count, they are displayed
            as tied leading phases. The leading group is not necessarily a majority.
        </p>
        </div>

        <div>
          <h4 className="font-semibold text-slate-900 dark:text-slate-100">
            Synchronization Percentage
          </h4>
          <p>
            <p>
              Calculated as the number of indices in any one leading phase divided
              by all classified indices, multiplied by 100. If multiple phases tie,
              the percentage represents each tied phase separately. Insufficient-data
              indices are excluded from this calculation.
            </p>
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-slate-900 dark:text-slate-100">
            Distinct Phases
          </h4>
          <p>
            The number of different valid phase classifications currently
            present across the indices. More distinct phases indicate greater
            phase dispersion.
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-slate-900 dark:text-slate-100">
            Important Limitation
          </h4>
          <p>
            High synchronization means agreement in classification, not
            necessarily bullish direction. It is a descriptive market
            breadth measure, not a trading signal.
          </p>
        </div>
      </InfoPopup>

      <InfoPopup
        open={showAlignmentInfo}
        onClose={() => setShowAlignmentInfo(false)}
        title="Understanding Cross-Timeframe Alignment"
      >
        <div>
          <h4 className="font-semibold text-slate-900 dark:text-slate-100">
            What is Cross-Timeframe Alignment?
          </h4>
          <p>
            It compares an individual index's Daily, Weekly and Monthly
            market-phase classifications to determine whether all three
            timeframes agree.
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-slate-900 dark:text-slate-100">
            Aligned
          </h4>
          <p>
            All three timeframes must have valid classifications, and all
            three classifications must be identical.
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-slate-900 dark:text-slate-100">
            Not Aligned
          </h4>
          <p>
            The table distinguishes two situations:
            Different phases means all three timeframes have valid classifications
            but they disagree. Insufficient data means one or more timeframes
            lack a valid classification.
          </p>
        </div>

        <div>
          <h4 className="font-semibold text-slate-900 dark:text-slate-100">
            Important Limitation
          </h4>
          <p>
            Alignment indicates consistency across timeframes. It does not
            establish bullish or bearish direction, nor does it guarantee
            future market behaviour.
          </p>
        </div>
      </InfoPopup>
    </section>

  )
}

export default PhaseSynchronization
