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
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Market Regime Assessment
        </h3>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
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
    </section>
  )
}

export default MarketRegimeAssessment
