import { useApi } from '../api.js'
import { day, firstName, money } from '../format.js'
import { Icon, KindIcon } from '../components/art.jsx'
import LineChart from '../components/LineChart.jsx'
import { BarList, BillStrip, Loader } from '../components/common.jsx'

const KIND_ORDER = ['idle', 'oversized', 'always_on_dev', 'unattached_storage']

function rollingAverage(values, size = 7) {
  return values.map((_, i) => {
    if (i < size - 1) return null
    const window = values.slice(i - size + 1, i + 1)
    return window.reduce((a, b) => a + b, 0) / size
  })
}

export default function Home({ user, summary, recommendations }) {
  const costs = useApi('/costs?granularity=daily')

  return (
    <Loader requests={[summary, recommendations, costs]}>
      {() => {
        const s = summary.data
        const live = recommendations.data.filter((r) => r.status !== 'dismissed')
        const kinds = KIND_ORDER.map((kind) => {
          const members = live.filter((r) => r.kind === kind)
          return {
            kind,
            label: members[0]?.kind_label,
            count: members.filter((r) => r.status === 'open').length,
            open: members.filter((r) => r.status === 'open').reduce((t, r) => t + r.estimated_monthly_saving, 0),
          }
        }).filter((k) => k.label)
        const open = s.open_monthly_saving
        const approved = s.approved_monthly_saving
        const openCount = live.filter((r) => r.status === 'open').length
        const change = s.change_pct

        return (
          <>
            <header className="page-header">
              <h1>Welcome back, {firstName(user.name)}</h1>
              <p className="lede">Here is where your cloud money went over the last 30 days.</p>
            </header>

            <section className="spotlight">
              {open > 0 ? (
                <>
                  <h2>You could stop wasting</h2>
                  <p className="spotlight-number">
                    {money(open)}
                    <span>a month</span>
                  </p>
                  <p className="spotlight-text">
                    That is {Math.round((open / s.last_30_days_cost) * 100)}% of your {money(s.last_30_days_cost)} bill,
                    going to {openCount} {openCount === 1 ? 'resource' : 'resources'} nobody is using.
                  </p>
                </>
              ) : (
                <>
                  <h2>Nothing left to fix</h2>
                  <p className="spotlight-number">
                    {money(approved)}
                    <span>saved a month</span>
                  </p>
                  <p className="spotlight-text">You have dealt with everything CloudLens found.</p>
                </>
              )}
              <BillStrip total={s.last_30_days_cost} open={open} approved={approved} />
              <ul className="strip-legend">
                <li>
                  <i className="dot dot-useful" />
                  Doing useful work
                </li>
                <li>
                  <i className="dot dot-open" />
                  Wasted
                </li>
                {approved > 0 && (
                  <li>
                    <i className="dot dot-approved" />
                    Fix approved
                  </li>
                )}
              </ul>
              {open > 0 && (
                <a href="#/save" className="btn">
                  See how to save it
                  <Icon name="arrow" />
                </a>
              )}
            </section>

            <ul className="stats">
              <li className="sticker sticker-white">
                <p className="sticker-label">Your bill, last 30 days</p>
                <p className="sticker-number">{money(s.last_30_days_cost)}</p>
                <p className="sticker-note">
                  {Math.abs(change) < 0.05
                    ? 'About the same as the month before'
                    : `${change > 0 ? 'Up' : 'Down'} ${Math.abs(change).toFixed(1)}% on the month before`}
                </p>
              </li>
              <li className="sticker sticker-sun">
                <p className="sticker-label">Next month, we expect</p>
                <p className="sticker-number">{s.forecast_next_30_days == null ? 'Soon' : money(s.forecast_next_30_days)}</p>
                <p className="sticker-note">
                  <a href="#/bills">See the next three months</a>
                </p>
              </li>
              <li className="sticker sticker-mint">
                <p className="sticker-label">Fixes you approved</p>
                <p className="sticker-number">{money(approved)}</p>
                <p className="sticker-note">Saved every month, estimated</p>
              </li>
            </ul>

            {kinds.some((k) => k.count > 0) && (
              <section>
                <h2>Where the money is going to waste</h2>
                <ul className="leaks">
                  {kinds
                    .filter((k) => k.count > 0)
                    .map((k) => (
                      <li key={k.kind}>
                        <a href="#/save" className="leak">
                          <KindIcon kind={k.kind} />
                          <span className="leak-label">{k.label}</span>
                          <span className="leak-number">{money(k.open)}</span>
                          <span className="leak-note">
                            a month, across {k.count} {k.count === 1 ? 'item' : 'items'}
                          </span>
                        </a>
                      </li>
                    ))}
                </ul>
              </section>
            )}

            <div className="split">
              <section className="panel">
                <h2>What you spent each day this year</h2>
                <p className="panel-note">Smoothed over a week so weekends do not hide the trend.</p>
                <LineChart
                  dates={costs.data.map((d) => d.period)}
                  series={[{ name: 'Spent that day', color: 'var(--blue)', values: rollingAverage(costs.data.map((d) => d.cost)) }]}
                  formatY={money}
                  formatX={day}
                  height={280}
                  label="Line chart of daily cloud spending over the last twelve months"
                />
              </section>
              <section className="panel">
                <h2>Which team spends the most</h2>
                <p className="panel-note">Last 30 days.</p>
                <BarList rows={Object.entries(s.last_30_days_by.team).map(([label, value]) => ({ label, value }))} />
              </section>
            </div>
          </>
        )
      }}
    </Loader>
  )
}
