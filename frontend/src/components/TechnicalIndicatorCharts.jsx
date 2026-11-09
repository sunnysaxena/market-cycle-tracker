import { useMemo, useState } from 'react'
import {
  ResponsiveContainer,
  LineChart,
  ComposedChart,
  Line,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  Legend,
} from 'recharts'

function formatDate(value) {
  if (!value) return ''

  // Keep the year visible on long historical charts.
  return value.length >= 7 ? value.slice(0, 7) : value
}

function formatTooltipDate(value) {
  return value || ''
}

function formatValue(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '—'
  }

  return Number(value).toFixed(2)
}

const axisProps = {
  tick: {
    fill: 'currentColor',
    fontSize: 10,
  },
  axisLine: {
    stroke: 'currentColor',
    opacity: 0.25,
  },
  tickLine: {
    stroke: 'currentColor',
    opacity: 0.25,
  },
  tickMargin: 8,
}

const tooltipStyle = {
  contentStyle: {
    backgroundColor: 'var(--chart-tooltip-bg)',
    border: '1px solid var(--chart-tooltip-border)',
    borderRadius: '10px',
    color: 'var(--chart-tooltip-text)',
    fontSize: '12px',
    padding: '9px 12px',
    boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
  },
  labelStyle: {
    color: 'var(--chart-tooltip-text)',
    fontWeight: 600,
    marginBottom: 5,
  },
  itemStyle: {
    padding: '2px 0',
  },
  formatter: formatValue,
  labelFormatter: formatTooltipDate,
}

const legendStyle = {
  fontSize: 11,
  paddingTop: 8,
}

function IndicatorPanel({ title, subtitle, empty, children }) {
  return (
    <section className="
      min-w-0 overflow-hidden rounded-xl border
      border-slate-200 bg-white p-4 shadow-sm
      transition-colors
      dark:border-slate-700/70 dark:bg-slate-900
    ">
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          {title}
        </h3>

        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {subtitle}
        </p>
      </div>

      {empty ? (
        <div className="
          flex h-[220px] items-center justify-center
          rounded-lg bg-slate-50 text-sm text-slate-500
          dark:bg-slate-800/50 dark:text-slate-400
        ">
          Indicator data unavailable
        </div>
      ) : (
        <div className="h-[220px] w-full text-slate-500 dark:text-slate-400">
          <ResponsiveContainer width="100%" height="100%" minWidth={0}>
            {children}
          </ResponsiveContainer>
        </div>
      )}
    </section>
  )
}

function ChartAxes({ dataKey = 'time' }) {
  return (
    <>
      <CartesianGrid
        stroke="currentColor"
        strokeDasharray="3 3"
        opacity={0.13}
        vertical={false}
      />

      <XAxis
        dataKey={dataKey}
        tickFormatter={formatDate}
        interval="preserveStartEnd"
        tickCount={6}
        minTickGap={45}
        height={32}
        {...axisProps}
      />

      <YAxis
        width={52}
        {...axisProps}
      />

      <Tooltip {...tooltipStyle} />
    </>
  )
}

const MAX_DISPLAY_POINTS = 300

function downsampleData(data, maxPoints = MAX_DISPLAY_POINTS) {
  if (data.length <= maxPoints) return data

  const result = []
  const step = (data.length - 1) / (maxPoints - 1)

  for (let i = 0; i < maxPoints; i++) {
    result.push(data[Math.round(i * step)])
  }

  return result
}

export default function TechnicalIndicatorCharts({
  data = [],
  loading = false,
  visibleLogicalRange = null,
}) {
  const [activeGroup, setActiveGroup] = useState('momentum')
  const visibleData = useMemo(() => {
    if (!visibleLogicalRange || data.length === 0) {
      return data
    }

    const start = Math.max(
      0,
      Math.floor(visibleLogicalRange.from),
    )

    const end = Math.min(
      data.length - 1,
      Math.ceil(visibleLogicalRange.to),
    )

    if (end < start) {
      return data
    }

    return data.slice(start, end + 1)
  }, [data, visibleLogicalRange])

  const displayData = useMemo(
    () => downsampleData(visibleData),
    [visibleData],
  )

  const hasValue = (key) =>
    visibleData.some((item) => Number.isFinite(item[key]))

  if (loading) {
    return (
      <div className="
        mt-6 rounded-xl border border-slate-200
        bg-white p-6 text-center text-sm text-slate-500
        dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400
      ">
        Loading technical indicators...
      </div>
    )
  }

  return (
    <div
      className="
         mt-6 mb-10 space-y-4
        [--chart-tooltip-bg:#ffffff]
        [--chart-tooltip-border:#e2e8f0]
        [--chart-tooltip-text:#0f172a]
        dark:[--chart-tooltip-bg:#0f172a]
        dark:[--chart-tooltip-border:#334155]
        dark:[--chart-tooltip-text:#e2e8f0]
      "
    >
      {/* Section heading */}
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Technical Indicators
        </h2>

        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Historical indicator values aligned with the selected chart timeframe.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
          {[
            { id: 'momentum', label: 'Momentum' },
            { id: 'trend', label: 'Trend' },
            { id: 'volatility', label: 'Volatility' },
            { id: 'condition', label: 'Market Condition' },
          ].map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveGroup(id)}
              aria-pressed={activeGroup === id}
              className={`
                rounded-lg px-4 py-2 text-sm font-medium
                transition-colors
                ${
                  activeGroup === id
                    ? 'bg-sky-600 text-white shadow-sm'
                    : 'bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700'
                }
              `}
            >
              {label}
            </button>
          ))}
      </div>

      
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">

      {/* MOMENTUM: RSI + MACD */}
      {activeGroup === 'momentum' && (
        <>
          <IndicatorPanel
            title="RSI (14)"
            subtitle="Momentum · Reference levels 30 and 70"
            empty={!hasValue('rsi14')}
          >
            <LineChart data={displayData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <ChartAxes />
              <YAxis domain={[0, 100]} width={42} {...axisProps} />
              <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="5 4" />
              <ReferenceLine y={30} stroke="#22c55e" strokeDasharray="5 4" />
              <Line type="monotone" dataKey="rsi14" name="RSI 14" stroke="#0ea5e9" dot={false} strokeWidth={2} connectNulls={false} isAnimationActive={false} />
            </LineChart>
          </IndicatorPanel>

          <IndicatorPanel
            title="MACD"
            subtitle="MACD line · Signal line · Histogram"
            empty={!hasValue('macd') && !hasValue('macdSignal') && !hasValue('macdHistogram')}
          >
            <ComposedChart data={displayData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <ChartAxes />
              <ReferenceLine y={0} stroke="currentColor" opacity={0.5} />
              <Bar
                dataKey="macdHistogram"
                name="Histogram"
                fill="#22c55e"
                isAnimationActive={false}
                shape={(props) => {
                  const { x, y, width, height, payload } = props

                  if (
                    !Number.isFinite(x) ||
                    !Number.isFinite(y) ||
                    !Number.isFinite(width) ||
                    !Number.isFinite(height)
                  ) {
                    return null
                  }

                  return (
                    <rect
                      x={x}
                      y={y}
                      width={width}
                      height={height}
                      fill={(payload?.macdHistogram ?? 0) >= 0 ? '#22c55e' : '#ef4444'}
                      opacity={0.65}
                    />
                  )
                }}
              />
              <Line type="monotone" dataKey="macd" name="MACD" stroke="#0ea5e9" dot={false} strokeWidth={2} connectNulls={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="macdSignal" name="Signal" stroke="#f59e0b" dot={false} strokeWidth={2} connectNulls={false} isAnimationActive={false} />
              <Legend wrapperStyle={legendStyle} />
            </ComposedChart>
          </IndicatorPanel>
        </>
      )}

      {/* TREND: ADX +DI -DI */}
      {activeGroup === 'trend' && (
        <IndicatorPanel
          title="ADX (14)"
          subtitle="Trend strength · Positive DI · Negative DI"
          empty={!hasValue('adx14') && !hasValue('plusDi14') && !hasValue('minusDi14')}
        >
          <LineChart data={displayData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <ChartAxes />
            <ReferenceLine y={25} stroke="#94a3b8" strokeDasharray="5 4" />
            <Line dataKey="adx14" name="ADX" stroke="#f59e0b" dot={false} strokeWidth={2} connectNulls={false} isAnimationActive={false} />
            <Line dataKey="plusDi14" name="+DI" stroke="#22c55e" dot={false} strokeWidth={2} connectNulls={false} isAnimationActive={false} />
            <Line dataKey="minusDi14" name="-DI" stroke="#ef4444" dot={false} strokeWidth={2} connectNulls={false} isAnimationActive={false} />
            <Legend wrapperStyle={legendStyle} />
          </LineChart>
        </IndicatorPanel>
      )}

      {/* VOLATILITY: ATR + Bollinger Bandwidth */}
      {activeGroup === 'volatility' && (
        <>
          <IndicatorPanel
            title="ATR (14)"
            subtitle="Average True Range · Volatility"
            empty={!hasValue('atr14')}
          >
            <LineChart data={displayData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <ChartAxes />
              <Line dataKey="atr14" name="ATR 14" stroke="#a855f7" dot={false} strokeWidth={2} connectNulls={false} isAnimationActive={false} />
            </LineChart>
          </IndicatorPanel>

          <IndicatorPanel
            title="Bollinger Bandwidth"
            subtitle="Volatility expansion and contraction"
            empty={!hasValue('bollingerBandwidth')}
          >
            <LineChart data={displayData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
              <ChartAxes />
              <Line dataKey="bollingerBandwidth" name="Bandwidth" stroke="#f97316" dot={false} strokeWidth={2} connectNulls={false} isAnimationActive={false} />
            </LineChart>
          </IndicatorPanel>
        </>
      )}

      {/* MARKET CONDITION: CHOP */}
      {activeGroup === 'condition' && (
        <IndicatorPanel
          title="CHOP (14)"
          subtitle="Choppiness Index · Reference levels 38.2 and 61.8"
          empty={!hasValue('chop14')}
        >
          <LineChart data={displayData} margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
            <ChartAxes />
            <YAxis domain={[0, 100]} width={42} {...axisProps} />
            <ReferenceLine y={61.8} stroke="#ef4444" strokeDasharray="5 4" />
            <ReferenceLine y={38.2} stroke="#22c55e" strokeDasharray="5 4" />
            <Line dataKey="chop14" name="CHOP 14" stroke="#d946ef" dot={false} strokeWidth={2} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </IndicatorPanel>
      )}

    </div>

    </div>
  )
}
