import { useState } from 'react'
import { useApi } from '../api.js'
import { ENVIRONMENT, money, TYPE } from '../format.js'
import { Loader, Meter, PageHeader } from '../components/common.jsx'

export default function YourCloud() {
  const resources = useApi('/resources')
  const [search, setSearch] = useState('')
  const [team, setTeam] = useState('all')
  const [flaggedOnly, setFlaggedOnly] = useState(false)

  return (
    <>
      <PageHeader title="Your cloud">
        Every server, database and storage disk you pay for, and how hard each one worked over the last 30 days.
      </PageHeader>
      <Loader requests={[resources]}>
        {() => {
          const teams = [...new Set(resources.data.map((r) => r.team))].sort()
          const rows = resources.data.filter(
            (r) =>
              r.name.includes(search.trim().toLowerCase()) &&
              (team === 'all' || r.team === team) &&
              (!flaggedOnly || r.finding),
          )
          return (
            <>
              <form className="filters" onSubmit={(e) => e.preventDefault()}>
                <label>
                  Find by name
                  <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="payments" />
                </label>
                <label>
                  Team
                  <select value={team} onChange={(e) => setTeam(e.target.value)}>
                    <option value="all">All teams</option>
                    {teams.map((t) => (
                      <option key={t}>{t}</option>
                    ))}
                  </select>
                </label>
                <label className="check">
                  <input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} />
                  Only show problems
                </label>
                <p className="filters-count" aria-live="polite">
                  Showing {rows.length} of {resources.data.length}
                </p>
              </form>

              {rows.length === 0 ? (
                <p className="state">Nothing matches. Clear the search or pick another team.</p>
              ) : (
                <div className="table-wrap table-card">
                  <table className="stacking">
                    <thead>
                      <tr>
                        <th scope="col">Name</th>
                        <th scope="col">Team</th>
                        <th scope="col">Used for</th>
                        <th scope="col">Processor used</th>
                        <th scope="col">Memory used</th>
                        <th scope="col" className="num">
                          Cost, 30 days
                        </th>
                        <th scope="col">Problem</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.resource_id}>
                          <th scope="row">
                            {r.name}
                            <span className="sub">
                              {r.type === 'storage' ? `${r.storage_gb.toLocaleString()} GB storage` : `${r.size} ${TYPE[r.type]}`}
                            </span>
                          </th>
                          <td data-label="Team" className="cap">
                            {r.team}
                          </td>
                          <td data-label="Used for">{ENVIRONMENT[r.environment]}</td>
                          <td data-label="Processor used">
                            <Meter value={r.cpu_avg} />
                          </td>
                          <td data-label="Memory used">
                            <Meter value={r.memory_avg} />
                          </td>
                          <td data-label="Cost, 30 days" className="num">
                            {money(r.last_30_days_cost)}
                          </td>
                          <td data-label="Problem">
                            {r.finding ? <span className="badge badge-open">{r.finding}</span> : <span className="badge badge-fine">Looks fine</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )
        }}
      </Loader>
    </>
  )
}
