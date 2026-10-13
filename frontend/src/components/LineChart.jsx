import { useEffect, useRef, useState } from 'react'

function useWidth() {
  const ref = useRef(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

/** Round the y-axis out to friendly numbers and return its ticks. */
function niceScale(min, max, count = 4) {
  const raw = (max - min || 1) / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((k) => k * magnitude).find((s) => s >= raw)
  const low = Math.floor(min / step) * step
  const high = Math.ceil(max / step) * step
  const ticks = []
  for (let t = low; t <= high + step / 2; t += step) ticks.push(t)
  return [low, high, ticks]
}

function linePath(values, x, y) {
  let d = ''
  let drawing = false
  values.forEach((value, i) => {
    if (value == null) {
      drawing = false
      return
    }
    d += `${drawing ? 'L' : 'M'}${x(i).toFixed(1)},${y(value).toFixed(1)}`
    drawing = true
  })
  return d
}

/**
 * Line chart on a shared date axis.
 *   dates   ISO date strings, one per x position
 *   series  [{ name, color, dashed, values }] where values[i] belongs to dates[i] (null = no point)
 *   band    optional { name, low, high } arrays drawn as a shaded range
 */
export default function LineChart({ dates, series, band, height = 300, formatY = String, formatX = String, label }) {
  const [ref, width] = useWidth()
  const [hover, setHover] = useState(null)

  const margin = { top: 12, right: 14, bottom: 30, left: 56 }
  const count = dates.length
  const numbers = [...series.flatMap((s) => s.values), ...(band ? [...band.low, ...band.high] : [])].filter(
    (v) => v != null,
  )
  const [low, high, ticks] = niceScale(Math.min(...numbers), Math.max(...numbers))
  const innerWidth = Math.max(width - margin.left - margin.right, 10)
  const innerHeight = height - margin.top - margin.bottom
  const x = (i) => margin.left + (count > 1 ? i / (count - 1) : 0) * innerWidth
  const y = (value) => margin.top + (1 - (value - low) / (high - low)) * innerHeight

  const tickCount = width < 520 ? 3 : 6
  const xTicks = Array.from({ length: tickCount }, (_, k) => Math.round((k / (tickCount - 1)) * (count - 1)))

  const bandPoints = band ? band.low.map((v, i) => (v == null ? null : i)).filter((i) => i != null) : []
  const bandPath = bandPoints.length
    ? `M${bandPoints.map((i) => `${x(i).toFixed(1)},${y(band.high[i]).toFixed(1)}`).join('L')}L${bandPoints
        .reverse()
        .map((i) => `${x(i).toFixed(1)},${y(band.low[i]).toFixed(1)}`)
        .join('L')}Z`
    : null

  function onMove(event) {
    const box = event.currentTarget.getBoundingClientRect()
    const ratio = (event.clientX - box.left - margin.left) / innerWidth
    setHover(Math.min(count - 1, Math.max(0, Math.round(ratio * (count - 1)))))
  }

  const hoverRows = hover == null ? [] : series.filter((s) => s.values[hover] != null)
  const flip = hover != null && x(hover) > width / 2

  return (
    <figure className="chart">
      {series.length > 1 && (
        <ul className="legend">
          {series.map((s) => (
            <li key={s.name}>
              <svg width="22" height="8" aria-hidden="true">
                <line x1="1" x2="21" y1="4" y2="4" stroke={s.color} strokeWidth="2" strokeDasharray={s.dashed ? '5 4' : null} />
              </svg>
              {s.name}
            </li>
          ))}
          {band && (
            <li>
              <span className="legend-band" aria-hidden="true" />
              {band.name}
            </li>
          )}
        </ul>
      )}
      <div className="chart-plot" ref={ref} style={{ height }}>
        {width > 0 && (
          <svg
            width={width}
            height={height}
            role="img"
            aria-label={label}
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
          >
            {ticks.map((tick) => (
              <g key={tick}>
                <line className="grid" x1={margin.left} x2={width - margin.right} y1={y(tick)} y2={y(tick)} />
                <text className="axis" x={margin.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                  {formatY(tick)}
                </text>
              </g>
            ))}
            {xTicks.map((i, k) => (
              <text
                key={i}
                className="axis"
                x={x(i)}
                y={height - 8}
                textAnchor={k === 0 ? 'start' : k === xTicks.length - 1 ? 'end' : 'middle'}
              >
                {formatX(dates[i])}
              </text>
            ))}
            {bandPath && <path className="band" d={bandPath} />}
            {series.map((s) => (
              <path
                key={s.name}
                d={linePath(s.values, x, y)}
                fill="none"
                stroke={s.color}
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
                strokeDasharray={s.dashed ? '5 4' : null}
              />
            ))}
            {hover != null && (
              <g>
                <line className="crosshair" x1={x(hover)} x2={x(hover)} y1={margin.top} y2={margin.top + innerHeight} />
                {hoverRows.map((s) => (
                  <circle key={s.name} className="dot" cx={x(hover)} cy={y(s.values[hover])} r="4.5" fill={s.color} />
                ))}
              </g>
            )}
          </svg>
        )}
        {hover != null && hoverRows.length > 0 && (
          <div className="tooltip" style={{ left: x(hover), transform: `translateX(${flip ? 'calc(-100% - 12px)' : '12px'})` }}>
            <strong>{formatX(dates[hover])}</strong>
            {hoverRows.map((s) => (
              <span key={s.name}>
                <i style={{ background: s.color }} />
                {s.name}
                <b>{formatY(s.values[hover])}</b>
              </span>
            ))}
          </div>
        )}
      </div>
    </figure>
  )
}
