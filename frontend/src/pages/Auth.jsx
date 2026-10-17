import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { Icon, LensOrb, Logo, ProviderLogos } from '../components/art.jsx'

const COPY = {
  signup: {
    title: 'Create your account',
    lede: 'Free, and it takes under a minute.',
    button: 'Create account',
    busy: 'Creating your account…',
    switchText: 'Already have an account?',
    switchLink: 'Log in',
    switchTo: 'login',
    endpoint: '/auth/register',
  },
  login: {
    title: 'Welcome back',
    lede: 'Log in to see where your cloud money is going.',
    button: 'Log in',
    busy: 'Logging you in…',
    switchText: 'New to CloudLens?',
    switchLink: 'Create an account',
    switchTo: 'signup',
    endpoint: '/auth/login',
  },
}

export default function Auth({ mode, onDone }) {
  const copy = COPY[mode]
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    document.title = `${copy.title} | CloudLens`
    setError(null)
  }, [copy])

  const set = (field) => (event) => setForm((f) => ({ ...f, [field]: event.target.value }))

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const body = mode === 'signup' ? form : { email: form.email, password: form.password }
      onDone(await api.post(copy.endpoint, body))
    } catch (e) {
      setError(e.status === 422 ? 'Check your email address, and use a password of at least 8 characters.' : e.message)
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <aside className="auth-art">
        <LensOrb className="auth-orb" />
        <a className="brand" href="#/">
          <Logo />
          CloudLens
        </a>
        <div className="auth-pitch">
          <p className="auth-tagline">See exactly where your cloud money goes.</p>
          <ul className="ticks">
            <li>
              <Icon name="check" />
              Finds servers and storage nobody is using
            </li>
            <li>
              <Icon name="check" />
              Shows next month’s bill before it arrives
            </li>
            <li>
              <Icon name="check" />
              Explains every saving in plain English
            </li>
          </ul>
          <div className="works-with">
            <span>Works with</span>
            <ProviderLogos />
          </div>
        </div>
      </aside>

      <main className="auth-main">
        <a className="brand auth-brand-mobile" href="#/">
          <Logo />
          CloudLens
        </a>
        <form className="auth-card" onSubmit={submit}>
          <h1>{copy.title}</h1>
          <p className="lede">{copy.lede}</p>

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          {mode === 'signup' && (
            <label>
              Your name
              <input value={form.name} onChange={set('name')} autoComplete="name" required maxLength={60} placeholder="Your full name" />
            </label>
          )}
          <label>
            Email
            <input type="email" value={form.email} onChange={set('email')} autoComplete="email" required placeholder="you@company.com" />
          </label>
          <label>
            Password
            <span className="password-row">
              <input
                type={showPassword ? 'text' : 'password'}
                value={form.password}
                onChange={set('password')}
                autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                required
                minLength={8}
                maxLength={72}
              />
              <button type="button" className="password-toggle" onClick={() => setShowPassword((s) => !s)} aria-pressed={showPassword}>
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </span>
            {mode === 'signup' && <span className="hint">At least 8 characters.</span>}
          </label>

          <button type="submit" className="btn btn-big" disabled={busy}>
            {busy ? copy.busy : copy.button}
          </button>
          <p className="auth-switch">
            {copy.switchText} <a href={`#/${copy.switchTo}`}>{copy.switchLink}</a>
          </p>
        </form>
      </main>
    </div>
  )
}
