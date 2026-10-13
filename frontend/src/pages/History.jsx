import { useState } from 'react'
import { api, useApi } from '../api.js'
import { money, timestamp } from '../format.js'
import { Loader, PageHeader, StatusBadge } from '../components/common.jsx'

export default function History({ version, refresh }) {
  const actions = useApi('/actions', version)
  const [error, setError] = useState(null)

  async function undo(id) {
    setError(null)
    try {
      await api.delete(`/actions/${id}`)
      refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <>
      <PageHeader title="History">
        Every choice you have made. This is practice mode, so nothing was really switched off or deleted.
      </PageHeader>
      <Loader requests={[actions]}>
        {() => {
          const approved = actions.data.filter((a) => a.status === 'approved')
          const monthly = approved.reduce((t, a) => t + a.estimated_monthly_saving, 0)
          if (actions.data.length === 0) {
            return (
              <p className="state">
                No choices yet. <a href="#/save">Look at the ways to save</a> and approve one to see it here.
              </p>
            )
          }
          return (
            <>
              <ul className="stats">
                <li className="sticker sticker-white">
                  <p className="sticker-label">Fixes approved</p>
                  <p className="sticker-number">{approved.length}</p>
                </li>
                <li className="sticker sticker-mint">
                  <p className="sticker-label">Saved every month</p>
                  <p className="sticker-number">{money(monthly)}</p>
                  <p className="sticker-note">Estimated</p>
                </li>
                <li className="sticker sticker-sun">
                  <p className="sticker-label">Saved over a year</p>
                  <p className="sticker-number">{money(monthly * 12)}</p>
                  <p className="sticker-note">Estimated</p>
                </li>
              </ul>
              {error && (
                <p className="state state-error" role="alert">
                  That did not undo. {error}
                </p>
              )}
              <div className="table-wrap table-card">
                <table className="stacking">
                  <thead>
                    <tr>
                      <th scope="col">Name</th>
                      <th scope="col">Fix</th>
                      <th scope="col">Your choice</th>
                      <th scope="col">When</th>
                      <th scope="col" className="num">Saves a month</th>
                      <th scope="col">
                        <span className="sr-only">Undo</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {actions.data.map((a) => (
                      <tr key={a.id}>
                        <th scope="row">{a.resource_name}</th>
                        <td data-label="Fix">{a.action}</td>
                        <td data-label="Your choice">
                          <StatusBadge status={a.status} />
                        </td>
                        <td data-label="When">{timestamp(a.decided_at)}</td>
                        <td data-label="Saves a month" className="num">
                          {a.status === 'approved' ? money(a.estimated_monthly_saving) : <span className="muted">Nothing</span>}
                        </td>
                        <td>
                          <button type="button" className="btn btn-white btn-small" onClick={() => undo(a.id)}>
                            Undo<span className="sr-only"> choice for {a.resource_name}</span>
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )
        }}
      </Loader>
    </>
  )
}
