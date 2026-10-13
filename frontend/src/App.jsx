import { useEffect, useState } from 'react'
import { api, LOGGED_OUT_EVENT, useApi } from './api.js'
import { Icon, Logo } from './components/art.jsx'
import Landing from './pages/Landing.jsx'
import Auth from './pages/Auth.jsx'
import Home from './pages/Home.jsx'
import Save from './pages/Save.jsx'
import YourCloud from './pages/YourCloud.jsx'
import Bills from './pages/Bills.jsx'
import Ask from './pages/Ask.jsx'
import History from './pages/History.jsx'

const APP_ROUTES = [
  { path: 'home', label: 'Overview', short: 'Home', icon: 'home', page: Home },
  { path: 'save', label: 'Ways to save', short: 'Save', icon: 'save', page: Save },
  { path: 'cloud', label: 'Your cloud', short: 'Cloud', icon: 'cloud', page: YourCloud },
  { path: 'bills', label: 'Next bills', short: 'Bills', icon: 'bills', page: Bills },
  { path: 'ask', label: 'Ask', icon: 'ask', page: Ask },
  { path: 'history', label: 'History', icon: 'history', page: History },
]
const PUBLIC_ROUTES = ['', 'login', 'signup']

function currentPath() {
  const path = window.location.hash.replace(/^#\/?/, '')
  return PUBLIC_ROUTES.includes(path) || APP_ROUTES.some((r) => r.path === path) ? path : ''
}

const go = (path) => {
  window.location.hash = `#/${path}`
}

function AppShell({ user, path, onLogout }) {
  // Bumped after every approve / skip / undo so all pages refetch fresh numbers.
  const [version, setVersion] = useState(0)
  const summary = useApi('/summary', version)
  const recommendations = useApi('/recommendations', version)
  const route = APP_ROUTES.find((r) => r.path === path)
  const open = recommendations.data?.filter((r) => r.status === 'open').length
  const Page = route.page
  const closeMenu = (event) => event.currentTarget.closest('[popover]').hidePopover()

  useEffect(() => {
    document.title = `${route.label} | CloudLens`
  }, [route])

  return (
    <div className="app">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="sidebar">
        <a className="brand" href="#/home">
          <Logo />
          CloudLens
        </a>
        <nav className="mainnav" aria-label="Main">
          <ul>
            {APP_ROUTES.map((r) => (
              <li key={r.path} className={r.path === 'history' ? 'nav-extra' : undefined}>
                <a href={`#/${r.path}`} aria-current={r.path === path ? 'page' : undefined}>
                  <Icon name={r.icon} />
                  <span className="nav-long">{r.label}</span>
                  <span className="nav-short">{r.short ?? r.label}</span>
                  {r.path === 'save' && open > 0 && <span className="count">{open}</span>}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <p className="sidebar-note">Practice mode. Sample data, and nothing real is changed.</p>
        <button type="button" className="userchip" popoverTarget="user-menu" aria-label={`Account menu for ${user.name}`}>
          <span className="avatar" aria-hidden="true">
            {user.name[0].toUpperCase()}
          </span>
          <span className="userchip-text">
            <strong>{user.name}</strong>
            <span>{user.email}</span>
          </span>
        </button>
        <div id="user-menu" popover="auto" className="usermenu">
          <p className="usermenu-who">
            <strong>{user.name}</strong>
            {user.email}
          </p>
          <a href="#/history" onClick={closeMenu}>
            History
          </a>
          <a href="#/" onClick={closeMenu}>
            Homepage
          </a>
          <button type="button" onClick={onLogout}>
            Log out
          </button>
        </div>
      </aside>

      <main id="main" tabIndex={-1}>
        <Page
          user={user}
          summary={summary}
          recommendations={recommendations}
          version={version}
          refresh={() => setVersion((v) => v + 1)}
        />
        <p className="footnote">
          Practice mode: CloudLens is running on sample data. Savings are estimates, and approving a fix only records
          your choice. Nothing real is switched off.
        </p>
      </main>
    </div>
  )
}

export default function App() {
  const [path, setPath] = useState(currentPath)
  // undefined = still checking, null = logged out, object = logged in
  const [user, setUser] = useState(undefined)

  useEffect(() => {
    api
      .get('/auth/me')
      .then(setUser)
      .catch(() => setUser(null))

    const onHash = () => {
      setPath(currentPath())
      window.scrollTo(0, 0)
    }
    const onLoggedOut = () => setUser(null)
    window.addEventListener('hashchange', onHash)
    window.addEventListener(LOGGED_OUT_EVENT, onLoggedOut)
    return () => {
      window.removeEventListener('hashchange', onHash)
      window.removeEventListener(LOGGED_OUT_EVENT, onLoggedOut)
    }
  }, [])

  const isAppRoute = APP_ROUTES.some((r) => r.path === path)
  const isAuthRoute = path === 'login' || path === 'signup'

  // Keep people on pages that make sense for them.
  useEffect(() => {
    if (user === undefined) return
    if (user === null && isAppRoute) go('login')
    if (user && isAuthRoute) go('home')
  }, [user, isAppRoute, isAuthRoute])

  async function logout() {
    await api.post('/auth/logout').catch(() => {})
    setUser(null)
    go('')
  }

  if (user === undefined || (user === null && isAppRoute) || (user && isAuthRoute)) {
    return (
      <p className="state state-loading boot">
        <span className="spinner" aria-hidden="true" />
        Opening CloudLens…
      </p>
    )
  }
  if (isAppRoute) return <AppShell user={user} path={path} onLogout={logout} />
  if (isAuthRoute) return <Auth mode={path} onDone={setUser} />
  return <Landing user={user} />
}
