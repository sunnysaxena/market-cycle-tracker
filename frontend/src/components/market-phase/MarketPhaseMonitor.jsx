import { useEffect, useState } from 'react'
import {
  Activity,
  BarChart3,
  FlaskConical,
  History,
  LayoutDashboard,
  Waypoints,
} from 'lucide-react'

import { getMultiTimeframeAnalysis } from '../../api/client'
import PhaseMatrix from './PhaseMatrix'
import PhaseBreadthSummary from './PhaseBreadthSummary'
import PhaseSynchronization from './PhaseSynchronization'
import RecentPhaseChanges from './RecentPhaseChanges'

const tabs = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'history', label: 'History', icon: History },
  { id: 'transitions', label: 'Transitions', icon: Waypoints },
  { id: 'strength', label: 'Strength', icon: Activity },
  { id: 'research', label: 'Research Lab', icon: FlaskConical },
]

const tabDescriptions = {
  overview: 'Monitor current market phases across all five indices and four timeframes.',
  history: 'Explore historical phase distribution, phase duration and market history.',
  transitions: 'Track historical phase changes and transition patterns.',
  strength: 'Study classification scores, evidence and relative index leadership.',
  research: 'Investigate forward returns, market regimes and historical strategy performance.',
}

function MarketPhaseMonitor({ indices = [] }) {
  const [activeTab, setActiveTab] = useState('overview')
  const [analysis, setAnalysis] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const indexKey = indices
    .map((index) => index.code)
    .join('|')

  useEffect(() => {
    if (!indexKey) {
      setAnalysis({})
      setLoading(false)
      return
    }

    let cancelled = false

    async function loadPhaseAnalysis() {
      setLoading(true)
      setError(null)

      try {
        const codes = indexKey.split('|')

        const results = await Promise.all(
          codes.map(async (code) => {
            const response = await getMultiTimeframeAnalysis(code)
            return [code, response]
          })
        )

        if (!cancelled) {
          setAnalysis(Object.fromEntries(results))
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message || 'Unable to load market phase data.')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadPhaseAnalysis()

    return () => {
      cancelled = true
    }
  }, [indexKey])

  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold">Market Phase Monitor</h2>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Comprehensive market-cycle monitoring across Indian indices
            </p>
          </div>

          <div className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">
            Classification Engine V1.1
          </div>
        </div>
      </div>

      <div className="flex gap-2 overflow-x-auto border-b border-slate-200 pb-2 dark:border-slate-800">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setActiveTab(id)}
            aria-pressed={activeTab === id}
            className={`flex shrink-0 items-center gap-2 rounded-lg px-4 py-3 text-sm font-medium transition ${
              activeTab === id
                ? 'bg-blue-600 text-white'
                : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
            }`}
          >
            <Icon size={17} />
            {label}
          </button>
        ))}
      </div>

      <div>
        <div className="mb-5">
          <h3 className="text-lg font-semibold">
            {tabs.find((tab) => tab.id === activeTab)?.label}
          </h3>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {tabDescriptions[activeTab]}
          </p>
        </div>

        {activeTab === 'overview' ? (
  loading ? (
        <PhaseMatrix
        indices={indices}
        analysis={analysis}
        loading={loading}
        error={error}
        />
    ) : (
        <div className="space-y-6">
            <PhaseBreadthSummary
                indices={indices}
                analysis={analysis}
            />

            <PhaseSynchronization
                indices={indices}
                analysis={analysis}
            />

            <PhaseMatrix
                indices={indices}
                analysis={analysis}
                loading={loading}
                error={error}
            />

            <RecentPhaseChanges indices={indices} />
        </div>
    )
    ) : (
        <div className="min-h-72 rounded-xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-[#111827]">
            <div className="flex min-h-60 flex-col items-center justify-center text-center">
            <BarChart3
                size={36}
                className="mb-4 text-slate-400"
            />
            <h4 className="font-semibold">
                {tabs.find((tab) => tab.id === activeTab)?.label} Analytics
            </h4>
            <p className="mt-2 max-w-lg text-sm text-slate-500 dark:text-slate-400">
                This section will be connected to the verified historical market-cycle
                data in the next implementation stages.
            </p>
            </div>
        </div>
        )}
      </div>
    </div>
  )
}

export default MarketPhaseMonitor
