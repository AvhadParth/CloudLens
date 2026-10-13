import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { firstName, fullDay, money } from '../format.js'
import { Icon, ProviderMark } from '../components/art.jsx'
import { Loader, PageHeader } from '../components/common.jsx'

const STEPS = [
  'Linking the account',
  'Reading 12 months of bills',
  'Checking how busy each server was',
  'Looking for waste',
]
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function ConnectDialog({ provider, onClose, onConnected }) {
  const ref = useRef(null)
  const [step, setStep] = useState(-1) // -1 = not started yet
  const [error, setError] = useState(null)

  useEffect(() => {
    if (provider) {
      setStep(-1)
      setError(null)
      ref.current.showModal()
    } else {
      ref.current.close()
    }
  }, [provider])

  async function connect() {
    setError(null)
    try {
      for (let i = 0; i < STEPS.length; i += 1) {
        setStep(i)
        // The last step does the real work: saving the connection to your account.
        if (i === STEPS.length - 1) await api.post('/connections', { provider: provider.id })
        await wait(600)
      }
      onConnected()
    } catch (e) {
      setError(e.message)
      setStep(-1)
    }
  }

  const busy = step >= 0

  return (
    <dialog ref={ref} aria-labelledby="connect-title" onClose={onClose} onCancel={(e) => busy && e.preventDefault()}>
      {provider && (
        <>
          <div className="connect-head">
            <ProviderMark id={provider.id} />
            <h2 id="connect-title">Connect {provider.name}</h2>
          </div>

          {busy ? (
            <ol className="connect-steps" aria-live="polite">
              {STEPS.map((label, i) => (
                <li key={label} className={i < step ? 'is-done' : i === step ? 'is-active' : undefined}>
                  {i < step ? <Icon name="check" size={16} /> : <span className={i === step ? 'spinner' : 'step-dot'} aria-hidden="true" />}
                  {label}
                </li>
              ))}
            </ol>
          ) : (
            <>
              <p>
                CloudLens will read this account’s bills and how busy each server is. It only reads; it never changes
                anything.
              </p>
              <p className="dialog-note">
                <strong>Demo connection.</strong> A live version would send you to {provider.name} to sign in and
                grant read-only access. This prototype skips that and links a sample {provider.name} account with{' '}
                {provider.resource_count} resources. It never asks for your cloud password or keys.
              </p>
              {error && (
                <p className="form-error" role="alert">
                  That did not connect. {error}
                </p>
              )}
              <div className="dialog-actions">
                <button type="button" className="btn btn-ghost" onClick={onClose}>
                  Cancel
                </button>
                <button type="button" className="btn" onClick={connect}>
                  Connect sample account
                </button>
              </div>
            </>
          )}
        </>
      )}
    </dialog>
  )
}

export default function Connections({ user, connections, refresh, welcome = false }) {
  const [target, setTarget] = useState(null)
  const [error, setError] = useState(null)

  async function disconnect(provider) {
    setError(null)
    try {
      await api.delete(`/connections/${provider.id}`)
      refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <>
      {welcome ? (
        <PageHeader title={`Welcome, ${firstName(user.name)}. Let’s connect your cloud.`}>
          Your dashboard is empty until CloudLens can see a bill. Connect one or more cloud accounts to get started.
        </PageHeader>
      ) : (
        <PageHeader title="Cloud connections">
          The cloud accounts CloudLens reads. Your dashboard only shows data from the ones you connect.
        </PageHeader>
      )}

      {error && (
        <p className="state state-error" role="alert">
          That did not disconnect. {error}
        </p>
      )}

      <Loader requests={[connections]}>
        {() => (
          <ul className="providers">
            {connections.data.map((p) => (
              <li key={p.id} className={`provider${p.connected ? ' is-connected' : ''}`}>
                <div className="provider-top">
                  <ProviderMark id={p.id} />
                  {p.connected ? <span className="badge badge-approved">Connected</span> : <span className="badge">Not connected</span>}
                </div>
                <h2>{p.name}</h2>
                {p.connected ? (
                  <p className="provider-meta">
                    {p.resource_count} resources, about {money(p.monthly_cost)} a month. Connected {fullDay(p.connected_at)}.
                  </p>
                ) : (
                  <p className="provider-meta">Sample account with {p.resource_count} resources.</p>
                )}
                {p.connected ? (
                  <button type="button" className="btn btn-ghost btn-small" onClick={() => disconnect(p)}>
                    Disconnect
                  </button>
                ) : (
                  <button type="button" className="btn" onClick={() => setTarget(p)}>
                    Connect
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Loader>

      <p className="callout">
        <strong>How connections work in this prototype.</strong> Each provider links a sample account, so you can try
        CloudLens without handing over real cloud access. Reading live AWS, Azure and Google Cloud bills is the planned
        next step.
      </p>

      <ConnectDialog
        provider={target}
        onClose={() => setTarget(null)}
        onConnected={() => {
          setTarget(null)
          refresh()
          if (welcome) window.location.hash = '#/home'
        }}
      />
    </>
  )
}
