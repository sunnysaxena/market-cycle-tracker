import { lazy, Suspense, useEffect, useMemo, useState } from 'react'
import {
  Activity, BarChart3, CandlestickChart, Clock,
  Database, LayoutDashboard, Menu, Moon, Settings,
  Sun, TrendingDown, TrendingUp, Users
} from 'lucide-react'

import {
  getIndices,
  getMarketHistory,
  getMultiTimeframeAnalysis,
} from './api/client'

const MultiTimeframePage = lazy(
  () => import('./components/MultiTimeframePage')
)

const navigation = [
  { name: 'Overview Dashboard', icon: LayoutDashboard },
  { name: 'Index Analysis', icon: CandlestickChart },
  { name: 'Multi-Timeframe Analysis', icon: BarChart3 },
  { name: 'Cycle History', icon: Clock },
  { name: 'Technical Analysis', icon: Activity },
  { name: 'FII / DII Activity', icon: Users },
  { name: 'Data Management', icon: Database },
  { name: 'Settings', icon: Settings },
]

const phases = [
  { name: 'ACCUMULATION', color: 'bg-blue-500' },
  { name: 'MARKUP', color: 'bg-green-500' },
  { name: 'DISTRIBUTION', color: 'bg-orange-500' },
  { name: 'MARKDOWN', color: 'bg-red-500' },
  { name: 'SIDEWAYS_CONSOLIDATION', color: 'bg-yellow-500' },
  { name: 'TRANSITION_UNCERTAIN', color: 'bg-purple-500' },
  { name: 'INSUFFICIENT_DATA', color: 'bg-slate-500' },
]

const timeframeLabels = {
  '1D': 'Daily',
  '1W': 'Weekly',
  '1M': 'Monthly',
  '1Y': 'Yearly',
}

function formatPrice(value) {
  if (value === null || value === undefined) return '—'

  return new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(Number(value))
}

function formatDate(value) {
  if (!value) return '—'

  return new Date(`${value}T00:00:00`).toLocaleDateString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

function formatLabel(value) {
  if (!value) return 'Unavailable'

  return value
    .toLowerCase()
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

function App() {
  const [dark, setDark] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [activePage, setActivePage] = useState('Overview Dashboard')

  const [indices, setIndices] = useState([])
  const [selectedInstrument, setSelectedInstrument] = useState('')
  const [analysis, setAnalysis] = useState({})
  const [loadingIndices, setLoadingIndices] = useState(true)
  const [loadingAnalysis, setLoadingAnalysis] = useState(false)
  const [apiError, setApiError] = useState('')
  const [indiaVixData, setIndiaVixData] = useState({
    loading: false,
    records: [],
    error: '',
  })

  const marketIndices = useMemo(
    () => indices.filter((item) => item.category === 'market_index'),
    [indices],
  )

  const volatilityIndices = useMemo(
    () => indices.filter((item) => item.category === 'volatility_index'),
    [indices],
  )

  const selectedIndex = indices.find(
    (item) => item.code === selectedInstrument,
  )

  const selectedAnalysis = analysis[selectedInstrument]

  useEffect(() => {
    let cancelled = false

    async function loadIndices() {
      try {
        setLoadingIndices(true)
        setApiError('')

        const result = await getIndices()

        if (cancelled) return

        setIndices(result)

        const firstMarketIndex = result.find(
          (item) => item.category === 'market_index',
        )

        setSelectedInstrument((current) => (
          current || firstMarketIndex?.code || ''
        ))
      } catch (error) {
        if (!cancelled) {
          setApiError(error.message || 'Unable to load instrument registry.')
        }
      } finally {
        if (!cancelled) {
          setLoadingIndices(false)
        }
      }
    }

    loadIndices()

    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (marketIndices.length === 0) return

    let cancelled = false

    async function loadMarketAnalysis() {
      setLoadingAnalysis(true)

      const results = await Promise.allSettled(
        marketIndices.map((item) => getMultiTimeframeAnalysis(item.code)),
      )

      if (cancelled) return

      const updatedAnalysis = {}

      results.forEach((result, index) => {
        const code = marketIndices[index].code

        if (result.status === 'fulfilled') {
          updatedAnalysis[code] = result.value
        } else {
          updatedAnalysis[code] = {
            error: result.reason?.message || 'Unable to load market analysis.',
          }
        }
      })

      setAnalysis((current) => ({
        ...current,
        ...updatedAnalysis,
      }))

      setLoadingAnalysis(false)
    }

    loadMarketAnalysis()

    return () => {
      cancelled = true
    }
  }, [marketIndices])


    useEffect(() => {
    const indiaVix = volatilityIndices.find(
      (item) => item.code === 'INDIA_VIX',
    )

    if (!indiaVix) return

    let cancelled = false

    async function loadIndiaVix() {
      setIndiaVixData({
        loading: true,
        records: [],
        error: '',
      })

      try {
        const result = await getMarketHistory('INDIA_VIX', {
          timeframe: '1D',
          importBatchId: 5,
          limit: 2,
          sortOrder: 'desc',
        })

        if (cancelled) return

        setIndiaVixData({
          loading: false,
          records: result.records || [],
          error: '',
        })
      } catch (error) {
        if (!cancelled) {
          setIndiaVixData({
            loading: false,
            records: [],
            error: error.message || 'Unable to load India VIX data.',
          })
        }
      }
    }

    loadIndiaVix()

    return () => {
      cancelled = true
    }
  }, [volatilityIndices])

  const phaseCounts = useMemo(() => {
    const counts = Object.fromEntries(
      phases.map((phase) => [phase.name, 0]),
    )

    marketIndices.forEach((item) => {
      const classification =
        analysis[item.code]?.timeframes?.['1D']?.cycle?.cycle_classification

      if (classification && classification in counts) {
        counts[classification] += 1
      }
    })

    return counts
  }, [marketIndices, analysis])

  const timeframeData = selectedAnalysis?.timeframes

  const systemStatus = apiError
    ? 'Connection error'
    : loadingIndices || loadingAnalysis
      ? 'Loading market data'
      : indices.length > 0
        ? 'API connected'
        : 'Awaiting data'

  return (
    <div className={dark ? 'dark' : ''}>
      <div className="min-h-screen bg-slate-100 text-slate-900 dark:bg-[#0b1120] dark:text-slate-100">
        <div className="flex min-h-screen">

          {sidebarOpen && (
                <button
                  type="button"
                  aria-label="Close sidebar"
                  onClick={() => setSidebarOpen(false)}
                  className="fixed inset-0 z-30 bg-black/50 lg:hidden"
                />
              )}

              <aside
                className={`fixed inset-y-0 left-0 z-40 w-64 overflow-y-auto border-r border-slate-200 bg-white p-5 transition-transform duration-300 ease-in-out dark:border-slate-800 dark:bg-[#111827]
                  ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
                  lg:sticky lg:top-0 lg:h-screen lg:shrink-0 lg:translate-x-0
                  lg:transition-none
                  ${sidebarOpen ? 'lg:w-64' : 'lg:w-0 lg:overflow-hidden lg:border-r-0 lg:p-0'}
                `}
              >
              <div className="mb-10">
                <div className="flex items-center gap-3">
                  <div className="rounded-xl bg-blue-600 p-2 text-white">
                    <Activity size={23} />
                  </div>
                  <div>
                    <h1 className="text-lg font-bold">Market Cycle</h1>
                    <p className="text-xs text-slate-500">Tracker V1.2</p>
                  </div>
                </div>
              </div>

              <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                Main Menu
              </p>

              <nav className="space-y-1">
                {navigation.map(({ name, icon: Icon }) => (
                  <button
                    key={name}
                    onClick={() => {
                      setActivePage(name)

                      if (window.innerWidth < 1024) {
                        setSidebarOpen(false)
                      }
                    }}
                    className={`flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left text-sm transition ${
                      activePage === name
                        ? 'bg-blue-600 text-white'
                        : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                    }`}
                  >
                    <Icon size={18} />
                    {name}
                  </button>
                ))}
              </nav>

              <div className="mt-10 rounded-xl border border-slate-200 p-3 dark:border-slate-700">
                <p className="text-xs text-slate-500">System Status</p>
                <p className="mt-2 flex items-center gap-2 text-sm font-medium">
                  <span className={`h-2 w-2 rounded-full ${
                    apiError ? 'bg-red-500' :
                    loadingIndices || loadingAnalysis ? 'bg-yellow-500' :
                    'bg-green-500'
                  }`} />
                  {systemStatus}
                </p>
              </div>
            </aside>

          <main className="min-w-0 flex-1">
            <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-6 dark:border-slate-800 dark:bg-[#111827]">
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setSidebarOpen((open) => !open)}
                  className="rounded-lg border border-slate-200 p-2 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
                  aria-label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
                  title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
                >
                  <Menu size={20} />
                </button>

                <div>
                  <h2 className="font-semibold">{activePage}</h2>
                  <p className="text-xs text-slate-500">
                    Indian Market Cycle Analysis
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-4">
                <span className="hidden text-sm text-slate-500 sm:block">
                  Daily analysis
                </span>
                <button
                  onClick={() => setDark(!dark)}
                  className="rounded-lg border border-slate-200 p-2 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
                  aria-label="Toggle theme"
                >
                  {dark ? <Sun size={18} /> : <Moon size={18} />}
                </button>
              </div>
            </header>

            <section className="p-6">
              {activePage === 'Multi-Timeframe Analysis' ? (
                <Suspense
                  fallback={
                    <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500 dark:border-slate-800 dark:bg-[#111827]">
                      Loading Multi-Timeframe Analysis...
                    </div>
                  }
                >
                  <MultiTimeframePage
                    indices={marketIndices}
                    selectedInstrument={selectedInstrument}
                    onSelectInstrument={setSelectedInstrument}
                    analysis={selectedAnalysis?.timeframes ? selectedAnalysis : null}
                    loading={loadingIndices || loadingAnalysis}
                    error={selectedAnalysis?.error || apiError}
                  />
                </Suspense>
              ) : activePage === 'Overview Dashboard' ? (
                <>
              <div className="mb-6">
                <h2 className="text-2xl font-bold">Market Overview</h2>
                <p className="mt-1 text-sm text-slate-500">
                  Daily, weekly, monthly and yearly market-cycle monitoring
                </p>
              </div>

              {apiError && (
                <div className="mb-6 rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                  <strong>API connection error:</strong> {apiError}
                  <p className="mt-1">
                    Check that the FastAPI server is running on port 8000.
                  </p>
                </div>
              )}

              <div className="mb-3 flex items-center justify-between">
                <h3 className="font-semibold">Market Indices</h3>
                <span className="text-xs text-slate-500">
                  {marketIndices.length} registered indices
                </span>
              </div>

              <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {loadingIndices && (
                  <p className="text-sm text-slate-500">
                    Loading instrument registry...
                  </p>
                )}

                {marketIndices.map((item) => {
                  const daily = analysis[item.code]?.timeframes?.['1D']
                  const classification = daily?.cycle?.cycle_classification
                  const isSelected = selectedInstrument === item.code

                  return (
                    <button
                      key={item.code}
                      onClick={() => setSelectedInstrument(item.code)}
                      className={`rounded-xl border p-5 text-left transition ${
                        isSelected
                          ? 'border-blue-500 ring-1 ring-blue-500'
                          : 'border-slate-200 dark:border-slate-800'
                      } bg-white hover:border-blue-400 dark:bg-[#111827]`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-sm font-medium text-slate-500">
                          {item.name}
                        </p>
                        {isSelected && (
                          <span className="rounded-md bg-blue-100 px-2 py-1 text-xs text-blue-700 dark:bg-blue-950 dark:text-blue-300">
                            Selected
                          </span>
                        )}
                      </div>

                      <p className="mt-4 text-2xl font-semibold">
                        {daily?.market_data
                          ? formatPrice(daily.market_data.close)
                          : analysis[item.code]?.error
                            ? 'Unavailable'
                            : loadingAnalysis
                              ? 'Loading...'
                              : '—'}
                      </p>

                      <p className="mt-1 text-xs text-slate-400">
                        Latest eligible daily close
                      </p>

                      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
                        <span className="text-xs font-medium text-slate-500">
                          {classification
                            ? formatLabel(classification)
                            : analysis[item.code]?.error
                              ? 'Analysis unavailable'
                              : 'Cycle data unavailable'}
                        </span>

                        <span className={`rounded-full px-2 py-1 text-xs ${
                          daily?.availability?.status === 'available'
                            ? 'bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-300'
                            : daily?.availability?.status === 'partial'
                              ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-950 dark:text-yellow-300'
                              : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
                        }`}>
                          {daily?.availability?.status || 'No data'}
                        </span>
                      </div>

                      <p className="mt-3 text-xs text-slate-400">
                        {daily?.period?.period_end
                          ? `As of ${formatDate(daily.period.period_end)}`
                          : item.code}
                      </p>
                    </button>
                  )
                })}
              </div>



              {volatilityIndices.length > 0 && (
                <section className="mb-6">
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="font-semibold">Market Volatility</h3>
                  </div>

                  <div className="space-y-3">
                    {volatilityIndices.map((item) => {
                      const records =
                        item.code === 'INDIA_VIX' ? indiaVixData.records : []

                      const latest = records[0]
                      const previous = records[1]

                      const latestClose =
                        latest?.close != null ? Number(latest.close) : null

                      const previousClose =
                        previous?.close != null ? Number(previous.close) : null

                      const change =
                        latestClose !== null && previousClose !== null
                          ? latestClose - previousClose
                          : null

                      const changePercent =
                        change !== null && previousClose !== 0
                          ? (change / previousClose) * 100
                          : null

                      const changeColor =
                        change === null
                          ? 'text-slate-500'
                          : change > 0
                            ? 'text-red-600 dark:text-red-400'
                            : change < 0
                              ? 'text-green-600 dark:text-green-400'
                              : 'text-slate-500'

                      const vixRisk =
                        latestClose === null
                          ? { label: 'Unavailable', color: 'text-slate-500' }
                          : latestClose < 12
                            ? { label: 'Low Risk', color: 'text-green-600 dark:text-green-400' }
                            : latestClose < 15
                              ? { label: 'Neutral Risk', color: 'text-green-600 dark:text-green-400' }
                              : latestClose < 20
                                ? { label: 'Choppy', color: 'text-yellow-600 dark:text-yellow-400' }
                                : latestClose < 25
                                  ? { label: 'High Risk', color: 'text-orange-600 dark:text-orange-400' }
                                  : { label: 'Extreme Risk', color: 'text-red-600 dark:text-red-400' }

                      const gaugeValue =
                        latestClose === null
                          ? 0
                          : Math.min(Math.max(latestClose, 0), 40)

                      const gaugeAngle = Math.PI - (gaugeValue / 40) * Math.PI

                      const needleX = 160 + 92 * Math.cos(gaugeAngle)
                      const needleY = 130 - 92 * Math.sin(gaugeAngle)

                      const structureState = String(
                        timeframeData?.['1D']?.structure?.market_structure_state || '',
                      ).toLowerCase()

                      const cycleState = String(
                        timeframeData?.['1D']?.cycle?.cycle_classification || '',
                      ).toLowerCase()

                      const marketCondition =
                        (structureState.includes('bullish') ||
                          structureState.includes('uptrend')) &&
                        cycleState.includes('markup')
                          ? {
                              label: 'Risk-On',
                              color: 'text-green-600 dark:text-green-400',
                              badge: 'bg-green-100 text-green-700 dark:bg-green-900/60 dark:text-green-300',
                            }
                          : (structureState.includes('bearish') ||
                              structureState.includes('downtrend')) &&
                            cycleState.includes('markdown')
                            ? {
                                label: 'Risk-Off',
                                color: 'text-red-600 dark:text-red-400',
                                badge: 'bg-red-100 text-red-700 dark:bg-red-900/60 dark:text-red-300',
                              }
                            : {
                                label: 'Transition / Unconfirmed',
                                color: 'text-yellow-600 dark:text-yellow-400',
                                badge: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/60 dark:text-yellow-300',
                              }

                      return (
                        <div
                          key={item.code}
                          className="rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-400 dark:border-slate-800 dark:bg-[#111827] sm:p-5"
                        >
                          {item.code === 'INDIA_VIX' && indiaVixData.loading ? (
                            <p className="text-sm text-slate-500">
                              Loading India VIX data...
                            </p>
                          ) : item.code === 'INDIA_VIX' && indiaVixData.error ? (
                            <p className="break-words text-sm text-red-500">
                              {indiaVixData.error}
                            </p>
                          ) : latest ? (
                            <>
                              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                                {/* Instrument identity */}
                                <div className="flex min-w-0 items-center gap-3 sm:flex-1">
                                  <div className="min-w-0">
                                    <p className="text-sm font-semibold">
                                      {item.name}
                                    </p>
                                    <p className="mt-1 text-xs text-slate-400">
                                      Market-wide volatility reference
                                    </p>
                                  </div>

                                  <span className="shrink-0 rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                                    NSE
                                  </span>
                                </div>

                                {/* Latest VIX value */}
                                <div className="sm:flex-1">
                                  <p className="text-xs text-slate-400">
                                    Latest daily close
                                  </p>
                                  <p className="mt-1 text-2xl font-semibold tabular-nums">
                                    {formatPrice(latestClose)}
                                  </p>
                                </div>

                                {/* Daily change */}
                                <div className="sm:flex-1 sm:text-right">
                                  <p className="text-xs text-slate-400">
                                    Daily change
                                  </p>
                                  <p className={`mt-1 text-lg font-semibold tabular-nums ${changeColor}`}>
                                    {change !== null
                                      ? `${change > 0 ? '+' : ''}${formatPrice(change)}`
                                      : '—'}
                                  </p>
                                  <p className={`text-xs font-medium ${changeColor}`}>
                                    {changePercent !== null
                                      ? `${changePercent > 0 ? '+' : ''}${changePercent.toFixed(2)}%`
                                      : 'Change unavailable'}
                                  </p>
                                </div>
                              </div>

                              {/* India VIX graphical gauge */}
                              <div className="mt-6 grid gap-6 border-t border-slate-100 pt-5 dark:border-slate-800 lg:grid-cols-2">

                                {/* Semicircular speedometer */}
                                <div className="min-w-0">
                                  <p className="text-sm font-semibold">
                                    Volatility Risk
                                  </p>

                                  <div className="mx-auto mt-3 w-full max-w-sm">
                                    <svg
                                      viewBox="0 0 320 175"
                                      className="h-auto w-full overflow-visible text-slate-900 dark:text-slate-100"
                                      role="img"
                                      aria-label={`India VIX ${formatPrice(latestClose)}, ${vixRisk.label}`}
                                    >
                                      {/* Low */}
                                      <path
                                        d="M 40 130 A 120 120 0 0 1 89.5 32.9"
                                        fill="none"
                                        stroke="#16A36A"
                                        strokeWidth="17"
                                      />

                                      {/* Neutral */}
                                      <path
                                        d="M 89.5 32.9 A 120 120 0 0 1 114.1 19.1"
                                        fill="none"
                                        stroke="#84A83D"
                                        strokeWidth="17"
                                      />

                                      {/* Choppy */}
                                      <path
                                        d="M 114.1 19.1 A 120 120 0 0 1 205.9 19.1"
                                        fill="none"
                                        stroke="#E5A12B"
                                        strokeWidth="17"
                                      />

                                      {/* High and Extreme */}
                                      <path
                                        d="M 205.9 19.1 A 120 120 0 0 1 280 130"
                                        fill="none"
                                        stroke="#D94B4B"
                                        strokeWidth="17"
                                      />

                                      {/* Needle */}
                                      {latestClose !== null && (
                                        <>
                                          <line
                                            x1="160"
                                            y1="130"
                                            x2={needleX}
                                            y2={needleY}
                                            stroke="currentColor"
                                            strokeWidth="3.5"
                                            strokeLinecap="round"
                                          />

                                          <circle
                                            cx="160"
                                            cy="130"
                                            r="7"
                                            fill="currentColor"
                                          />
                                        </>
                                      )}

                                      {/* Current value */}
                                      <text
                                        x="160"
                                        y="105"
                                        textAnchor="middle"
                                        fill="currentColor"
                                        fontSize="27"
                                        fontWeight="700"
                                      >
                                        {formatPrice(latestClose)}
                                      </text>

                                      <text
                                        x="160"
                                        y="121"
                                        textAnchor="middle"
                                        fill="currentColor"
                                        fontSize="10"
                                      >
                                        INDIA VIX
                                      </text>

                                      <text
                                        x="31"
                                        y="153"
                                        fill="currentColor"
                                        fontSize="11"
                                      >
                                        0
                                      </text>

                                      <text
                                        x="289"
                                        y="153"
                                        textAnchor="end"
                                        fill="currentColor"
                                        fontSize="11"
                                      >
                                        40+
                                      </text>
                                    </svg>
                                  </div>

                                  <div className="mt-1 text-center">
                                    <span
                                      className={`text-base font-bold ${vixRisk.color}`}
                                    >
                                      {vixRisk.label}
                                    </span>
                                  </div>

                                  <div className="mt-4 grid grid-cols-5 gap-1 text-center">
                                    {[
                                      { label: 'Low', color: 'bg-green-500' },
                                      { label: 'Neutral', color: 'bg-lime-500' },
                                      { label: 'Choppy', color: 'bg-yellow-500' },
                                      { label: 'High', color: 'bg-orange-500' },
                                      { label: 'Extreme', color: 'bg-red-500' },
                                    ].map((zone) => (
                                      <div key={zone.label} className="min-w-0">
                                        <div
                                          className={`mx-auto mb-1 h-2 w-2 rounded-full ${zone.color}`}
                                        />
                                        <span className="text-[10px] text-slate-500">
                                          {zone.label}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </div>

                                {/* Separate market condition */}
                                <div className="flex flex-col justify-center rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-[#111827]">
                                  <p className="text-sm font-semibold">
                                    Market Condition
                                  </p>

                                  <p className="mt-1 text-xs text-slate-500">
                                    Based on daily market structure and cycle classification
                                  </p>

                                  <div className="mt-4">
                                    <span
                                      className={`inline-flex rounded-lg px-3 py-2 text-sm font-semibold ${marketCondition.color} ${marketCondition.badge}`}
                                    >
                                      {marketCondition.label}
                                    </span>
                                  </div>

                                  <div className="mt-4 space-y-2 text-xs text-slate-500">
                                    <p>
                                      Structure:{' '}
                                      <span className="font-medium text-slate-700 dark:text-slate-300">
                                        {formatLabel(
                                          timeframeData?.['1D']?.structure?.market_structure_state,
                                        )}
                                      </span>
                                    </p>

                                    <p>
                                      Cycle:{' '}
                                      <span className="font-medium text-slate-700 dark:text-slate-300">
                                        {formatLabel(
                                          timeframeData?.['1D']?.cycle?.cycle_classification,
                                        )}
                                      </span>
                                    </p>
                                  </div>
                                </div>
                              </div>

                              {/* Expandable details */}
                              <details className="mt-4 border-t border-slate-100 pt-3 dark:border-slate-800">
                                <summary className="cursor-pointer text-xs font-medium text-slate-500 transition hover:text-blue-500">
                                  View additional details
                                </summary>

                                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                                  <div>
                                    <p className="text-xs text-slate-400">
                                      Previous close
                                    </p>
                                    <p className="mt-1 text-sm font-medium tabular-nums">
                                      {previousClose !== null
                                        ? formatPrice(previousClose)
                                        : '—'}
                                    </p>
                                  </div>

                                  <div>
                                    <p className="text-xs text-slate-400">
                                      Latest data date
                                    </p>
                                    <p className="mt-1 text-sm font-medium">
                                      {latest.candle_date
                                        ? formatDate(latest.candle_date)
                                        : '—'}
                                    </p>
                                  </div>

                                  <div>
                                    <p className="text-xs text-slate-400">
                                      Data quality
                                    </p>
                                    <p className="mt-1 text-sm font-medium">
                                      {latest.quality_status === 'accepted'
                                        ? 'Accepted'
                                        : latest.quality_status || 'Unavailable'}
                                    </p>
                                  </div>
                                </div>
                              </details>
                            </>
                          ) : (
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <p className="text-sm font-semibold">{item.name}</p>
                                <p className="mt-1 text-xs text-slate-400">
                                  Volatility reference
                                </p>
                              </div>
                              <span className="text-sm text-slate-500">
                                No data available
                              </span>
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </section>
              )}



              <div className="grid gap-6 xl:grid-cols-3">
                <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827] xl:col-span-2">
                  <h3 className="font-semibold">Market Cycle Distribution</h3>
                  <p className="mt-1 text-sm text-slate-500">
                    Latest daily classification across registered price indices
                  </p>

                  <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {phases.map((phase) => (
                      <div
                        key={phase.name}
                        className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 p-4 dark:bg-slate-800/60"
                      >
                        <div className="flex min-w-0 items-center gap-3">
                          <span className={`h-3 w-3 shrink-0 rounded-full ${phase.color}`} />
                          <span className="text-xs font-medium">
                            {formatLabel(phase.name)}
                          </span>
                        </div>
                        <span className="font-semibold tabular-nums">
                          {phaseCounts[phase.name]}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]">
                  <h3 className="font-semibold">Multi-Timeframe Analysis</h3>
                  <p className="mt-1 text-sm text-slate-500">
                    {selectedIndex?.name || 'Select a market index'}
                  </p>

                  <div className="mt-6 space-y-4">
                    {Object.entries(timeframeLabels).map(([key, label]) => {
                      const snapshot = timeframeData?.[key]

                      return (
                        <div
                          key={key}
                          className="flex items-center justify-between gap-3 border-b border-slate-100 pb-3 dark:border-slate-800"
                        >
                          <div>
                            <p className="text-sm font-medium">{label}</p>
                            <p className="text-xs text-slate-400">
                              {snapshot?.period
                                ? formatDate(snapshot.period.period_end)
                                : 'No eligible record'}
                            </p>
                          </div>

                          <span className={`text-xs font-medium ${
                            snapshot?.availability?.status === 'available'
                              ? 'text-green-600 dark:text-green-400'
                              : snapshot?.availability?.status === 'partial'
                                ? 'text-yellow-600 dark:text-yellow-400'
                                : 'text-slate-400'
                          }`}>
                            {snapshot?.availability?.status || 'No data'}
                          </span>
                        </div>
                      )
                    })}
                  </div>

                  {selectedAnalysis?.batch && (
                    <p className="mt-4 text-xs text-slate-400">
                      Import batch: {selectedAnalysis.batch.import_batch_id}
                    </p>
                  )}

                  {selectedAnalysis?.error && (
                    <p className="mt-4 text-xs text-red-500">
                      {selectedAnalysis.error}
                    </p>
                  )}
                </div>
              </div>

              <div className="mt-6 grid gap-6 lg:grid-cols-2">
                <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]">
                  <div className="flex items-center gap-2">
                    <TrendingUp size={18} className="text-green-500" />
                    <h3 className="font-semibold">Market Intelligence</h3>
                  </div>

                  <div className="mt-4 space-y-3 text-sm">
                    <div className="flex justify-between gap-3">
                      <span className="text-slate-500">Market structure</span>
                      <span className="font-medium">
                        {formatLabel(timeframeData?.['1D']?.structure?.market_structure_state)}
                      </span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-slate-500">Cycle classification</span>
                      <span className="font-medium">
                        {formatLabel(timeframeData?.['1D']?.cycle?.cycle_classification)}
                      </span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-slate-500">ADX (14)</span>
                      <span className="font-medium">
                        {formatPrice(timeframeData?.['1D']?.indicators?.trend?.adx_14)}
                      </span>
                    </div>
                    <div className="flex justify-between gap-3">
                      <span className="text-slate-500">RSI (14)</span>
                      <span className="font-medium">
                        {formatPrice(timeframeData?.['1D']?.indicators?.momentum?.rsi_14)}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]">
                  <div className="flex items-center gap-2">
                    <TrendingDown size={18} className="text-orange-500" />
                    <h3 className="font-semibold">Institutional Activity</h3>
                  </div>
                  <p className="mt-3 text-sm text-slate-500">
                    FII and DII cash-market activity will appear here after
                    a verified data source is integrated.
                  </p>
                </div>
              </div>

              <p className="mt-8 text-center text-xs text-slate-500">
                Market Cycle Tracker V1.2 · Local-first application · No live trading
              </p>

                </>
              ) : (
                <div className="rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-[#111827]">
                  <h2 className="text-lg font-semibold">{activePage}</h2>
                  <p className="mt-2 text-sm text-slate-500">
                    This section has not been connected yet.
                  </p>
                </div>
              )}            
            </section>
          </main>
        </div>
      </div>
    </div>
  )
}

export default App

