import { useEffect, useMemo, useState } from 'react'
import {
  ArrowRight,
  Info,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'

import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceArea,
} from 'recharts'

import {
  getAllMarketCycles,
  getAllMarketHistory,
} from '../../api/client'

import InfoPopup from './InfoPopup'

const TIMEFRAMES = [
  { id: '1D', label: 'Daily' },
  { id: '1W', label: 'Weekly' },
  { id: '1M', label: 'Monthly' },
  { id: '1Y', label: 'Yearly' },
]

const CHART_RANGES = [
  { id: '1Y', label: '1 Year' },
  { id: '3Y', label: '3 Years' },
  { id: '5Y', label: '5 Years' },
  { id: '10Y', label: '10 Years' },
  { id: 'ALL', label: 'All History' },
]

const PHASES = [
  'ACCUMULATION',
  'MARKUP',
  'DISTRIBUTION',
  'MARKDOWN',
  'SIDEWAYS_CONSOLIDATION',
  'TRANSITION_UNCERTAIN',
]

const CLASSIFICATION_LABELS = {
  ACCUMULATION: 'Accumulation',
  MARKUP: 'Markup',
  DISTRIBUTION: 'Distribution',
  MARKDOWN: 'Markdown',
  SIDEWAYS_CONSOLIDATION: 'Sideways Consolidation',
  TRANSITION_UNCERTAIN: 'Transition Uncertain',
}

const PHASE_COLORS = {
  ACCUMULATION: 'bg-sky-500',
  MARKUP: 'bg-emerald-500',
  DISTRIBUTION: 'bg-amber-500',
  MARKDOWN: 'bg-rose-500',
  SIDEWAYS_CONSOLIDATION: 'bg-violet-500',
  TRANSITION_UNCERTAIN: 'bg-orange-500',
}


const PHASE_CHART_COLORS = {
  ACCUMULATION: '#0EA5E9',
  MARKUP: '#10B981',
  DISTRIBUTION: '#F59E0B',
  MARKDOWN: '#F43F5E',
  SIDEWAYS_CONSOLIDATION: '#8B5CF6',
  TRANSITION_UNCERTAIN: '#F97316',
}


const PHASE_BADGE_COLORS = {
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

const PAGE_SIZE = 50

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

function formatPhaseName(phase) {
  return CLASSIFICATION_LABELS[phase] ?? phase ?? 'â€”'
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

function PhaseBadge({ phase }) {
  return (
    <span
      className={`inline-flex whitespace-nowrap rounded-md border px-2 py-1 text-xs font-medium ${
        PHASE_BADGE_COLORS[phase] ??
        'border-slate-500/20 bg-slate-500/10 text-slate-400'
      }`}
    >
      {formatPhaseName(phase)}
    </span>
  )
}

function InfoButton({ onClick, label }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${label} information`}
      title={`About ${label}`}
      className="rounded-full p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-primary-hover dark:hover:bg-slate-800 dark:hover:text-primary-hover"
    >
      <Info size={16} />
    </button>
  )
}

export default function PhaseTransitions({ indices = [] }) {
  
  // Existing code continues here...
  const [transitions, setTransitions] = useState([])
  const [phaseDatasets, setPhaseDatasets] = useState([])
  const [priceDatasets, setPriceDatasets] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [selectedIndex, setSelectedIndex] = useState('ALL')
  const [selectedTimeframe, setSelectedTimeframe] = useState('ALL')
  const [selectedTransitionType, setSelectedTransitionType] = useState('ALL')
  const [selectedPhase, setSelectedPhase] = useState('ALL')
  const [chartRange, setChartRange] = useState('1Y')

  const [currentPage, setCurrentPage] = useState(1)

  const [showTimelineInfo, setShowTimelineInfo] = useState(false)
  const [showMatrixInfo, setShowMatrixInfo] = useState(false)
  const [showFrequencyInfo, setShowFrequencyInfo] = useState(false)
  const [showRecordsInfo, setShowRecordsInfo] = useState(false)
  const [selectedChartTransition, setSelectedChartTransition] = useState(null)

  const indexKey = useMemo(
    () => indices.map((index) => index.code).filter(Boolean).join('|'),
    [indices]
  )


useEffect(() => {
    let cancelled = false

    async function loadTransitions() {
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
                    indexName:
                        index.name ?? index.display_name ?? index.code,
                    timeframe: timeframe.id,
                    timeframeLabel: timeframe.label,
                    records: response.records ?? [],
                }
            })
        )

        const priceRequests = activeIndices.flatMap((index) =>
            TIMEFRAMES.map(async (timeframe) => {
                const response = await getAllMarketHistory(index.code, {
                    timeframe: timeframe.id,
                    importBatchId: 5,
                    limit: 2000,
                })

                return {
                    indexCode: index.code,
                    indexName:
                        index.name ?? index.display_name ?? index.code,
                    timeframe: timeframe.id,
                    timeframeLabel: timeframe.label,
                    records: response.records ?? [],
                }
            })
        )

        const [datasets, historicalPrices] = await Promise.all([
            Promise.all(requests),
            Promise.all(priceRequests),
        ])

        if (cancelled) return

        setPhaseDatasets(datasets)
        setPriceDatasets(historicalPrices)

        const detectedTransitions = []

        datasets.forEach((dataset) => {
            const records = [...dataset.records].sort((a, b) =>
            String(a.period_start).localeCompare(
                String(b.period_start)
            )
            )

            for (let i = 1; i < records.length; i += 1) {
                const previous = records[i - 1]
                const current = records[i]

                const previousPhase = previous.cycle_classification
                const currentPhase = current.cycle_classification

                // Insufficient Data breaks transition continuity.
                if (
                    !PHASES.includes(previousPhase) ||
                    !PHASES.includes(currentPhase) ||
                    previousPhase === currentPhase
                ) {
                    continue
                }

                detectedTransitions.push({
                    id: `${dataset.indexCode}-${dataset.timeframe}-${current.period_start}`,
                    indexCode: dataset.indexCode,
                    indexName: dataset.indexName,
                    timeframe: dataset.timeframe,
                    timeframeLabel: dataset.timeframeLabel,
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


        detectedTransitions.sort((a, b) =>
            String(b.date).localeCompare(String(a.date))
        )

        if (!cancelled) {
            setTransitions(detectedTransitions)
        }
        } catch (err) {
        if (!cancelled) {
            setError(
            err.message || 'Unable to load historical transitions.'
            )
        }
        } finally {
        if (!cancelled) {
            setLoading(false)
        }
        }
    }

    if (!indexKey) {
      setTransitions([])
      setPhaseDatasets([])
      setPriceDatasets([])
      setLoading(false)
      return undefined
    }

    loadTransitions()

    return () => {
        cancelled = true
    }
    }, [indexKey])

    const filteredTransitions = useMemo(
    () =>
      transitions.filter((transition) => {
        const matchesIndex =
          selectedIndex === 'ALL' ||
          transition.indexCode === selectedIndex

        const matchesTimeframe =
          selectedTimeframe === 'ALL' ||
          transition.timeframe === selectedTimeframe

        const matchesType =
          selectedTransitionType === 'ALL' ||
          transition.transitionType === selectedTransitionType

        const matchesPhase =
          selectedPhase === 'ALL' ||
          transition.previousPhase === selectedPhase ||
          transition.currentPhase === selectedPhase

        return (
          matchesIndex &&
          matchesTimeframe &&
          matchesType &&
          matchesPhase
        )
      }),
    [
      transitions,
      selectedIndex,
      selectedTimeframe,
      selectedTransitionType,
      selectedPhase,
    ]
  )


const phaseProgressionData = useMemo(() => {
  const chartIndexCode =
    selectedIndex === 'ALL'
      ? indices[0]?.code
      : selectedIndex

  const chartTimeframe =
    selectedTimeframe === 'ALL'
      ? '1D'
      : selectedTimeframe

  if (!chartIndexCode) return []

  const phaseDataset = phaseDatasets.find(
    (dataset) =>
      dataset.indexCode === chartIndexCode &&
      dataset.timeframe === chartTimeframe
  )

  const priceDataset = priceDatasets.find(
    (dataset) =>
      dataset.indexCode === chartIndexCode &&
      dataset.timeframe === chartTimeframe
  )

  if (!phaseDataset || !priceDataset) return []

  const phaseByDate = new Map(
    phaseDataset.records.map((record) => [
      record.period_start,
      record,
    ])
  )

  return priceDataset.records
    .map((record) => {
      const date = record.period_start ?? record.candle_date
      const phaseRecord = phaseByDate.get(date)

      if (!phaseRecord) return null

      return {
        date,
        close: Number(record.close),
        open: Number(record.open),
        high: Number(record.high),
        low: Number(record.low),
        phase: phaseRecord.cycle_classification,
        ruleScore: phaseRecord.rule_score,
      }
    })
    .filter(
      (record) =>
        record &&
        Number.isFinite(record.close)
    )
    .sort((a, b) =>
      String(a.date).localeCompare(String(b.date))
    )
}, [
  indices,
  selectedIndex,
  selectedTimeframe,
  phaseDatasets,
  priceDatasets,
])


const visiblePhaseProgressionData = useMemo(() => {
  if (phaseProgressionData.length === 0) return []

  if (chartRange === 'ALL') {
    return phaseProgressionData
  }

  const latestDate = new Date(
    `${phaseProgressionData[phaseProgressionData.length - 1].date}T00:00:00`
  )

  const startDate = new Date(latestDate)
  const years = Number(chartRange.replace('Y', ''))

  startDate.setFullYear(startDate.getFullYear() - years)

  return phaseProgressionData.filter((record) => {
    const recordDate = new Date(`${record.date}T00:00:00`)

    return recordDate >= startDate && recordDate <= latestDate
  })
}, [phaseProgressionData, chartRange])


const visibleChartTransitions = useMemo(() => {
  const chartIndexCode =
    selectedIndex === 'ALL'
      ? indices[0]?.code
      : selectedIndex

  const chartTimeframe =
    selectedTimeframe === 'ALL'
      ? '1D'
      : selectedTimeframe

  if (!chartIndexCode || visiblePhaseProgressionData.length === 0) {
    return []
  }

  const priceByDate = new Map(
    visiblePhaseProgressionData.map((record) => [
      record.date,
      record,
    ])
  )

  return transitions
    .filter(
      (transition) =>
        transition.indexCode === chartIndexCode &&
        transition.timeframe === chartTimeframe &&
        priceByDate.has(transition.date)
    )
    .map((transition) => {
      const priceRecord = priceByDate.get(transition.date)

      const indexInfo = indices.find(
        (index) => index.code === transition.indexCode
      )

      return {
        ...transition,
        indexName: indexInfo?.name ?? transition.indexCode,
        close: priceRecord.close,
      }
    })
    .sort((a, b) =>
      String(a.date).localeCompare(String(b.date))
    )
}, [
  indices,
  selectedIndex,
  selectedTimeframe,
  visiblePhaseProgressionData,
  transitions,
])



const visiblePhaseSegments = useMemo(() => {
  if (visiblePhaseProgressionData.length === 0) return []

  const segments = []
  let currentSegment = null

  visiblePhaseProgressionData.forEach((record) => {
    if (!PHASES.includes(record.phase)) {
      if (currentSegment) {
        segments.push(currentSegment)
        currentSegment = null
      }
      return
    }

    if (currentSegment && currentSegment.phase === record.phase) {
      currentSegment.endDate = record.date
      currentSegment.count += 1
    } else {
      if (currentSegment) {
        segments.push(currentSegment)
      }

      currentSegment = {
        phase: record.phase,
        startDate: record.date,
        endDate: record.date,
        count: 1,
      }
    }
  })

  if (currentSegment) {
    segments.push(currentSegment)
  }

  return segments
}, [visiblePhaseProgressionData])


const timelineDateMarkers = useMemo(() => {
  const records = visiblePhaseProgressionData

  if (records.length === 0) return []

  const lastIndex = records.length - 1

  const positions = [
    0,
    Math.floor(lastIndex * 0.25),
    Math.floor(lastIndex * 0.5),
    Math.floor(lastIndex * 0.75),
    lastIndex,
  ]

  return [...new Set(positions)].map(
    (index) => records[index].date
  )
}, [visiblePhaseProgressionData])


const phasePriceDomain = useMemo(() => {
  if (visiblePhaseProgressionData.length === 0) return [0, 1]

  let min = Infinity
  let max = -Infinity

  visiblePhaseProgressionData.forEach((record) => {
    min = Math.min(min, record.close)
    max = Math.max(max, record.close)
  })

  const padding =
    (max - min) * 0.05 || Math.max(Math.abs(max) * 0.005, 1)

  return [min - padding, max + padding]
}, [visiblePhaseProgressionData])


const phaseSegments = useMemo(() => {
  if (phaseProgressionData.length === 0) return []

  const segments = []
  let currentSegment = null

  phaseProgressionData.forEach((record) => {
    if (!PHASES.includes(record.phase)) {
      if (currentSegment) {
        segments.push(currentSegment)
        currentSegment = null
      }
      return
    }

    if (
      currentSegment &&
      currentSegment.phase === record.phase
    ) {
      currentSegment.endDate = record.date
    } else {
      if (currentSegment) {
        segments.push(currentSegment)
      }

      currentSegment = {
        phase: record.phase,
        startDate: record.date,
        endDate: record.date,
      }
    }
  })

  if (currentSegment) {
    segments.push(currentSegment)
  }

  return segments
}, [phaseProgressionData])


  const transitionSummary = useMemo(() => {
  const total = filteredTransitions.length

  const bullishReversals = filteredTransitions.filter(
    (item) => item.transitionType === 'Bullish Reversal'
  ).length

  const bearishReversals = filteredTransitions.filter(
    (item) => item.transitionType === 'Bearish Reversal'
  ).length

  const uncertainTransitions = filteredTransitions.filter(
    (item) => item.transitionType === 'Uncertain Transition'
  ).length

  const confirmedPhaseChanges = filteredTransitions.filter(
    (item) =>
      item.previousPhase !== 'TRANSITION_UNCERTAIN' &&
      item.currentPhase !== 'TRANSITION_UNCERTAIN'
  ).length

  const uniqueIndices = new Set(
    filteredTransitions.map((item) => item.indexCode)
  ).size

  return {
    total,
    bullishReversals,
    bearishReversals,
    uncertainTransitions,
    confirmedPhaseChanges,
    uniqueIndices,
  }
}, [filteredTransitions])

  const transitionTypeOptions = useMemo(
    () => [...new Set(transitions.map((item) => item.transitionType))].sort(),
    [transitions]
  )

  useEffect(() => {
    setCurrentPage(1)
  }, [
    selectedIndex,
    selectedTimeframe,
    selectedTransitionType,
    selectedPhase,
  ])

  const totalPages = Math.max(
    1,
    Math.ceil(filteredTransitions.length / PAGE_SIZE)
  )

  const pageTransitions = filteredTransitions.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  )

  const matrixStats = useMemo(() => {
    const counts = Object.fromEntries(
      PHASES.map((fromPhase) => [
        fromPhase,
        Object.fromEntries(PHASES.map((toPhase) => [toPhase, 0])),
      ])
    )

    filteredTransitions.forEach((transition) => {
      counts[transition.previousPhase][transition.currentPhase] += 1
    })

    return counts
  }, [filteredTransitions])

  const frequencyStats = useMemo(
    () =>
      PHASES.map((phase) => ({
        phase,
        outgoing: filteredTransitions.filter(
          (item) => item.previousPhase === phase
        ).length,
        incoming: filteredTransitions.filter(
          (item) => item.currentPhase === phase
        ).length,
      })),
    [filteredTransitions]
  )

    if (loading) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-[#111827]">
        <div className="flex items-center gap-3">
          <RefreshCw size={18} className="animate-spin text-primary" />
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Loading historical phase transitions across all indices and timeframes...
          </p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-5">
        <p className="text-sm font-medium text-rose-400">
          Unable to load phase transitions
        </p>
        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          {error}
        </p>
      </div>
    )
  }

    return (
    <div className="space-y-6">

      {/* Transition Filters */}
      <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-950">
        <div className="mb-4">
          <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
            Filter Transitions
          </h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Narrow historical changes using the following filters.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <select
            value={selectedIndex}
            onChange={(event) => setSelectedIndex(event.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <option value="ALL">All Indices</option>
            {indices.map((index) => (
              <option key={index.code} value={index.code}>
                {index.name ?? index.display_name ?? index.code}
              </option>
            ))}
          </select>

          <select
            value={selectedTimeframe}
            onChange={(event) => setSelectedTimeframe(event.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <option value="ALL">All Timeframes</option>
            {TIMEFRAMES.map((timeframe) => (
              <option key={timeframe.id} value={timeframe.id}>
                {timeframe.label}
              </option>
            ))}
          </select>

          <select
            value={selectedTransitionType}
            onChange={(event) => setSelectedTransitionType(event.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <option value="ALL">All Transition Types</option>
            {transitionTypeOptions.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>

          <select
            value={selectedPhase}
            onChange={(event) => setSelectedPhase(event.target.value)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200"
          >
            <option value="ALL">All Phases</option>
            {PHASES.map((phase) => (
              <option key={phase} value={phase}>
                {formatPhaseName(phase)}
              </option>
            ))}
          </select>
        </div>
      </section>


      {/* Market Phase Progression Chart */}
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        
      <div className="mb-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
            Market Phase Progression
          </h2>

          <div className="flex flex-wrap gap-2">
            {CHART_RANGES.map((range) => (
              <button
                key={range.id}
                type="button"
                onClick={() => setChartRange(range.id)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  chartRange === range.id
                    ? 'bg-primary text-white'
                    : 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800'
                }`}
              >
                {range.label}
              </button>
            ))}
          </div>
        </div>

        <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
          Historical closing-price movement with coloured market-phase regions.
        </p>
      </div>


        {visiblePhaseProgressionData.length > 0 ? (
        <>
          <div className="h-[380px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                  accessibilityLayer={false}
                  data={visiblePhaseProgressionData}
                  margin={{ top: 10, right: 20, bottom: 10, left: 10 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="currentColor"
                  opacity={0.12}
                />

                <XAxis
                  dataKey="date"
                  tickFormatter={(value) => String(value).slice(0, 7)}
                  tick={{ fontSize: 11 }}
                  minTickGap={40}
                  stroke="currentColor"
                  opacity={0.65}
                />

                <YAxis
                  dataKey="close"
                  domain={phasePriceDomain}
                  tick={{ fontSize: 11 }}
                  tickFormatter={(value) =>
                    Number(value).toLocaleString('en-IN')
                  }
                  stroke="currentColor"
                  opacity={0.65}
                  width={85}
                />


              <Tooltip
                cursor={false}
                content={() => null}
              />

                
              <Line
                type="monotone"
                dataKey="close"
                name="Closing Price"
                stroke="#38bdf8"
                strokeWidth={2}
                dot={(props) => {
                  const { cx, cy, payload } = props

                  const transition = visibleChartTransitions.find(
                    (item) => item.date === payload?.date
                  )

                  if (
                    !transition ||
                    !Number.isFinite(cx) ||
                    !Number.isFinite(cy)
                  ) {
                    return null
                  }

                  return (
                      <circle
                        data-transition-marker="true"
                        cx={cx}
                        cy={cy}
                        r={9}
                        fill={
                          PHASE_CHART_COLORS[transition.currentPhase] ??
                          '#f8fafc'
                        }
                        stroke="#0f172a"
                        strokeWidth={1.5}
                        style={{ cursor: 'pointer' }}
                        pointerEvents="all"
                        onClick={() => {
                          setSelectedChartTransition(transition)
                        }}
                      />
                    )
                }}
                activeDot={false}
                connectNulls={false}
                isAnimationActive={false}
              />


              </ComposedChart>
            </ResponsiveContainer>
            </div>

              {selectedChartTransition && (
                <div
                  key={selectedChartTransition.date}
                  className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-900"
                >
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      Selected Phase Transition
                    </h3>

                    <button
                      type="button"
                      onClick={() => setSelectedChartTransition(null)}
                      className="rounded-md px-2 py-1 text-xs text-slate-500 hover:bg-slate-200 dark:text-slate-400 dark:hover:bg-slate-800"
                    >
                      Clear
                    </button>
                  </div>

                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
                    <div>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Transition Date
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-900 dark:text-slate-100">
                        {selectedChartTransition.date}
                      </p>
                    </div>

                     {/* Index Name */}
                    <div>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Index Name
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-900 dark:text-slate-100">
                        {selectedChartTransition.indexName ?? 'N/A'}
                      </p>
                    </div>

                    <div>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Previous Phase
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-900 dark:text-slate-100">
                        {selectedChartTransition.previousPhase?.replaceAll('_', ' ')}
                      </p>
                    </div>

                    <div>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        New Phase
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-900 dark:text-slate-100">
                        {selectedChartTransition.currentPhase?.replaceAll('_', ' ')}
                      </p>
                    </div>

                    <div>
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        Rule Score
                      </p>
                      <p className="mt-1 text-sm font-medium text-slate-900 dark:text-slate-100">
                        {selectedChartTransition.ruleScore ?? 'N/A'}
                      </p>
                    </div>
                  </div>

                  <div className="mt-3 border-t border-slate-200 pt-3 dark:border-slate-700">
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      Closing Price at Transition
                    </p>
                    <p className="mt-1 text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {Number(selectedChartTransition.close).toLocaleString('en-IN', {
                        maximumFractionDigits: 2,
                      })}
                    </p>
                  </div>
                  </div>
              )}
          </>
        ) : (
          <div className="flex h-[300px] items-center justify-center rounded-lg border border-dashed border-slate-300 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
            {loading
              ? 'Loading market phase progression...'
              : 'No matching historical price and phase data available.'}
          </div>
        )}

        <div className="mt-6 border-t border-slate-200 pt-5 dark:border-slate-800">
          <h3 className="mb-2 text-base font-semibold text-slate-900 dark:text-slate-100">
            Market Phase Timeline
          </h3>

          <p className="mb-4 text-sm text-slate-500 dark:text-slate-400">
            Historical phase progression across the selected date range.
          </p>

          {visiblePhaseSegments.length > 0 ? (
            <div className="flex h-12 w-full overflow-hidden rounded-lg bg-slate-100 dark:bg-slate-800">
              {visiblePhaseSegments.map((segment, index) => (
                <div
                  key={`${segment.phase}-${segment.startDate}-${index}`}
                  title={`${segment.phase.replaceAll('_', ' ')} | ${segment.startDate} to ${segment.endDate} | ${segment.count} candles`}
                  className="h-full min-w-0 transition-opacity hover:opacity-80"
                  style={{
                    width: `${(segment.count / visiblePhaseProgressionData.length) * 100}%`,
                    backgroundColor: PHASE_CHART_COLORS[segment.phase],
                  }}
                />
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-slate-300 p-5 text-center text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
              No market phase timeline data available.
            </div>
          )}
            {visiblePhaseSegments.length > 0 && (
              <div className="mt-2 flex justify-between gap-2">
                {timelineDateMarkers.map((date) => (
                  <span
                    key={date}
                    className="text-xs text-slate-500 dark:text-slate-400"
                  >
                    {new Date(`${date}T00:00:00`).toLocaleDateString('en-IN', {
                      month: 'short',
                      year: '2-digit',
                    })}
                  </span>
                ))}
              </div>
            )}
        </div>


        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-3">
          {PHASES.map((phase) => (
            <div key={phase} className="flex items-center gap-2">
              <span
                className="h-3 w-3 rounded-sm"
                style={{
                  backgroundColor: PHASE_CHART_COLORS[phase],
                }}
              />
              <span className="text-xs text-slate-600 dark:text-slate-400">
                {phase.replaceAll('_', ' ')}
              </span>
            </div>
          ))}
        </div>


      </section>
      
      
      {/* Transition Summary */}
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950">
        <div className="mb-4">
            <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Historical Transition Summary
                </h2>

                <InfoButton
                label="Historical Transition Summary"
                onClick={() => setShowRecordsInfo(!showRecordsInfo)}
                />
            </div>

            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                Overview of detected market phase changes across indices and timeframes.
            </p>
            </div>

            {showRecordsInfo && (
            <InfoPopup
                open={showRecordsInfo}
                title="Historical Transition Summary"
                onClose={() => setShowRecordsInfo(false)}
            >
                <p>
                Counts represent detected changes between consecutive valid
                market-phase classifications. They are historical observations,
                not predictions or probabilities of future market direction.
                </p>
            </InfoPopup>
            )}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {[
                    {
                    label: 'Total Transitions',
                    value: transitionSummary.total,
                    color: 'text-slate-900 dark:text-slate-100',
                    },
                    {
                    label: 'Confirmed Phase Changes',
                    value: transitionSummary.confirmedPhaseChanges,
                    color: 'text-primary',
                    },
                    {
                    label: 'Bullish Reversals',
                    value: transitionSummary.bullishReversals,
                    color: 'text-emerald-600 dark:text-emerald-400',
                    },
                    {
                    label: 'Bearish Reversals',
                    value: transitionSummary.bearishReversals,
                    color: 'text-rose-600 dark:text-rose-400',
                    },
                    {
                    label: 'Uncertain Transitions',
                    value: transitionSummary.uncertainTransitions,
                    color: 'text-amber-600 dark:text-amber-400',
                    },
                    {
                    label: 'Indices with Changes',
                    value: transitionSummary.uniqueIndices,
                    color: 'text-primary',
                    },
                ].map((item) => (
                    <div
                    key={item.label}
                    className="rounded-lg bg-slate-50 p-4 dark:bg-slate-900"
                    >
                    <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
                        {item.label}
                    </p>
                    <p className={`mt-2 text-2xl font-semibold ${item.color}`}>
                        {item.value.toLocaleString('en-IN')}
                    </p>
                    </div>
                ))}
            </div>
      </section>


      {/* Transition Timeline */}
      <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-950">
        <div className="mb-4">
            <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Phase Transition Timeline
                </h2>

                <InfoButton
                label="Phase Transition Timeline"
                onClick={() => setShowTimelineInfo(!showTimelineInfo)}
                />
            </div>

            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                Chronological record of historical market-phase changes.
            </p>
            </div>

            {showTimelineInfo && (
            <InfoPopup
                open={showTimelineInfo}
                title="Phase Transition Timeline"
                onClose={() => setShowTimelineInfo(false)}
            >
                <p>
                Each row represents a change between two consecutive valid
                classifications for an index and timeframe. Dates refer to the
                period start of the new classification. Records are sorted
                newest first.
                </p>
            </InfoPopup>
            )}
        {pageTransitions.length === 0 ? (
          <div className="rounded-lg bg-slate-50 px-4 py-10 text-center dark:bg-slate-900">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              No transitions match the selected filters.
            </p>
          </div>
        ) : (
          <>
            <div className="space-y-3">
              {pageTransitions.map((transition, index) => (
                <div
                  key={`${transition.indexCode}-${transition.timeframe}-${transition.periodStart}-${index}`}
                  className="rounded-lg border border-slate-200 p-4 dark:border-slate-800"
                >
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-slate-900 dark:text-slate-100">
                          {transition.indexName}
                        </span>
                        <span className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                          {transition.timeframeLabel}
                        </span>
                        <span className="text-xs text-slate-500 dark:text-slate-400">
                          {formatDate(transition.date)}
                        </span>
                      </div>

                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <PhaseBadge phase={transition.previousPhase} />

                        <ArrowRight
                            size={16}
                            className="text-slate-400"
                        />
                        <PhaseBadge phase={transition.currentPhase} />

                        {(transition.previousPhase === 'TRANSITION_UNCERTAIN' ||
                            transition.currentPhase === 'TRANSITION_UNCERTAIN') && (
                            <span className="rounded-md bg-amber-100 px-2 py-1 text-xs font-medium text-amber-700 dark:bg-amber-950 dark:text-amber-300">
                            Unconfirmed direction
                            </span>
                        )}
                        </div>
                    </div>

                    <div className="flex flex-col gap-1 lg:items-end">
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        {transition.transitionType}
                      </span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {formatPhaseName(transition.previousPhase)}
                        {' â†’ '}
                        {formatPhaseName(transition.currentPhase)}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-5 flex flex-col gap-3 border-t border-slate-200 pt-4 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Showing {filteredTransitions.length === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1}
                {'â€“'}
                {Math.min(currentPage * PAGE_SIZE, filteredTransitions.length)}
                {' of '}
                {filteredTransitions.length.toLocaleString('en-IN')} transitions
              </p>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                  disabled={currentPage === 1}
                  className="rounded-md border border-slate-300 p-2 text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                  aria-label="Previous page"
                >
                  <ChevronLeft size={16} />
                </button>

                <span className="text-sm text-slate-600 dark:text-slate-300">
                  Page {currentPage} of {totalPages}
                </span>

                <button
                  type="button"
                  onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                  disabled={currentPage >= totalPages}
                  className="rounded-md border border-slate-300 p-2 text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                  aria-label="Next page"
                >
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          </>
        )}
      </section>


      {/* Historical Transition Matrix */}
      <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-950">
        <div className="mb-4">
            <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Historical Transition Matrix
                </h2>

                <InfoButton
                label="Historical Transition Matrix"
                onClick={() => setShowMatrixInfo(!showMatrixInfo)}
                />
            </div>

            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                Count of transitions from each previous phase to the next phase.
            </p>
            </div>

            {showMatrixInfo && (
            <InfoPopup
                open={showMatrixInfo}
                title="Historical Transition Matrix"
                onClose={() => setShowMatrixInfo(false)}
            >
                <p>
                Rows represent the previous market phase and columns represent
                the newly classified phase. Each cell shows the number of
                observed transitions. These are historical counts, not
                transition probabilities or forecasts.
                </p>
            </InfoPopup>
            )}

        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800">
                <th className="px-3 py-3 text-left font-semibold text-slate-600 dark:text-slate-300">
                  Previous Phase â†“ / New Phase â†’
                </th>
                {PHASES.map((phase) => (
                  <th
                    key={phase}
                    className="px-3 py-3 text-center font-semibold text-slate-600 dark:text-slate-300"
                  >
                    {formatPhaseName(phase)}
                  </th>
                ))}
                <th className="px-3 py-3 text-center font-semibold text-slate-600 dark:text-slate-300">
                  Total
                </th>
              </tr>
            </thead>

            <tbody>
              {PHASES.map((fromPhase) => {
                const rowTotal = PHASES.reduce(
                  (sum, toPhase) =>
                    sum + (matrixStats[fromPhase]?.[toPhase] ?? 0),
                  0
                )

                return (
                  <tr
                    key={fromPhase}
                    className="border-b border-slate-100 dark:border-slate-800/70"
                  >
                    <td className="px-3 py-3 font-medium text-slate-800 dark:text-slate-200">
                      {formatPhaseName(fromPhase)}
                    </td>

                    {PHASES.map((toPhase) => {
                      const count = matrixStats[fromPhase]?.[toPhase] ?? 0

                      return (
                        <td
                          key={toPhase}
                          className="px-3 py-3 text-center tabular-nums"
                        >
                          <span
                            className={`inline-flex min-w-9 justify-center rounded-md px-2 py-1 ${
                              count > 0
                                ? 'bg-primary-soft font-semibold text-primary'
                                : 'text-slate-400 dark:text-slate-600'
                            }`}
                          >
                            {count.toLocaleString('en-IN')}
                          </span>
                        </td>
                      )
                    })}

                    <td className="px-3 py-3 text-center font-semibold tabular-nums text-slate-900 dark:text-slate-100">
                      {rowTotal.toLocaleString('en-IN')}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          The matrix reflects the currently selected filters.
        </p>
      </section>


      {/* Transition Frequency */}
      <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-950">
        <div className="mb-4">
            <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Transition Frequency by Phase
                </h2>

                <InfoButton
                label="Transition Frequency by Phase"
                onClick={() => setShowFrequencyInfo(!showFrequencyInfo)}
                />
            </div>

            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                Historical frequency of observed transitions entering and leaving each
                phase, including transitions involving uncertain classifications.
            </p>
        </div>

        {showFrequencyInfo && (
        <InfoPopup
            open={showFrequencyInfo}
            title="Transition Frequency by Phase"
            onClose={() => setShowFrequencyInfo(false)}
        >
            <p>
                Incoming counts show how often a phase was entered. Outgoing
                counts show how often a phase was left. These counts include
                transitions involving TRANSITION_UNCERTAIN and do not establish
                a confirmed market reversal. They do not measure phase strength
                or predict future market direction.
            </p>
        </InfoPopup>
        )}

        <div className="space-y-4">
          {frequencyStats.map((item) => {
            const maxCount = Math.max(
              1,
              ...frequencyStats.flatMap((stat) => [
                stat.incoming,
                stat.outgoing,
              ])
            )

            return (
              <div
                key={item.phase}
                className="rounded-lg bg-slate-50 p-4 dark:bg-slate-900"
              >
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <PhaseBadge phase={item.phase} />

                  <div className="flex gap-4 text-xs text-slate-600 dark:text-slate-400">
                    <span>
                      Incoming:{' '}
                      <strong className="text-emerald-600 dark:text-emerald-400">
                        {item.incoming.toLocaleString('en-IN')}
                      </strong>
                    </span>
                    <span>
                      Outgoing:{' '}
                      <strong className="text-rose-600 dark:text-rose-400">
                        {item.outgoing.toLocaleString('en-IN')}
                      </strong>
                    </span>
                  </div>
                </div>

                <div className="space-y-2">
                  <div>
                    <div className="mb-1 flex justify-between text-xs text-slate-500 dark:text-slate-400">
                      <span>Incoming transitions</span>
                      <span>{item.incoming.toLocaleString('en-IN')}</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                      <div
                        className="h-full rounded-full bg-emerald-500"
                        style={{
                          width: `${(item.incoming / maxCount) * 100}%`,
                        }}
                      />
                    </div>
                  </div>

                  <div>
                    <div className="mb-1 flex justify-between text-xs text-slate-500 dark:text-slate-400">
                      <span>Outgoing transitions</span>
                      <span>{item.outgoing.toLocaleString('en-IN')}</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                      <div
                        className="h-full rounded-full bg-rose-500"
                        style={{
                          width: `${(item.outgoing / maxCount) * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </section>

    </div>
  )
}

