import { useEffect, useRef, useState } from 'react'
import type { TrendAnalysis } from '../api'
import { cn } from '@/lib/utils'
import { shortPeriod } from '../format'

const compact = (v: number) => {
  const a = Math.abs(v)
  const s = v < 0 ? '−' : ''
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`
  return `${s}$${a.toFixed(0)}`
}

/** Round up to a clean step so the scale ends on a readable value. */
function nice(v: number) {
  if (v <= 0) return 0
  const pow = 10 ** Math.floor(Math.log10(v))
  return Math.ceil(v / (pow / 2)) * (pow / 2)
}

/** Rounded at the data end, square at the zero line. */
function bar(x: number, yTop: number, w: number, h: number, up: boolean) {
  if (h <= 0) return ''
  const r = Math.min(6, w / 2, h)
  if (up) {
    return `M${x},${yTop + h} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + w - r} Q${x + w},${yTop} ${x + w},${yTop + r} V${yTop + h} Z`
  }
  return `M${x},${yTop} V${yTop + h - r} Q${x},${yTop + h} ${x + r},${yTop + h} H${x + w - r} Q${x + w},${yTop + h} ${x + w},${yTop + h - r} V${yTop} Z`
}

/** EBITDA per period as bars, the usual level as a dashed line. The latest
 *  period is the one being judged, so it alone carries the accent colour. */
export function TrendChart({ data }: { data: TrendAnalysis }) {
  const ref = useRef<HTMLDivElement>(null)
  const [W, setW] = useState(312)
  const [hover, setHover] = useState<number | null>(null)

  // Draw at the real width so text keeps its stated size in any panel.
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((e) => {
      const w = Math.round(e[0]?.contentRect.width ?? 0)
      if (w > 0) setW(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const values = data.ebitda
  const avg = data.historical_average
  const H = 196
  const PAD = { top: 24, bottom: 28, side: 2 }
  const plotW = W - PAD.side * 2
  const plotH = H - PAD.top - PAD.bottom

  // Zero is always on the scale: bars are magnitudes, and losses go below it.
  const hi = nice(Math.max(0, ...values, avg))
  const lo = -nice(-Math.min(0, ...values, avg))
  const span = hi - lo || 1
  const y = (v: number) => PAD.top + ((hi - v) / span) * plotH
  const zero = y(0)
  const avgY = y(avg)

  const n = values.length
  const band = plotW / n
  const barW = Math.min(40, band * 0.58)
  const last = n - 1
  const labelAll = band >= 46

  return (
    <div ref={ref}>
      {/* Keyed on the figures, so a new file draws in afresh. */}
      <svg
        key={data.periods.join() + data.ebitda.join()}
        viewBox={`0 0 ${W} ${H}`}
        width={W}
        height={H}
        className="block max-w-full"
        role="img"
        aria-label={`EBITDA by period. ${data.commentary}`}
      >
        <line
          x1={PAD.side} x2={W - PAD.side} y1={zero} y2={zero}
          className="stroke-n-3 dark:stroke-n-5" strokeWidth={1}
        />

        {/* Layer order: bars, then the usual line over them, then labels
            over both, so no figure is ever crossed out by the line. */}
        {values.map((v, i) => {
          const up = v >= 0
          const top = up ? y(v) : zero
          const h = Math.abs(y(v) - zero)
          const cx = PAD.side + i * band + band / 2
          const diff = v - avg
          return (
            <g
              key={data.periods[i]}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              <title>
                {`${data.periods[i]}: ${compact(v)}, ${compact(Math.abs(diff))} ${diff >= 0 ? 'above' : 'below'} the usual level`}
              </title>
              <rect
                x={PAD.side + i * band} y={PAD.top} width={band} height={plotH}
                fill="transparent"
              />
              {/* Each bar rises from the zero line, left to right. */}
              <path
                d={bar(cx - barW / 2, top, barW, h, up)}
                className={cn(
                  'animate-bar-grow transition-opacity',
                  i === last ? 'fill-primary-1 dark:fill-primary-1d' : 'fill-n-3 dark:fill-n-5'
                )}
                style={{
                  transformBox: 'fill-box',
                  transformOrigin: up ? 'bottom' : 'top',
                  animationDelay: `${i * 70}ms`,
                }}
                opacity={hover !== null && hover !== i ? 0.45 : 1}
              />
            </g>
          )
        })}

        {/* The usual line and the figures settle in once the bars are up. */}
        <line
          x1={PAD.side} x2={W - PAD.side} y1={avgY} y2={avgY}
          className="stroke-n-7 duration-500 animate-in fade-in-0 fill-mode-both dark:stroke-n-1"
          style={{ animationDelay: `${300 + n * 70}ms` }}
          strokeWidth={1.5} strokeDasharray="5 4"
          pointerEvents="none"
        />

        <g
          pointerEvents="none"
          className="duration-500 animate-in fade-in-0 fill-mode-both"
          style={{ animationDelay: `${200 + n * 70}ms` }}
        >
          {values.map((v, i) => {
            const up = v >= 0
            const top = up ? y(v) : zero
            const h = Math.abs(y(v) - zero)
            const cx = PAD.side + i * band + band / 2
            const current = i === last
            const ink = current ? 'fill-n-7 dark:fill-n-1' : 'fill-n-4 dark:fill-n-4d'
            // An 11px label spans roughly baseline-9 to baseline+2. If that
            // band would straddle the usual line, lift the label clear above it.
            let ly = up ? top - 7 : top + h + 14
            if (ly >= avgY - 2 && ly <= avgY + 9) ly = avgY - 5
            return (
              <g key={data.periods[i]}>
                {(labelAll || current || hover === i) && (
                  <text
                    x={cx} y={ly} textAnchor="middle"
                    // A halo in the panel colour lifts the figure off the line.
                    className={cn('font-display stroke-n-1 dark:stroke-n-6', ink)}
                    strokeWidth={4} paintOrder="stroke" strokeLinejoin="round"
                    fontSize={11} fontWeight={current ? 700 : 500}
                  >
                    {compact(v)}
                  </text>
                )}
                <text
                  x={cx} y={H - 8} textAnchor="middle"
                  className={cn('font-display', ink)}
                  fontSize={11} fontWeight={current ? 700 : 500}
                >
                  {shortPeriod(data.periods[i])}
                </text>
              </g>
            )
          })}
        </g>
      </svg>
    </div>
  )
}
