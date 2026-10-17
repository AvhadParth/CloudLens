import { useEffect, useState } from 'react'

export const LOGGED_OUT_EVENT = 'cloudlens:logged-out'

const STARTING_UP = new Set([502, 503, 504])
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

async function send(path, options) {
  try {
    return await fetch(`/api${path}`, options)
  } catch {
    return null // network error
  }
}

async function request(path, options) {
  let response = await send(path, options)
  // The server can take a few seconds to wake up after a quiet spell; try once more.
  if (!response || STARTING_UP.has(response.status)) {
    await wait(1500)
    response = await send(path, options)
  }
  if (!response) {
    throw new Error('We could not reach the server. Check your connection and try again.')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    // The login expired (or the server restarted): send the person back to the login page.
    if (response.status === 401 && !path.startsWith('/auth/')) window.dispatchEvent(new Event(LOGGED_OUT_EVENT))
    const error = new Error(typeof body.detail === 'string' ? body.detail : 'Something went wrong. Please try again.')
    error.status = response.status
    throw error
  }
  return response.json()
}

export const api = {
  get: (path) => request(path),
  post: (path, body) =>
    request(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    }),
  delete: (path) => request(path, { method: 'DELETE' }),
}

/** Fetch `path` and refetch whenever `version` changes (bumped after a decision is saved). A null path waits. */
export function useApi(path, version = 0) {
  const [state, setState] = useState({ data: null, error: null, loading: true })

  useEffect(() => {
    if (!path) {
      setState({ data: null, error: null, loading: true })
      return undefined
    }
    let cancelled = false
    api
      .get(path)
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error) => !cancelled && setState((s) => ({ data: s.data, error: error.message, loading: false })))
    return () => {
      cancelled = true
    }
  }, [path, version])

  return state
}
