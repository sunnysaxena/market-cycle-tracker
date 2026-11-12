import { useState } from 'react'
import { Info } from 'lucide-react'
import InfoPopup from './InfoPopup'

const phases = [
  {
    id: 'ACCUMULATION',
    label: 'Accumulation',
    color: 'bg-blue-500',
    text: 'text-blue-600 dark:text-blue-400',
  },
  {
    id: 'MARKUP',
    label: 'Markup',
    color: 'bg-green-500',
    text: 'text-green-600 dark:text-green-400',
  },
  {
    id: 'DISTRIBUTION',
    label: 'Distribution',
    color: 'bg-orange-500',
    text: 'text-orange-600 dark:text-orange-400',
  },
  {
    id: 'MARKDOWN',
    label: 'Markdown',
    color: 'bg-red-500',
    text: 'text-red-600 dark:text-red-400',
  },
  {
    id: 'SIDEWAYS_CONSOLIDATION',
    label: 'Sideways',
    color: 'bg-yellow-500',
    text: 'text-yellow-700 dark:text-yellow-400',
  },
  {
    id: 'TRANSITION_UNCERTAIN',
    label: 'Transition',
    color: 'bg-purple-500',
    text: 'text-purple-600 dark:text-purple-400',
  },
]

function getPhase(analysis, indexCode, timeframe) {
  const phase =
    analysis[indexCode]?.timeframes?.[timeframe]?.cycle
      ?.cycle_classification

  if (!phase || phase === 'INSUFFICIENT_DATA') {
    return null
  }

  return phases.some((item) => item.id === phase) ? phase : null
}

function getDominantPhase(counts, classified) {
  if (classified === 0) {
    return { label: 'Insufficient data', tied: false }
  }

  const highestCount = Math.max(...Object.values(counts))
  const leaders = Object.entries(counts).filter(
    ([, count]) => count === highestCount && count > 0
  )

  if (leaders.length !== 1) {
    return { label: 'Mixed', tied: true }
  }

  return {
    label: phases.find((phase) => phase.id === leaders[0][0])?.label ?? 'Mixed',
    tied: false,
  }
}

function MetricCard({ label, value, description }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-2 text-2xl font-bold text-slate-900 dark:text-slate-100">
        {value}
      </p>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        {description}
      </p>
    </div>
  )
}

function MarketRegimeAssessment({ indices = [], analysis = {} }) {
  const [showInfo, setShowInfo] = useState(false)

  const dailyCounts = Object.fromEntries(
    phases.map((phase) => [phase.id, 0])
  )

  let dailyClassified = 0
  let dailyInsufficient = 0
  let weeklyAgreement = 0
  let weeklyComparable = 0

  indices.forEach((index) => {
    const daily = getPhase(analysis, index.code, '1D')
    const weekly = getPhase(analysis, index.code, '1W')

    if (daily) {
      dailyCounts[daily] += 1
      dailyClassified += 1
    } else {
      dailyInsufficient += 1
    }

    if (daily && weekly) {
      weeklyComparable += 1

      if (daily === weekly) {
        weeklyAgreement += 1
      }
    }
  })

  const dominant = getDominantPhase(dailyCounts, dailyClassified)

  const representedPhases = phases.filter(
    (phase) => dailyCounts[phase.id] > 0
  )

  const dailyConsensus =
    dailyClassified > 0 && representedPhases.length === 1

  const fullySynchronized =
    dailyClassified === indices.length &&
    dailyConsensus &&
    weeklyComparable === indices.length &&
    weeklyAgreement === indices.length

  const overallRegime =
    dailyClassified === 0
      ? 'INSUFFICIENT DATA'
      : dailyClassified < indices.length
        ? dailyConsensus
          ? representedPhases[0].label.toUpperCase()
          : 'PARTIAL / MIXED'
        : dailyConsensus
          ? representedPhases[0].label.toUpperCase()
          : 'MIXED'

  const synchronizationLabel =
    fullySynchronized
      ? 'Synchronized'
      : dailyClassified < indices.length
        ? 'Partial data'
        : dailyConsensus
          ? 'Daily consensus'
          : 'Mixed phases'

  const dailyDispersion = representedPhases.length

    // Index-wise contribution to the dominant daily regime
  const dominantPhaseId =
    dailyClassified > 0 && !dominant.tied
      ? phases.find((phase) => phase.label === dominant.label)?.id ?? null
      : null

  const regimeContributions = indices.map((index) => {
    const phaseId = getPhase(analysis, index.code, '1D')
    const phase = phases.find((item) => item.id === phaseId)

    const status = !phaseId
      ? 'Insufficient data'
      : !dominantPhaseId
        ? 'Mixed / tied'
        : phaseId === dominantPhaseId
          ? 'Aligned'
          : 'Divergent'

    return {
      indexCode: index.code,
      phaseLabel: phase?.label ?? 'Insufficient data',
      status,
    }
  })

  const interpretation =
    dailyClassified === 0
      ? 'No valid daily classifications are currently available.'
      : dominant.tied
        ? `The market is mixed: multiple phases share the highest representation across ${dailyClassified} classified indices.`
        : `${dominant.label} is the most represented daily phase, appearing in ${dailyCounts[phases.find((phase) => phase.label === dominant.label)?.id] ?? 0} of ${dailyClassified} classified indices.`

  const summaryDescription =
    dailyClassified === 0
      ? 'No valid daily phase classifications are available.'
      : dailyConsensus
        ? `All ${dailyClassified} classified indices share the same daily phase.`
        : `${dailyClassified} classified indices currently represent ${dailyDispersion} different daily phases.`

  return (
    <section className="space-y-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/40">
        <div>
                <div className="flex items-center gap-2">
                    <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                    Market Regime Assessment
                    </h3>

                    <button
                    type="button"
                    onClick={() => setShowInfo(true)}
                    aria-label="Market Regime Assessment information"
                    title="About Market Regime Assessment"
                    className="rounded-full p-1 text-slate-400 transition hover:bg-slate-100 hover:text-blue-500 dark:hover:bg-slate-800"
                    >
                    <Info size={16} />
                    </button>
                </div>

                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    Equal-weighted assessment of the five tracked indices using existing
                    market-cycle classifications
                </p>
        </div>

        {/* Overall Market Regime Summary */}
        <div className="rounded-xl border border-purple-200 bg-purple-50/70 p-5 dark:border-purple-900/60 dark:bg-purple-950/20">
            <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                Overall Market Regime
                </p>

                <h4 className="mt-2 text-2xl font-bold text-purple-700 dark:text-purple-300">
                {overallRegime}
                </h4>

                <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                {summaryDescription}
                </p>
            </div>

            <div className="rounded-lg border border-purple-200 bg-white px-4 py-3 dark:border-purple-800 dark:bg-slate-900">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                Alignment Status
                </p>
                <p className="mt-1 text-sm font-bold text-purple-700 dark:text-purple-300">
                {synchronizationLabel}
                </p>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {weeklyAgreement}/{weeklyComparable} Daily–Weekly matches
                </p>
            </div>
            </div>
        </div>

        {/* Existing Metric Cards */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
            label="Most Represented Daily Phase"
            value={dominant.label}
            description={`${dailyClassified} of ${indices.length} indices classified`}
            />

            <MetricCard
            label="Daily–Weekly Agreement"
            value={`${weeklyAgreement} / ${weeklyComparable}`}
            description="Indices with matching valid Daily and Weekly phases"
            />

            <MetricCard
            label="Daily Phase Dispersion"
            value={`${dailyDispersion} / 6`}
            description="Distinct daily phases currently represented"
            />

            <MetricCard
            label="Insufficient Daily Data"
            value={`${dailyInsufficient} / ${indices.length}`}
            description="Indices without a valid daily classification"
            />
        </div>

        {/* Daily Phase Participation */}
        <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                Daily Phase Participation
            </h4>
            <span className="text-xs text-slate-500 dark:text-slate-400">
                {dailyClassified} classified indices
            </span>
            </div>

            <div className="flex h-4 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
            {phases.map((phase) => {
                const count = dailyCounts[phase.id]
                const width = dailyClassified
                ? (count / dailyClassified) * 100
                : 0

                return count > 0 ? (
                <div
                    key={phase.id}
                    className={`${phase.color} h-full`}
                    style={{ width: `${width}%` }}
                    title={`${phase.label}: ${count}`}
                />
                ) : null
            })}
            </div>

            <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
            {phases.map((phase) => (
                <div key={phase.id} className="flex items-center gap-2">
                <span
                    className={`h-2.5 w-2.5 shrink-0 rounded-full ${phase.color}`}
                />
                <span className="text-xs text-slate-600 dark:text-slate-400">
                    {phase.label}
                </span>
                <span className={`ml-auto text-xs font-semibold ${phase.text}`}>
                    {dailyCounts[phase.id]}
                </span>
                </div>
            ))}
            </div>
        </div>

        {/* Index-wise Regime Contribution */}
        <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-3">
            <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
                Index-wise Regime Contribution
            </h4>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                Daily phase alignment against the most represented phase
            </p>
            </div>

            <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-left text-sm">
                <thead>
                <tr className="border-b border-slate-200 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
                    <th className="px-3 py-2 font-medium">Index</th>
                    <th className="px-3 py-2 font-medium">Daily Phase</th>
                    <th className="px-3 py-2 font-medium">Contribution</th>
                </tr>
                </thead>

                <tbody>
                {regimeContributions.map((item) => (
                    <tr
                    key={item.indexCode}
                    className="border-b border-slate-100 last:border-0 dark:border-slate-800"
                    >
                    <td className="px-3 py-3 font-semibold text-slate-800 dark:text-slate-200">
                        {item.indexCode}
                    </td>

                    <td className="px-3 py-3 text-slate-600 dark:text-slate-400">
                        {item.phaseLabel}
                    </td>

                    <td className="px-3 py-3">
                        <span
                        className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${
                            item.status === 'Aligned'
                            ? 'bg-green-100 text-green-700 dark:bg-green-950/50 dark:text-green-400'
                            : item.status === 'Divergent'
                                ? 'bg-orange-100 text-orange-700 dark:bg-orange-950/50 dark:text-orange-400'
                                : item.status === 'Mixed / tied'
                                ? 'bg-purple-100 text-purple-700 dark:bg-purple-950/50 dark:text-purple-400'
                                : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                        }`}
                        >
                        {item.status}
                        </span>
                    </td>
                    </tr>
                ))}
                </tbody>
            </table>
            </div>
        </div>

        {/* Regime Interpretation */}
        <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h4 className="text-sm font-semibold text-slate-800 dark:text-slate-200">
            Regime Interpretation
          </h4>
          <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-400">
            {interpretation}
          </p>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-500">
            Daily–Weekly agreement:{' '}
            {weeklyComparable > 0
              ? `${((weeklyAgreement / weeklyComparable) * 100).toFixed(1)}% of comparable indices`
              : 'No comparable classifications available'}
            . This is descriptive alignment, not a probability or trading signal.
          </p>
        </div>

        {/* Market Regime Assessment Information */}
        <InfoPopup
          open={showInfo}
          onClose={() => setShowInfo(false)}
          title="Understanding Market Regime Assessment"
        >
          <div>
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              What is Market Regime Assessment?
            </h4>
            <p>
              It provides an equal-weighted overview of the current market-cycle
              classifications across NIFTY50, BANKNIFTY, SENSEX, FINNIFTY, and
              MIDCPNIFTY using their existing daily classifications.
            </p>
          </div>

          <div>
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              Overall Market Regime
            </h4>
            <p>
              The most represented daily phase is used as the dominant regime
              when one phase has the highest count. A tie between leading phases
              is reported as Mixed. A dominant phase does not necessarily mean
              that a majority of indices share it.
            </p>
          </div>

          <div>
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              Daily–Weekly Agreement
            </h4>
            <p>
              Measures how many indices have matching valid Daily and Weekly
              classifications. Only indices with valid classifications on both
              timeframes are included in this comparison.
            </p>
          </div>

          <div>
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              Daily Phase Dispersion
            </h4>
            <p>
              Counts the number of distinct daily phases represented across the
              tracked indices. A lower count indicates fewer different phases;
              a higher count indicates greater phase diversity.
            </p>
          </div>

          <div>
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              Index-wise Regime Contribution
            </h4>
            <p>
              Aligned means an index matches the unique dominant daily phase.
              Divergent means it has a different valid daily phase. Mixed / tied
              means there is no unique dominant phase. Insufficient data means
              the index has no valid daily classification.
            </p>
          </div>

          <div>
            <h4 className="font-semibold text-slate-900 dark:text-slate-100">
              Important Interpretation
            </h4>
            <p>
              All tracked indices are weighted equally. Insufficient-data
              classifications are excluded from phase counts. Transition
              Uncertain remains a valid phase. These metrics describe market
              structure and alignment; they are not probabilities, forecasts,
              or trading signals.
            </p>
          </div>
        </InfoPopup>

    </section>
  )
}

export default MarketRegimeAssessment
