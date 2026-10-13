import { money } from '../format.js'

export function PageHeader({ title, children }) {
  return (
    <header className="page-header">
      <h1>{title}</h1>
      {children && <p className="lede">{children}</p>}
    </header>
  )
}

/** Shows loading and error states; renders children only once every request has data. */
export function Loader({ requests, children }) {
  const failed = requests.find((r) => r.error)
  if (failed) {
    return (
      <p className="state state-error" role="alert">
        This page could not load. {failed.error}
      </p>
    )
  }
  if (requests.some((r) => !r.data)) {
    return (
      <p className="state state-loading">
        <span className="spinner" aria-hidden="true" />
        Looking through your cloud…
      </p>
    )
  }
  return children()
}

export function StatusBadge({ status }) {
  const text = { open: 'To decide', approved: 'Approved', dismissed: 'Skipped' }[status]
  return <span className={`badge badge-${status}`}>{text}</span>
}

/** Horizontal bars for comparing a handful of named amounts. */
export function BarList({ rows }) {
  const max = Math.max(...rows.map((r) => r.value))
  return (
    <ul className="barlist">
      {rows.map((row) => (
        <li key={row.label}>
          <span className="barlist-label">{row.label}</span>
          <span className="barlist-value">{money(row.value)}</span>
          <span className="barlist-track">
            <span className="barlist-bar" style={{ width: `${(row.value / max) * 100}%` }} />
          </span>
        </li>
      ))}
    </ul>
  )
}

export function Meter({ value }) {
  if (value == null) return <span className="muted">Not measured</span>
  return (
    <span className="meter">
      <span className="meter-track">
        <span className="meter-bar" style={{ width: `${Math.min(value, 100)}%` }} />
      </span>
      {value.toFixed(0)}%
    </span>
  )
}

/** The whole bill as one chunky bar: white is useful, red is wasted, green is waste you approved a fix for. */
export function BillStrip({ total, open, approved = 0 }) {
  const share = (value) => `${(value / total) * 100}%`
  return (
    <div
      className="strip"
      role="img"
      aria-label={`Out of ${money(total)}, ${money(open + approved)} is being wasted${approved > 0 ? `, and you have approved fixes for ${money(approved)} of it` : ''}.`}
    >
      <span className="strip-useful" style={{ width: share(total - open - approved) }} />
      {approved > 0 && <span className="strip-approved" style={{ width: share(approved) }} />}
      {open > 0 && <span className="strip-open" style={{ width: share(open) }} />}
    </div>
  )
}
