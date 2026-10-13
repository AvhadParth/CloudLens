import { useEffect, useRef, useState } from 'react'
import { api, useApi } from '../api.js'
import { ENVIRONMENT, money, percent, TYPE } from '../format.js'
import { KindIcon } from '../components/art.jsx'
import { Loader, PageHeader, StatusBadge } from '../components/common.jsx'

const TABS = [
  { status: 'open', label: 'To decide' },
  { status: 'approved', label: 'Approved' },
  { status: 'dismissed', label: 'Skipped' },
]

const EMPTY = {
  open: 'All done. You have decided on everything CloudLens found.',
  approved: 'No fixes approved yet. Approve one from “To decide” and it shows up here.',
  dismissed: 'You have not skipped anything.',
}

function ConfirmDialog({ target, onCancel, onConfirm, busy }) {
  const ref = useRef(null)
  useEffect(() => {
    if (target) ref.current.showModal()
    else ref.current.close()
  }, [target])

  return (
    <dialog ref={ref} closedby="any" aria-labelledby="confirm-title" onClose={onCancel}>
      {target && (
        <>
          <h2 id="confirm-title">Approve this fix?</h2>
          <p>
            <strong>{target.action}</strong> for {target.name}. You would save about{' '}
            {money(target.estimated_monthly_saving)} a month.
          </p>
          <p className="dialog-note">
            Practice mode: this only records your choice. Nothing real is switched off or deleted.
          </p>
          <div className="dialog-actions">
            <button type="button" className="btn btn-white" onClick={onCancel}>
              Cancel
            </button>
            <button type="button" className="btn" onClick={onConfirm} disabled={busy}>
              Approve fix
            </button>
          </div>
        </>
      )}
    </dialog>
  )
}

function Accuracy({ evaluation }) {
  const { overall, by_kind: byKind, planted_waste: planted, resources } = evaluation.rules
  return (
    <details className="tech">
      <summary>Technical details: how accurate are these checks?</summary>
      <p>
        {planted} of the {resources} sample items were made wasteful on purpose. CloudLens was then scored against
        that answer sheet, which it never sees. It found {overall.true_positives} of {planted}, with{' '}
        {overall.false_positives} wrong {overall.false_positives === 1 ? 'alarm' : 'alarms'}.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Kind of waste</th>
              <th scope="col" className="num">Found</th>
              <th scope="col" className="num">Missed</th>
              <th scope="col" className="num">Wrong alarms</th>
              <th scope="col" className="num">Precision</th>
              <th scope="col" className="num">Recall</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(byKind).map(([kind, k]) => (
              <tr key={kind}>
                <th scope="row">{k.label}</th>
                <td className="num">{k.true_positives}</td>
                <td className="num">{k.false_negatives}</td>
                <td className="num">{k.false_positives}</td>
                <td className="num">{percent(k.precision * 100)}</td>
                <td className="num">{percent(k.recall * 100)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        The sample data was made for this project, so a high score shows the checks work as designed. It does not
        prove they would score the same on a real cloud bill.
      </p>
    </details>
  )
}

export default function Save({ recommendations, refresh }) {
  const evaluation = useApi('/evaluation')
  const [tab, setTab] = useState('open')
  const [target, setTarget] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function run(task) {
    setBusy(true)
    setError(null)
    try {
      await task()
      refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
      setTarget(null)
    }
  }

  return (
    <>
      <PageHeader title="Ways to save">
        Everything below costs money without doing much. Biggest saving first. Approve the fixes you agree with.
      </PageHeader>
      <Loader requests={[recommendations]}>
        {() => {
          const all = recommendations.data
          const shown = all.filter((r) => r.status === tab)
          const total = shown.reduce((t, r) => t + r.estimated_monthly_saving, 0)
          return (
            <>
              <div className="tabs" role="group" aria-label="Show">
                {TABS.map((t) => (
                  <button key={t.status} type="button" aria-pressed={tab === t.status} onClick={() => setTab(t.status)}>
                    {t.label}
                    <span className="count">{all.filter((r) => r.status === t.status).length}</span>
                  </button>
                ))}
                {shown.length > 0 && <p className="tabs-total">Worth about {money(total)} a month</p>}
              </div>

              {error && (
                <p className="state state-error" role="alert">
                  That did not save. {error}
                </p>
              )}

              {shown.length === 0 ? (
                <p className="state">{EMPTY[tab]}</p>
              ) : (
                <ul className="recs">
                  {shown.map((r) => (
                    <li key={r.resource_id} className="rec">
                      <KindIcon kind={r.kind} />
                      <div className="rec-main">
                        <p className="rec-kind">{r.kind_label}</p>
                        <h2>{r.name}</h2>
                        <p className="rec-meta">
                          A {r.size ? `${r.size} ` : ''}
                          {TYPE[r.type]} used by the {r.team} team for {ENVIRONMENT[r.environment].toLowerCase()} work
                        </p>
                        <p className="rec-reason">{r.reason}</p>
                        <details className="proof">
                          <summary>How we know</summary>
                          <dl>
                            {r.evidence.map((e) => (
                              <div key={e.label}>
                                <dt>{e.label}</dt>
                                <dd>{e.value}</dd>
                              </div>
                            ))}
                            <div>
                              <dt>What it costs now</dt>
                              <dd>{money(r.current_monthly_cost)} a month</dd>
                            </div>
                          </dl>
                        </details>
                      </div>
                      <div className="rec-side">
                        <p className="rec-saving">
                          <span>Save about</span>
                          {money(r.estimated_monthly_saving)}
                          <span>a month</span>
                        </p>
                        <p className="rec-action">{r.action}</p>
                        {r.status === 'open' ? (
                          <div className="rec-buttons">
                            <button type="button" className="btn" onClick={() => setTarget(r)} disabled={busy}>
                              Approve fix
                            </button>
                            <button
                              type="button"
                              className="btn btn-white"
                              disabled={busy}
                              onClick={() => run(() => api.post(`/recommendations/${r.resource_id}/dismiss`))}
                            >
                              Skip
                            </button>
                          </div>
                        ) : (
                          <div className="rec-buttons">
                            <StatusBadge status={r.status} />
                            <button
                              type="button"
                              className="btn btn-white btn-small"
                              disabled={busy}
                              onClick={() => run(() => api.delete(`/actions/${r.action_id}`))}
                            >
                              Undo
                            </button>
                          </div>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )
        }}
      </Loader>

      {evaluation.data && <Accuracy evaluation={evaluation.data} />}

      <ConfirmDialog
        target={target}
        busy={busy}
        onCancel={() => setTarget(null)}
        onConfirm={() => run(() => api.post(`/recommendations/${target.resource_id}/approve`))}
      />
    </>
  )
}
