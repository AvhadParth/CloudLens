import { useEffect } from 'react'
import { useApi } from '../api.js'
import { money } from '../format.js'
import { Icon, KindIcon, LensOrb, Logo } from '../components/art.jsx'
import { BillStrip } from '../components/common.jsx'

const KINDS = [
  {
    kind: 'idle',
    title: 'Switched on, never used',
    text: 'Servers someone started months ago and forgot. They do no work, and the meter keeps running.',
  },
  {
    kind: 'oversized',
    title: 'Bigger than the job needs',
    text: 'Machines that never use more than a fraction of their power. A smaller size does the same work for half the price.',
  },
  {
    kind: 'always_on_dev',
    title: 'Left on overnight',
    text: 'Test machines that only matter during working hours, running through every night and weekend.',
  },
  {
    kind: 'unattached_storage',
    title: 'Storage nobody opens',
    text: 'Old disks connected to nothing. Nobody reads them, but they are billed every month.',
  },
]

const STEPS = [
  { title: 'It reads your bill', text: 'A year of costs, plus how hard each server actually worked.' },
  { title: 'It finds the waste', text: 'Clear checks pick out what is unused, too big, or left running for nothing.' },
  { title: 'You decide what to fix', text: 'Every finding comes with a reason and a saving. Approve the ones you agree with.' },
]

export default function Landing({ user }) {
  const preview = useApi('/public/preview')
  const p = preview.data
  const cta = user ? { href: '#/home', label: 'Open dashboard' } : { href: '#/signup', label: 'Get started free' }

  useEffect(() => {
    document.title = "CloudLens: stop paying for cloud you don't use"
  }, [])

  return (
    <div className="landing">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="land-nav">
        <a className="brand" href="#/">
          <Logo />
          CloudLens
        </a>
        <nav aria-label="Homepage">
          <a href="#finds" className="land-link">
            What it finds
          </a>
          <a href="#how" className="land-link">
            How it works
          </a>
          {!user && (
            <a href="#/login" className="land-link land-link-keep">
              Log in
            </a>
          )}
          <a href={cta.href} className="btn btn-small">
            {user ? 'Dashboard' : 'Sign up'}
          </a>
        </nav>
      </header>

      <main id="main">
        <section className="hero">
          <LensOrb className="hero-orb" />
          <p className="pill">Cloud cost clarity for teams of any size</p>
          <h1>Stop paying for cloud you don’t use.</h1>
          <p className="hero-sub">
            CloudLens reads your cloud bill, finds the servers and storage nobody is using, and shows you exactly
            what to switch off. In plain English.
          </p>
          <div className="hero-actions">
            <a href={cta.href} className="btn btn-big">
              {cta.label}
              <Icon name="arrow" />
            </a>
            {!user && (
              <a href="#/login" className="btn btn-ghost btn-big">
                Log in
              </a>
            )}
          </div>

          {p && (
            <div className="shot">
              <div className="shot-bar" aria-hidden="true">
                <i />
                <i />
                <i />
                <span>Sample company, last 30 days</span>
              </div>
              <div className="shot-body">
                <div className="shot-main">
                  <p className="label">You could stop wasting</p>
                  <p className="shot-number">
                    {money(p.monthly_waste)}
                    <span>a month</span>
                  </p>
                  <p className="shot-text">
                    {Math.round((p.monthly_waste / p.monthly_bill) * 100)}% of a {money(p.monthly_bill)} bill, across{' '}
                    {p.finding_count} of {p.resource_count} resources.
                  </p>
                  <BillStrip total={p.monthly_bill} open={p.monthly_waste} />
                </div>
                <ul className="shot-list">
                  {Object.entries(p.waste_by_kind).map(([kind, k]) => (
                    <li key={kind}>
                      <KindIcon kind={kind} size={36} />
                      <span>
                        {k.label}
                        <small>
                          {k.count} {k.count === 1 ? 'item' : 'items'}
                        </small>
                      </span>
                      <b>{money(k.saving)}</b>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </section>

        <section className="band" id="finds">
          <div className="band-head">
            <h2>Four kinds of waste, found automatically.</h2>
            <p>Most cloud bills carry the same four problems. CloudLens checks for each one and puts a price on it.</p>
          </div>
          <ul className="finds">
            {KINDS.map((k) => (
              <li key={k.kind}>
                <KindIcon kind={k.kind} />
                <h3>{k.title}</h3>
                <p>{k.text}</p>
                {p?.waste_by_kind[k.kind] && (
                  <p className="finds-price">
                    <b>{money(p.waste_by_kind[k.kind].saving)}</b> a month in the sample bill
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>

        <section className="band" id="how">
          <div className="band-head">
            <h2>From bill to savings in three steps.</h2>
          </div>
          <ol className="steps">
            {STEPS.map((step, i) => (
              <li key={step.title}>
                <span className="step-number">{i + 1}</span>
                <h3>{step.title}</h3>
                <p>{step.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="band duo">
          <div className="duo-copy">
            <h2>Ask a question. Get a straight answer.</h2>
            <p>
              No reports to decode. Ask the way you would ask a colleague, and see the numbers behind every answer.
            </p>
            <ul className="ticks">
              <li>
                <Icon name="check" />
                See next month’s bill before it arrives
              </li>
              <li>
                <Icon name="check" />
                Know which team spends the most
              </li>
              <li>
                <Icon name="check" />
                Try fixes safely: practice mode never touches a real server
              </li>
            </ul>
          </div>
          <div className="chat-demo" aria-label="Example conversation">
            <p className="msg msg-you">Which servers are not being used?</p>
            <div className="msg msg-assistant">
              <p>5 are switched on and being paid for, but doing almost nothing. Fixing all of them would save about $848 a month.</p>
            </div>
            <p className="msg msg-you">What will we spend next month?</p>
            <div className="msg msg-assistant">
              <p>About $10,637 if nothing changes.</p>
            </div>
          </div>
        </section>

        <section className="closer">
          <h2>Find your first saving today.</h2>
          <p>Create an account and explore the sample company in under a minute.</p>
          <a href={cta.href} className="btn btn-big">
            {cta.label}
            <Icon name="arrow" />
          </a>
        </section>
      </main>

      <footer className="land-footer">
        <span className="brand">
          <Logo size={26} />
          CloudLens
        </span>
        <p>
          A final-year B.Tech I.T. project. It runs on sample data, connects to no real cloud account, and all savings
          are estimates.
        </p>
      </footer>
    </div>
  )
}
