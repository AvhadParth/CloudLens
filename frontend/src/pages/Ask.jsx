import { useEffect, useRef, useState } from 'react'
import { api, useApi } from '../api.js'
import { PageHeader } from '../components/common.jsx'

export default function Ask() {
  const suggestions = useApi('/assistant/suggestions')
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef(null)

  useEffect(() => {
    if (messages.length) end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages])

  async function ask(question) {
    const text = question.trim()
    if (!text || busy) return
    setDraft('')
    setBusy(true)
    setMessages((m) => [...m, { from: 'you', text }])
    try {
      const reply = await api.post('/assistant', { question: text })
      setMessages((m) => [...m, { from: 'assistant', ...reply, text: reply.answer }])
    } catch (e) {
      setMessages((m) => [...m, { from: 'assistant', text: `That question did not go through. ${e.message}`, items: [], suggestions: [] }])
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title="Ask CloudLens">
        Ask about your bill the way you would ask a colleague. Every answer is worked out from your data.
      </PageHeader>

      <section className="chat" aria-label="Conversation">
        <div className="chat-log" aria-live="polite">
          {messages.length === 0 && <p className="state">Tap a question below, or type your own.</p>}
          {messages.map((m, i) => (
            <div key={i} className={`msg msg-${m.from}`}>
              <p>{m.text}</p>
              {m.items?.length > 0 && (
                <ul className="msg-items">
                  {m.items.map((item) => (
                    <li key={item.label}>
                      <span>
                        {item.label}
                        <small>{item.detail}</small>
                      </span>
                      <b>{item.value}</b>
                    </li>
                  ))}
                </ul>
              )}
              {m.suggestions?.length > 0 && (
                <div className="chips">
                  {m.suggestions.map((s) => (
                    <button key={s} type="button" onClick={() => ask(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              )}
              {m.from === 'assistant' && m.intent && (
                <p className="msg-why">
                  Understood as a question about “{m.intent.replace('_', ' ')}” ({Math.round(m.confidence * 100)}% match).
                </p>
              )}
            </div>
          ))}
          <div ref={end} />
        </div>

        <form
          className="chat-form"
          onSubmit={(e) => {
            e.preventDefault()
            ask(draft)
          }}
        >
          <label htmlFor="question">Your question</label>
          <div className="chat-row">
            <input
              id="question"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={300}
              autoComplete="off"
              placeholder="How much can we save?"
            />
            <button type="submit" className="btn" disabled={busy || !draft.trim()}>
              Ask
            </button>
          </div>
        </form>

        {suggestions.data && (
          <div className="chips" aria-label="Questions you can ask">
            {suggestions.data.map((s) => (
              <button key={s} type="button" onClick={() => ask(s)} disabled={busy}>
                {s}
              </button>
            ))}
          </div>
        )}
      </section>
    </>
  )
}
