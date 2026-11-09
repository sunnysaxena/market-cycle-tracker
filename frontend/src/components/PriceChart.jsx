import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  CandlestickSeries,
  LineSeries,
} from 'lightweight-charts'

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

export default function PriceChart({
  data = [],
  loading = false,
  error = null,
  timeframe = '1D',
  isDark = true,
  onVisibleRangeChange,
}) {

  const containerRef = useRef(null)
  const chartRef = useRef(null)
  const candleSeriesRef = useRef(null)
  const emaSeriesRef = useRef({})

  const onVisibleRangeChangeRef = useRef(onVisibleRangeChange)

  useEffect(() => {
    onVisibleRangeChangeRef.current = onVisibleRangeChange
  }, [onVisibleRangeChange])

  const [visibility, setVisibility] = useState(INITIAL_VISIBILITY)
  const [showMaDropdown, setShowMaDropdown] = useState(false)

  // Create the chart and its series.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const backgroundColor = isDark ? '#111827' : '#ffffff'
    const textColor = isDark ? '#cbd5e1' : '#334155'
    const gridColor = isDark ? '#263244' : '#e2e8f0'
    const borderColor = isDark ? '#334155' : '#cbd5e1'

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 460,

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
          color: isDark ? '#64748b' : '#94a3b8',
          width: 1,
          style: 2,
          labelBackgroundColor: '#475569',
        },
        horzLine: {
          color: isDark ? '#64748b' : '#94a3b8',
          width: 1,
          style: 2,
          labelBackgroundColor: '#475569',
        },
      },

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

    // Report the visible candle range to the parent component.
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
  }, [isDark])

  // Update candles and EMA overlays when new data arrives.
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

    if (candleData.length > 0) {
      chart.timeScale().fitContent()
    }
  }, [data])

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

  const hasData = data.length > 0

  return (
    <section className="w-full overflow-hidden rounded-xl border border-slate-700/70 bg-slate-900 shadow-xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-700/70 px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">
            Price Action
          </h3>
          <p className="mt-1 text-xs text-slate-400">
            Candlestick chart · {timeframe}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
                type="button"
                onClick={() => chartRef.current?.timeScale().fitContent()}
                className="rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:bg-slate-700">
                  Reset View
          </button>
          <div className="relative">
            <button
              type="button"
              onClick={() => setShowMaDropdown((current) => !current)}
              aria-expanded={showMaDropdown}
              className="flex items-center gap-2 rounded-md border border-slate-600 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:bg-slate-700"
            >
              Moving Averages
              <span>{showMaDropdown ? '▲' : '▼'}</span>
            </button>

            {showMaDropdown && (
              <div className="absolute right-0 top-full z-30 mt-2 w-48 rounded-lg border border-slate-600 bg-slate-800 p-3 shadow-xl">
                <p className="mb-2 text-xs font-semibold text-slate-300">
                  Show / Hide Averages
                </p>

                <div className="space-y-3">
                  {EMA_OPTIONS.map((option) => (
                    <label
                      key={option.key}
                      className="flex cursor-pointer items-center gap-2 text-xs text-slate-200"
                    >
                      <input
                        type="checkbox"
                        checked={visibility[option.key]}
                        onChange={() => toggleEma(option.key)}
                        className="h-3.5 w-3.5 accent-blue-500"
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
          style={{ height: 460 }}
        />

        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-950/70">
            <p className="text-sm text-slate-300">
              Loading chart data...
            </p>
          </div>
        )}

        {!loading && error && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-950/80 px-6">
            <p className="text-center text-sm text-red-400">
              {error}
            </p>
          </div>
        )}

        {!loading && !error && !hasData && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-sm text-slate-400">
              No historical candle data available.
            </p>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-700/70 px-4 py-2">
        <p className="text-xs text-slate-400">
          {data.length.toLocaleString()} candles
        </p>
        <p className="text-xs text-slate-500">
          Scroll to zoom · Drag to navigate
        </p>
      </div>
    </section>
  )
}
