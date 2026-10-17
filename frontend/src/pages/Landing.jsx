import { useEffect } from 'react'
import { useApi } from '../api.js'
import { money } from '../format.js'
import { Icon, KindIcon, LensOrb, Logo, ProviderLogos, ProviderMark } from '../components/art.jsx'
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

const INTEGRATIONS = [
  {
    id: 'aws',
    name: 'Amazon Web Services',
    reads: 'Daily bill from Cost Explorer, EC2 servers and EBS disks in every region, and CloudWatch processor use.',
    keys: 'An IAM user with a short read-only policy',
  },
  {
    id: 'azure',
    name: 'Microsoft Azure',
    reads: 'Daily bill per resource from Cost Management, virtual machines, managed disks, and Azure Monitor processor use.',
    keys: 'A service principal with the built-in Reader role',
  },
  {
    id: 'gcp',
    name: 'Google Cloud',
    reads: 'Daily bill from the BigQuery billing export, Compute Engine servers and disks, and Cloud Monitoring processor use.',
    keys: 'A service account with viewer roles',
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
          <a href="#clouds" className="land-link">
            Clouds
          </a>
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

          <div className="works-with">
            <span>Works with</span>
            <ProviderLogos />
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

        <section className="band" id="clouds">
          <div className="band-head">
            <h2>Connect the clouds you already use.</h2>
            <p>A guided five-minute setup with read-only keys. CloudLens reads; it never changes anything in your account.</p>
          </div>
          <ul className="integrations">
            {INTEGRATIONS.map((item) => (
              <li key={item.id}>
                <ProviderMark id={item.id} size={56} />
                <h3>{item.name}</h3>
                <p>{item.reads}</p>
                <p className="integration-keys">
                  <Icon name="check" />
                  {item.keys}
                </p>
              </li>
            ))}
          </ul>
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
                Approving a fix never changes anything in your cloud
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
          A final-year B.Tech I.T. project. It reads cloud accounts with read-only keys and includes a sample company
          for demos. All savings are estimates.
        </p>
        <p className="trademark">
          Amazon Web Services, Microsoft Azure and Google Cloud and their logos are trademarks of their respective
          owners. CloudLens is an independent student project and is not affiliated with or endorsed by them.
        </p>
      </footer>
    </div>
  )
}
