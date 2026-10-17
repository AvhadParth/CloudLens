import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { firstName, fullDay, money, timestamp } from '../format.js'
import { Icon, ProviderMark } from '../components/art.jsx'
import { Loader, PageHeader } from '../components/common.jsx'

const NAMES = { aws: 'Amazon Web Services', azure: 'Microsoft Azure', gcp: 'Google Cloud' }

function Copyable({ text }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="code">
      <pre>{text}</pre>
      <button
        type="button"
        className="btn btn-ghost btn-small"
        onClick={() => navigator.clipboard?.writeText(text).then(() => setCopied(true), () => {})}
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  )
}

/* ---------- what each provider needs, in plain steps ---------- */

function AwsGuide({ policy }) {
  return (
    <ol className="guide">
      <li>
        In the AWS console open <strong>IAM → Users → Create user</strong>. Name it <code>cloudlens-readonly</code> and
        leave console access off.
      </li>
      <li>
        On the new user choose <strong>Add permissions → Create inline policy → JSON</strong>, paste this read-only
        policy and save it:
        <Copyable text={JSON.stringify(policy, null, 2)} />
      </li>
      <li>
        Open the user’s <strong>Security credentials</strong> tab, choose <strong>Create access key → Third-party
        service</strong>, and copy both keys into the boxes below.
      </li>
      <li>
        If you have never opened <strong>Billing → Cost Explorer</strong>, open it once to switch it on (AWS can take up
        to a day to prepare the data). AWS charges $0.01 for each Cost Explorer request; CloudLens makes one per sync.
      </li>
    </ol>
  )
}

function AzureGuide() {
  return (
    <ol className="guide">
      <li>
        Open <strong>Cloud Shell</strong> from the top bar of the Azure portal and find your subscription ID:
        <Copyable text="az account show --query id -o tsv" />
      </li>
      <li>
        Create a read-only identity for CloudLens (replace the ID with yours):
        <Copyable text={'az ad sp create-for-rbac --name cloudlens-reader --role Reader \\\n  --scopes /subscriptions/YOUR_SUBSCRIPTION_ID'} />
      </li>
      <li>
        It prints <code>appId</code> (the client ID), <code>password</code> (the client secret) and <code>tenant</code>{' '}
        (the tenant ID). Copy them, with the subscription ID, into the boxes below.
      </li>
    </ol>
  )
}

function GcpGuide() {
  const commands = [
    'PROJECT=your-project-id',
    'gcloud iam service-accounts create cloudlens-reader --project $PROJECT',
    'for ROLE in compute.viewer monitoring.viewer bigquery.dataViewer bigquery.jobUser; do',
    '  gcloud projects add-iam-policy-binding $PROJECT \\',
    '    --member serviceAccount:cloudlens-reader@$PROJECT.iam.gserviceaccount.com --role roles/$ROLE',
    'done',
    'gcloud iam service-accounts keys create key.json \\',
    '  --iam-account cloudlens-reader@$PROJECT.iam.gserviceaccount.com',
    'cat key.json',
  ].join('\n')
  return (
    <ol className="guide">
      <li>
        Open <strong>Cloud Shell</strong> in the Google Cloud console and run this, with your project ID on the first
        line. It creates a read-only service account and a key for it:
        <Copyable text={commands} />
      </li>
      <li>Paste everything that <code>cat key.json</code> prints into the key box below.</li>
      <li>
        For the real bill, turn on <strong>Billing → Billing export → BigQuery export</strong> (detailed usage cost)
        and copy the table name, which looks like <code>project.dataset.gcp_billing_export_v1_XXXXXX</code>. Without
        it, CloudLens estimates costs from list prices.
      </li>
    </ol>
  )
}

const FIELDS = {
  aws: [
    { name: 'access_key_id', label: 'Access key ID', placeholder: 'AKIA…', autoComplete: 'off' },
    { name: 'secret_access_key', label: 'Secret access key', secret: true },
  ],
  azure: [
    { name: 'tenant_id', label: 'Tenant ID', placeholder: '00000000-0000-0000-0000-000000000000' },
    { name: 'client_id', label: 'Client ID (appId)', placeholder: '00000000-0000-0000-0000-000000000000' },
    { name: 'client_secret', label: 'Client secret (password)', secret: true },
    { name: 'subscription_id', label: 'Subscription ID', placeholder: '00000000-0000-0000-0000-000000000000' },
  ],
  gcp: [
    { name: 'service_account_json', label: 'Service account key (contents of key.json)', multiline: true },
    { name: 'project_id', label: 'Project ID', placeholder: 'Read from the key if left empty', optional: true },
    { name: 'billing_table', label: 'Billing export table', placeholder: 'project.dataset.gcp_billing_export_v1_XXXXXX', optional: true },
  ],
}

/* ---------- the add-account wizard ---------- */

function AddAccountDialog({ open, policy, onClose, onDone }) {
  const ref = useRef(null)
  const [provider, setProvider] = useState(null)
  const [label, setLabel] = useState('')
  const [values, setValues] = useState({})
  const [stage, setStage] = useState('pick') // pick -> form -> syncing -> done
  const [error, setError] = useState(null)
  const [account, setAccount] = useState(null)

  useEffect(() => {
    if (open) {
      setProvider(null)
      setLabel('')
      setValues({})
      setStage('pick')
      setError(null)
      setAccount(null)
      ref.current.showModal()
    } else {
      ref.current.close()
    }
  }, [open])

  const busy = stage === 'checking' || stage === 'syncing'

  async function sync(created) {
    setStage('syncing')
    const result = await api.post(`/cloud-accounts/${created.id}/sync`)
    setAccount(result)
    setStage(result.status === 'ready' ? 'done' : 'failed')
  }

  async function submit(event) {
    event.preventDefault()
    setError(null)
    setStage('checking')
    try {
      const credentials = Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim() !== ''))
      const created = await api.post('/cloud-accounts', { provider, label, credentials })
      setAccount(created)
      await sync(created)
    } catch (e) {
      setError(e.message)
      setStage('form')
    }
  }

  return (
    <dialog ref={ref} className="wizard" aria-labelledby="wizard-title" onClose={onClose} onCancel={(e) => busy && e.preventDefault()}>
      {stage === 'pick' && (
        <>
          <h2 id="wizard-title">Connect a cloud account</h2>
          <p>Which cloud do you use? You can connect more than one.</p>
          <div className="pick">
            {Object.entries(NAMES).map(([id, name]) => (
              <button key={id} type="button" className="pick-option" onClick={() => { setProvider(id); setStage('form') }}>
                <ProviderMark id={id} />
                {name}
              </button>
            ))}
          </div>
          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
          </div>
        </>
      )}

      {(stage === 'form' || stage === 'checking') && (
        <form onSubmit={submit}>
          <div className="connect-head">
            <ProviderMark id={provider} />
            <h2 id="wizard-title">Connect {NAMES[provider]}</h2>
          </div>
          <p className="dialog-note">
            Use <strong>read-only</strong> keys made just for CloudLens. They are checked with {NAMES[provider]}, then
            stored encrypted and never shown again. Removing the account deletes them.
          </p>
          <details className="guide-box" open>
            <summary>How to create read-only keys</summary>
            {provider === 'aws' && <AwsGuide policy={policy} />}
            {provider === 'azure' && <AzureGuide />}
            {provider === 'gcp' && <GcpGuide />}
          </details>

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          <div className="fields">
            <label>
              <span>
                Name for this account <span className="hint">(optional)</span>
              </span>
              <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={60} placeholder="e.g. Production" />
            </label>
            {FIELDS[provider].map((field) => (
              <label key={field.name}>
                <span>
                  {field.label} {field.optional && <span className="hint">(optional)</span>}
                </span>
                {field.multiline ? (
                  <textarea
                    rows={6}
                    spellCheck={false}
                    required={!field.optional}
                    value={values[field.name] ?? ''}
                    onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                    placeholder='{ "type": "service_account", … }'
                  />
                ) : (
                  <input
                    type="text"
                    className={field.secret ? 'masked' : undefined}
                    name={`cloudlens-${provider}-${field.name}`}
                    autoComplete="off"
                    data-1p-ignore
                    data-lpignore="true"
                    spellCheck={false}
                    required={!field.optional}
                    value={values[field.name] ?? ''}
                    onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                    placeholder={field.placeholder}
                  />
                )}
              </label>
            ))}
          </div>

          <div className="dialog-actions">
            <button type="button" className="btn btn-ghost" onClick={() => setStage('pick')} disabled={busy}>
              Back
            </button>
            <button type="submit" className="btn" disabled={busy}>
              {stage === 'checking' ? 'Checking the keys…' : 'Check keys and connect'}
            </button>
          </div>
        </form>
      )}

      {(stage === 'syncing' || stage === 'done' || stage === 'failed') && (
        <>
          <div className="connect-head">
            <ProviderMark id={provider} />
            <h2 id="wizard-title">{account?.label}</h2>
          </div>
          <ol className="connect-steps" aria-live="polite">
            <li className="is-done">
              <Icon name="check" size={16} />
              Keys accepted for {account?.account_ref}
            </li>
            <li className={stage === 'syncing' ? 'is-active' : 'is-done'}>
              {stage === 'syncing' ? <span className="spinner" aria-hidden="true" /> : <Icon name="check" size={16} />}
              Reading the bill, servers, disks and 30 days of usage
            </li>
            <li className={stage === 'done' ? 'is-done' : undefined}>
              {stage === 'done' ? <Icon name="check" size={16} /> : <span className="step-dot" aria-hidden="true" />}
              Looking for waste
            </li>
          </ol>
          {stage === 'syncing' && <p className="hint">This usually takes 10 to 40 seconds.</p>}
          {stage === 'done' && (
            <p>
              Found {account.resource_count} resources and about {money(account.monthly_cost)} of spending in the last 30
              days.
            </p>
          )}
          {stage === 'done' && account.warnings?.length > 1 && (
            <div className="sync-notes">
              <p>Some things could not be read:</p>
              <ul>
                {account.warnings.slice(1).map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          {stage === 'failed' && (
            <p className="form-error" role="alert">
              The keys work, but reading the account failed: {account?.last_error}
            </p>
          )}
          <div className="dialog-actions">
            {stage === 'failed' && (
              <button type="button" className="btn btn-ghost" onClick={() => sync(account)}>
                Try again
              </button>
            )}
            <button type="button" className="btn" disabled={stage === 'syncing'} onClick={() => onDone(stage === 'done')}>
              {stage === 'done' ? 'Open my dashboard' : 'Close'}
            </button>
          </div>
        </>
      )}
    </dialog>
  )
}

/* ---------- connected real accounts ---------- */

function LiveAccount({ account, onChanged }) {
  const [busy, setBusy] = useState(null)
  const [confirming, setConfirming] = useState(false)

  async function run(kind, task) {
    setBusy(kind)
    try {
      await task()
    } finally {
      setBusy(null)
      onChanged()
    }
  }

  const status =
    busy === 'sync' || account.status === 'syncing'
      ? { text: 'Syncing', className: 'badge' }
      : account.status === 'error'
        ? { text: 'Needs attention', className: 'badge badge-open' }
        : account.last_synced_at
          ? { text: 'Connected', className: 'badge badge-approved' }
          : { text: 'Not synced yet', className: 'badge' }

  return (
    <li className={`provider live${account.status === 'error' ? ' is-error' : ' is-connected'}`}>
      <div className="provider-top">
        <ProviderMark id={account.provider} />
        <span className={status.className}>{status.text}</span>
      </div>
      <h2>{account.label}</h2>
      <p className="provider-meta">
        {account.provider_name}, {account.account_ref}
        <br />
        Keys {account.hint}
        {account.last_synced_at && (
          <>
            <br />
            {account.resource_count} resources, about {money(account.monthly_cost)} in the last 30 days. Synced{' '}
            {timestamp(account.last_synced_at)}.
          </>
        )}
      </p>
      {account.status === 'error' && <p className="form-error">{account.last_error}</p>}
      {account.warnings?.length > 0 && (
        <details className="notes" open={account.warnings.length > 1}>
          <summary>{account.warnings.length > 1 ? 'Some things could not be read' : 'Notes'}</summary>
          <ul>
            {account.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
      )}
      <div className="rec-buttons">
        <button type="button" className="btn btn-small" disabled={!!busy} onClick={() => run('sync', () => api.post(`/cloud-accounts/${account.id}/sync`))}>
          {busy === 'sync' ? 'Syncing…' : 'Sync now'}
        </button>
        {confirming ? (
          <button type="button" className="btn btn-ghost btn-small danger" disabled={!!busy} onClick={() => run('remove', () => api.delete(`/cloud-accounts/${account.id}`))}>
            Yes, remove it and its keys
          </button>
        ) : (
          <button type="button" className="btn btn-ghost btn-small" disabled={!!busy} onClick={() => setConfirming(true)}>
            Remove
          </button>
        )}
      </div>
    </li>
  )
}

/* ---------- the page ---------- */

export default function Connections({ user, connections, cloudAccounts, refresh, welcome = false }) {
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState(null)

  async function toggleSample(provider) {
    setError(null)
    try {
      if (provider.connected) await api.delete(`/connections/${provider.id}`)
      else await api.post('/connections', { provider: provider.id })
      refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <>
      {welcome ? (
        <PageHeader title={`Welcome, ${firstName(user.name)}. Let’s connect your cloud.`}>
          CloudLens needs to see a bill before it can help. Connect your AWS, Azure or Google Cloud account with
          read-only keys, or try a sample account first.
        </PageHeader>
      ) : (
        <PageHeader title="Cloud connections">
          The accounts CloudLens reads. Your dashboard combines everything connected here.
        </PageHeader>
      )}

      {error && (
        <p className="state state-error" role="alert">
          That did not save. {error}
        </p>
      )}

      <Loader requests={[connections, cloudAccounts]}>
        {() => {
          const live = cloudAccounts.data
          return (
            <>
              <section className="conn-section">
                <div className="section-head">
                  <div>
                    <h2>Your cloud accounts</h2>
                    <p className="panel-note">Real bills and servers, read with read-only keys.</p>
                  </div>
                  {live.enabled && (
                    <button type="button" className="btn" onClick={() => setAdding(true)}>
                      Connect a cloud account
                    </button>
                  )}
                </div>
                {!live.enabled && (
                  <p className="state">Connecting real accounts is switched off on this server (the encryption key is not set).</p>
                )}
                {live.enabled && live.accounts.length === 0 && (
                  <p className="state">
                    No real accounts yet. Choose <strong>Connect a cloud account</strong> and follow the steps; it takes
                    about five minutes.
                  </p>
                )}
                {live.accounts.length > 0 && (
                  <ul className="providers">
                    {live.accounts.map((account) => (
                      <LiveAccount key={account.id} account={account} onChanged={refresh} />
                    ))}
                  </ul>
                )}
              </section>

              <section className="conn-section">
                <div>
                  <h2>Sample accounts</h2>
                  <p className="panel-note">A made-up company for trying CloudLens and for demos. No keys needed.</p>
                </div>
                <ul className="providers">
                  {connections.data.map((p) => (
                    <li key={p.id} className={`provider${p.connected ? ' is-connected' : ''}`}>
                      <div className="provider-top">
                        <ProviderMark id={p.id} />
                        {p.connected ? <span className="badge badge-approved">Connected</span> : <span className="badge">Sample</span>}
                      </div>
                      <h2>Sample {p.name}</h2>
                      <p className="provider-meta">
                        {p.resource_count} resources, about {money(p.monthly_cost)} a month.
                        {p.connected && ` Connected ${fullDay(p.connected_at)}.`}
                      </p>
                      <button type="button" className={p.connected ? 'btn btn-ghost btn-small' : 'btn btn-ghost'} onClick={() => toggleSample(p)}>
                        {p.connected ? 'Disconnect' : 'Use sample data'}
                      </button>
                    </li>
                  ))}
                </ul>
              </section>

              <AddAccountDialog
                open={adding}
                policy={live.aws_policy}
                onClose={() => {
                  setAdding(false)
                  refresh()
                }}
                onDone={(connected) => {
                  setAdding(false)
                  refresh()
                  if (connected) window.location.hash = '#/home'
                }}
              />
            </>
          )
        }}
      </Loader>
    </>
  )
}
