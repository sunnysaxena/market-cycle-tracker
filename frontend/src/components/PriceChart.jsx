
import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  CandlestickSeries,
  LineSeries,
} from 'lightweight-charts'

const DEFAULT_CHART_HEIGHT = 550
const MIN_CHART_HEIGHT = 350
const MAX_CHART_HEIGHT = 900

const EMA_OPTIONS = [
  { key: 'ema9', label: 'EMA 9', color: '#facc15' },
  { key: 'ema20', label: 'EMA 20', color: '#38bdf8' },
  { key: 'ema50', label: 'EMA 50', color: '#c084fc' },
  { key: 'ema100', label: 'EMA 100', color: '#b0f02f' },
  { key: 'ema200', label: 'EMA 200', color: '#fb923c' },
  { key: 'sma222', label: 'SMA 222', color: '#ff2929' },
]

const INITIAL_VISIBILITY = {
  ema9: true,
  ema20: true,
  ema50: false,
  ema100: false,
  ema200: false,
  sma222: false,
}

function getChartTheme(isDark) {
  const backgroundColor = isDark ? '#111827' : '#ffffff'
  const textColor = isDark ? '#cbd5e1' : '#334155'
  const gridColor = isDark ? '#263244' : '#e2e8f0'
  const borderColor = isDark ? '#334155' : '#cbd5e1'
  const crosshairColor = isDark ? '#64748b' : '#94a3b8'

  return {
    layout: {
      background: {
        type: 'solid',
        color: backgroundColor,
      },
      textColor,
      fontFamily: 'Inter, system-ui, sans-serif',
      fontSize: 12,
    },

    grid: {
      vertLines: { color: gridColor },
      horzLines: { color: gridColor },
    },

    rightPriceScale: {
      borderColor,
      autoScale: true,
    },

    timeScale: {
      borderColor,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 5,
    },

    crosshair: {
      vertLine: {
        color: crosshairColor,
        width: 1,
        style: 2,
        labelBackgroundColor: '#475569',
      },
      horzLine: {
        color: crosshairColor,
        width: 1,
        style: 2,
        labelBackgroundColor: '#475569',
      },
    },
  }
}

export default function PriceChart({
  data = [],
  loading = false,
  error = null,
  timeframe = '1D',
  isDark = true,
  fitContentKey = 0,
  onVisibleRangeChange,
}) {
  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const candleSeriesRef = useRef(null)
  const emaSeriesRef = useRef({})

  const onVisibleRangeChangeRef = useRef(onVisibleRangeChange)
  const resizeStartRef = useRef(null)
  const lastFitContentKeyRef = useRef(null)

  const [visibility, setVisibility] = useState(INITIAL_VISIBILITY)
  const [showMaDropdown, setShowMaDropdown] = useState(false)
  const [chartHeight, setChartHeight] = useState(DEFAULT_CHART_HEIGHT)

  useEffect(() => {
    onVisibleRangeChangeRef.current = onVisibleRangeChange
  }, [onVisibleRangeChange])

  // Create the chart once. Theme updates are handled separately.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      width: container.clientWidth,
      height: DEFAULT_CHART_HEIGHT,

      ...getChartTheme(true),

      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },

      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    const emaSeries = {}

    for (const option of EMA_OPTIONS) {
      emaSeries[option.key] = chart.addSeries(LineSeries, {
        color: option.color,
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: true,
        visible: INITIAL_VISIBILITY[option.key],
      })
    }

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    emaSeriesRef.current = emaSeries

    // Report the visible candle range to the parent.
    let visibleRangeTimer = null
    let lastReportedRange = null

    const handleVisibleLogicalRangeChange = (range) => {
      const nextRange = range
        ? {
            from: Math.floor(range.from),
            to: Math.ceil(range.to),
          }
        : null

      clearTimeout(visibleRangeTimer)

      visibleRangeTimer = setTimeout(() => {
        if (
          nextRange &&
          lastReportedRange &&
          nextRange.from === lastReportedRange.from &&
          nextRange.to === lastReportedRange.to
        ) {
          return
        }

        lastReportedRange = nextRange
        onVisibleRangeChangeRef.current?.(nextRange)
      }, 120)
    }

    chart.timeScale().subscribeVisibleLogicalRangeChange(
      handleVisibleLogicalRangeChange
    )

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return

      const width = Math.floor(entry.contentRect.width)

      if (width > 0) {
        chart.applyOptions({ width })
      }
    })

    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      clearTimeout(visibleRangeTimer)

      chart.timeScale().unsubscribeVisibleLogicalRangeChange(
        handleVisibleLogicalRangeChange
      )

      chart.remove()

      chartRef.current = null
      candleSeriesRef.current = null
      emaSeriesRef.current = {}
    }
  }, [])

  // Apply dark/light theme without rebuilding the chart.
  useEffect(() => {
    chartRef.current?.applyOptions(getChartTheme(isDark))
  }, [isDark])

  // Update chart height when the resize control is used.
  useEffect(() => {
    chartRef.current?.applyOptions({
      height: chartHeight,
    })
  }, [chartHeight])

  // Update candles and EMA overlays when data changes.
  // Only fit content when a new fit request is received.
  useEffect(() => {
    const candleSeries = candleSeriesRef.current
    const emaSeries = emaSeriesRef.current
    const chart = chartRef.current

    if (!candleSeries || !chart) return

    const validCandles = data
      .filter(
        (item) =>
          item.time &&
          Number.isFinite(item.open) &&
          Number.isFinite(item.high) &&
          Number.isFinite(item.low) &&
          Number.isFinite(item.close),
      )
      .sort((a, b) => a.time.localeCompare(b.time))

    const candleData = validCandles.map((item) => ({
      time: item.time,
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    }))

    candleSeries.setData(candleData)

    for (const option of EMA_OPTIONS) {
      const series = emaSeries[option.key]
      if (!series) continue

      const lineData = validCandles
        .filter((item) => Number.isFinite(item[option.key]))
        .map((item) => ({
          time: item.time,
          value: item[option.key],
        }))

      series.setData(lineData)
    }

    if (
      candleData.length > 0 &&
      lastFitContentKeyRef.current !== fitContentKey
    ) {
      chart.timeScale().fitContent()
      lastFitContentKeyRef.current = fitContentKey
    }
  }, [data, fitContentKey])

  // Apply EMA visibility without rebuilding the chart.
  useEffect(() => {
    for (const option of EMA_OPTIONS) {
      const series = emaSeriesRef.current[option.key]

      if (series) {
        series.applyOptions({
          visible: visibility[option.key],
        })
      }
    }
  }, [visibility])

  function toggleEma(key) {
    setVisibility((current) => ({
      ...current,
      [key]: !current[key],
    }))
  }

  function handleResizeStart(event) {
    event.preventDefault()

    event.currentTarget.setPointerCapture(event.pointerId)

    resizeStartRef.current = {
      startY: event.clientY,
      startHeight: chartHeight,
    }
  }

  function handleResizeMove(event) {
    if (!resizeStartRef.current) return

    const difference = event.clientY - resizeStartRef.current.startY

    const nextHeight = Math.min(
      MAX_CHART_HEIGHT,
      Math.max(
        MIN_CHART_HEIGHT,
        resizeStartRef.current.startHeight + difference,
      ),
    )

    setChartHeight(nextHeight)
  }

  function handleResizeEnd() {
    resizeStartRef.current = null
  }

  const hasData = data.length > 0

  const panelClass = isDark
    ? 'border-slate-700/70 bg-slate-900'
    : 'border-slate-200 bg-white'

  const headingClass = isDark
    ? 'text-slate-100'
    : 'text-slate-900'

  const mutedClass = isDark
    ? 'text-slate-400'
    : 'text-slate-500'

  const buttonClass = isDark
    ? 'border-slate-600 bg-slate-800 text-slate-200 hover:border-primary hover:bg-primary-soft'
    : 'border-slate-300 bg-white text-slate-700 hover:border-primary hover:bg-primary-soft'

  const dropdownClass = isDark
    ? 'border-slate-600 bg-slate-800 text-slate-200 shadow-emerald-950/20'
    : 'border-slate-200 bg-white text-slate-700 shadow-slate-200/60'

  return (
    <section
      className={`w-full overflow-hidden rounded-xl border shadow-sm ${panelClass}`}
    >
      <div
        className={`flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3 ${
          isDark ? 'border-slate-700/70' : 'border-slate-200'
        }`}
      >
        <div>
          <h3 className={`text-sm font-semibold ${headingClass}`}>
            Price Action
          </h3>

          <p className={`mt-1 text-xs ${mutedClass}`}>
            Candlestick chart Â· {timeframe}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => chartRef.current?.timeScale().fitContent()}
            className={`rounded-md border px-3 py-1.5 text-xs font-medium transition ${buttonClass}`}
          >
            Reset View
          </button>

          <div className="relative">
            <button
              type="button"
              onClick={() => setShowMaDropdown((current) => !current)}
              aria-expanded={showMaDropdown}
              className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs font-medium transition ${buttonClass}`}
            >
              Moving Averages
              <span>{showMaDropdown ? '\u25B2' : '\u25BC'}</span>
            </button>

            {showMaDropdown && (
              <div
                className={`absolute right-0 top-full z-30 mt-2 w-48 rounded-lg border p-3 shadow-xl ${dropdownClass}`}
              >
                <p className="mb-2 text-xs font-semibold">
                  Show / Hide Averages
                </p>

                <div className="space-y-3">
                  {EMA_OPTIONS.map((option) => (
                    <label
                      key={option.key}
                      className="flex cursor-pointer items-center gap-2 text-xs"
                    >
                      <input
                        type="checkbox"
                        checked={visibility[option.key]}
                        onChange={() => toggleEma(option.key)}
                        className="h-3.5 w-3.5 accent-primary"
                      />

                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: option.color }}
                      />

                      {option.label}
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="relative">
        <div
          ref={containerRef}
          className="w-full"
          style={{ height: `${chartHeight}px` }}
        />

        {loading && (
          <div
            className={`absolute inset-0 flex items-center justify-center ${
              isDark ? 'bg-slate-950/70' : 'bg-white/75'
            }`}
          >
            <p className={`text-sm ${mutedClass}`}>
              Loading chart data...
            </p>
          </div>
        )}

        {!loading && error && (
          <div
            className={`absolute inset-0 flex items-center justify-center px-6 ${
              isDark ? 'bg-slate-950/80' : 'bg-white/90'
            }`}
          >
            <p className="text-center text-sm text-red-500">
              {error}
            </p>
          </div>
        )}

        {!loading && !error && !hasData && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className={`text-sm ${mutedClass}`}>
              No historical candle data available.
            </p>
          </div>
        )}
      </div>

      {/* Adjustable chart-height handle */}
      <div
        role="separator"
        aria-label="Resize price chart"
        aria-orientation="horizontal"
        aria-valuemin={MIN_CHART_HEIGHT}
        aria-valuemax={MAX_CHART_HEIGHT}
        aria-valuenow={Math.round(chartHeight)}
        tabIndex={0}
        onPointerDown={handleResizeStart}
        onPointerMove={handleResizeMove}
        onPointerUp={handleResizeEnd}
        onPointerCancel={handleResizeEnd}
        onDoubleClick={() => setChartHeight(DEFAULT_CHART_HEIGHT)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowUp') {
            event.preventDefault()
            setChartHeight((current) =>
              Math.min(MAX_CHART_HEIGHT, current + 25),
            )
          }

          if (event.key === 'ArrowDown') {
            event.preventDefault()
            setChartHeight((current) =>
              Math.max(MIN_CHART_HEIGHT, current - 25),
            )
          }

          if (event.key === 'Home') {
            event.preventDefault()
            setChartHeight(MIN_CHART_HEIGHT)
          }

          if (event.key === 'End') {
            event.preventDefault()
            setChartHeight(MAX_CHART_HEIGHT)
          }

          if (event.key === 'Enter') {
            event.preventDefault()
            setChartHeight(DEFAULT_CHART_HEIGHT)
          }
        }}
        className={`flex h-4 cursor-ns-resize touch-none items-center justify-center border-t transition-colors ${
          isDark
            ? 'border-slate-700 hover:bg-slate-800'
            : 'border-slate-200 hover:bg-slate-100'
        }`}
        title="Drag to resize Â· Double-click to reset"
      >
        <div
          className={`h-1 w-12 rounded-full ${
            isDark ? 'bg-slate-600' : 'bg-slate-300'
          }`}
        />
      </div>

      <div
        className={`flex flex-wrap items-center justify-between gap-2 border-t px-4 py-2 ${
          isDark ? 'border-slate-700/70' : 'border-slate-200'
        }`}
      >
        <p className={`text-xs ${mutedClass}`}>
          {data.length.toLocaleString()} candles
        </p>

        <p className={`text-xs ${mutedClass}`}>
          {Math.round(chartHeight)}px Â· Scroll to zoom Â· Drag to navigate
        </p>
      </div>
    </section>
  )
}
