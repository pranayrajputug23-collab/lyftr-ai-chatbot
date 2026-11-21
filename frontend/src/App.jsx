import { useEffect, useRef, useState } from 'react'
import { getApiBaseUrl, sendChatMessage } from './api.js'

const suggestions = [
  { label: 'Write something', prompt: 'Help me write a clear, thoughtful email about…' },
  { label: 'Explore an idea', prompt: 'I have an idea I want to think through: ' },
  { label: 'Make a plan', prompt: 'Help me make a practical plan for…' },
]

function createSessionId() {
  if (globalThis.crypto?.randomUUID) return `s-${globalThis.crypto.randomUUID()}`
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

function createMessageId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function Icon({ name, size = 18 }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true }
  if (name === 'sparkle') return <svg {...common}><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" /><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z" /></svg>
  if (name === 'arrow') return <svg {...common}><path d="M12 19V5" /><path d="m6 11 6-6 6 6" /></svg>
  if (name === 'chevron') return <svg {...common}><path d="m7 10 5 5 5-5" /></svg>
  if (name === 'plus') return <svg {...common}><path d="M12 5v14M5 12h14" /></svg>
  if (name === 'copy') return <svg {...common}><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg>
  return <svg {...common}><circle cx="12" cy="12" r="9" /><path d="M12 8v4l2.5 1.5" /></svg>
}

function AssistantMark({ small = false }) {
  return <div className={`assistant-mark${small ? ' assistant-mark--small' : ''}`}><Icon name="sparkle" size={small ? 15 : 18} /></div>
}

function ErrorNotice({ children }) {
  return <div className="error-notice" role="alert"><span className="error-dot" />{children}</div>
}

function Metadata({ metadata }) {
  if (!metadata) return null
  return (
    <div className="metadata" aria-label="Response metadata">
      <span className={`source-pill ${metadata.resolution_source === 'LLM_CACHE' ? 'source-pill--cache' : ''}`} data-testid="meta-source">
        <span className="source-dot" />{metadata.resolution_source}
      </span>
      <span className="meta-item meta-model" data-testid="meta-model" title={metadata.model}>{metadata.model}</span>
      <span className="meta-item" data-testid="meta-latency"><Icon name="clock" size={13} />{metadata.latency_ms} ms</span>
      <span className="meta-item" data-testid="meta-input-tokens">{metadata.input_tokens} in</span>
      <span className="meta-item" data-testid="meta-output-tokens">{metadata.output_tokens} out</span>
    </div>
  )
}

function Message({ message }) {
  if (message.role === 'user') {
    return <article className="message-row message-row--user"><div className="user-bubble">{message.content}</div></article>
  }

  return (
    <article className="message-row message-row--assistant" data-testid="assistant-message">
      <AssistantMark small />
      <div className="assistant-content">
        <div className="message-copy">{message.content}</div>
        <Metadata metadata={message.metadata} />
      </div>
    </article>
  )
}

function LoadingMessage() {
  return (
    <div className="message-row message-row--assistant loading-row" aria-live="polite" aria-label="Lyftr is thinking">
      <AssistantMark small />
      <div className="thinking"><span /><span /><span /><small>Thinking</small></div>
    </div>
  )
}

export default function App() {
  // Initializer runs once per document load, so each page load starts a new session.
  const [sessionId] = useState(createSessionId)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [promptOpen, setPromptOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [copiedId, setCopiedId] = useState(null)
  const transcriptEnd = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, loading, error])

  async function handleSend(value = input) {
    const content = value.trim()
    if (!content || loading) return

    setInput('')
    setError('')
    setMessages((current) => [...current, { id: createMessageId(), role: 'user', content }])
    setLoading(true)

    try {
      // Only the latest user message is sent. The backend retrieves earlier turns from SQLite.
      const result = await sendChatMessage({
        sessionId,
        message: content,
        systemPrompt,
      })
      setMessages((current) => [...current, {
        id: createMessageId(),
        role: 'assistant',
        content: result.reply,
        metadata: result.metadata,
      }])
    } catch (sendError) {
      setError(sendError.message || 'Your message could not be sent. Please try again.')
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      handleSend()
    }
  }

  async function copyMessage(message) {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopiedId(message.id)
      window.setTimeout(() => setCopiedId(null), 1400)
    } catch {
      setError('Clipboard access is unavailable in this browser.')
    }
  }

  const apiConfigured = Boolean(getApiBaseUrl())

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top" aria-label="Lyftr AI home">
          <span className="brand-symbol"><Icon name="sparkle" size={18} /></span>
          <span>lyftr<span className="brand-ai">.ai</span></span>
        </a>

        <button className="new-chat-button" type="button" onClick={() => window.location.reload()}>
          <Icon name="plus" size={16} /><span>New conversation</span><kbd>⌘ K</kbd>
        </button>

        <div className="sidebar-section-label">WORKSPACE</div>
        <div className="workspace-card">
          <div className="workspace-icon"><Icon name="sparkle" size={16} /></div>
          <div><strong>Personal space</strong><span>Private workspace</span></div>
          <Icon name="chevron" size={15} />
        </div>

        <div className="sidebar-bottom">
          <div className="sidebar-note"><span className="online-dot" />Ready when you are</div>
          <div className="profile-card">
            <div className="profile-avatar">L</div>
            <div><strong>Lyftr AI</strong><span>Personal plan</span></div>
            <span className="profile-menu">···</span>
          </div>
        </div>
      </aside>

      <main className="main-panel" id="top">
        <header className="topbar">
          <div className="breadcrumb"><span>Personal space</span><span className="breadcrumb-slash">/</span><strong>New conversation</strong></div>
          <div className="topbar-right"><span className="model-indicator"><span className="model-indicator-dot" />AI assistant</span><button className="icon-button" aria-label="More options" type="button">···</button></div>
        </header>

        <section className={`chat-layout${messages.length ? ' chat-layout--active' : ''}`} aria-label="AI conversation">
          {messages.length === 0 ? (
            <div className="welcome-block">
              <div className="welcome-orb"><span className="orb-ring orb-ring--one" /><span className="orb-ring orb-ring--two" /><AssistantMark /></div>
              <div className="eyebrow"><span />YOUR THOUGHT PARTNER</div>
              <h1>A little more clarity.<br /><span>One conversation away.</span></h1>
              <p className="welcome-description">Bring a question, a half-formed idea, or a task you’ve been putting off. We’ll work through it together.</p>
              <div className="suggestion-grid">
                {suggestions.map((suggestion, index) => (
                  <button className="suggestion-card" type="button" key={suggestion.label} onClick={() => { setInput(suggestion.prompt); inputRef.current?.focus() }}>
                    <span className={`suggestion-icon suggestion-icon--${index}`}><Icon name={index === 0 ? 'copy' : index === 1 ? 'sparkle' : 'arrow'} size={16} /></span>
                    <span><strong>{suggestion.label}</strong><small>{suggestion.prompt}</small></span>
                    <span className="suggestion-arrow">↗</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="transcript" aria-live="polite">
              {messages.map((message) => <Message key={message.id} message={message} />)}
              {loading && <LoadingMessage />}
              {error && <ErrorNotice>{error}</ErrorNotice>}
              <div ref={transcriptEnd} className="transcript-end" />
            </div>
          )}

          {!apiConfigured && <ErrorNotice>The backend URL is not configured. Copy <code>.env.example</code> to <code>.env.local</code> and set <code>VITE_API_BASE_URL</code>.</ErrorNotice>}
          {error && messages.length === 0 && <ErrorNotice>{error}</ErrorNotice>}

          <div className="composer-area">
            {promptOpen && (
              <div className="system-prompt-panel">
                <div className="system-prompt-heading"><div><span className="prompt-sparkle"><Icon name="sparkle" size={14} /></span><strong>System prompt</strong><small>Guide how Lyftr responds in this conversation.</small></div><button type="button" className="close-prompt" onClick={() => setPromptOpen(false)} aria-label="Close system prompt">×</button></div>
                <textarea
                  data-testid="system-prompt-input"
                  value={systemPrompt}
                  onChange={(event) => setSystemPrompt(event.target.value)}
                  placeholder="e.g. Be concise, ask clarifying questions, and use a warm tone."
                  rows={3}
                  maxLength={2000}
                />
              </div>
            )}
            <div className="composer">
              <textarea
                ref={inputRef}
                data-testid="chat-input"
                value={input}
                onChange={(event) => { setInput(event.target.value); if (error) setError('') }}
                onKeyDown={handleKeyDown}
                placeholder="Ask anything, or share what’s on your mind…"
                rows={1}
                maxLength={4000}
                disabled={loading}
                aria-label="Write your message"
              />
              <div className="composer-tools">
                <div className="composer-left-tools">
                  <button className={`prompt-toggle${promptOpen ? ' prompt-toggle--active' : ''}`} type="button" onClick={() => setPromptOpen((open) => !open)} aria-expanded={promptOpen}>
                    <Icon name="sparkle" size={14} /><span>System prompt</span>
                  </button>
                  <span className="composer-hint">Enter to send · Shift + Enter for a new line</span>
                </div>
                <div className="composer-right-tools">
                  {input.length > 0 && <span className="character-count">{input.length}/4000</span>}
                  <button className="send-button" data-testid="send-button" type="button" onClick={() => handleSend()} disabled={loading || !input.trim() || !apiConfigured} aria-label="Send message">
                    {loading ? <span className="send-spinner" /> : <Icon name="arrow" size={17} />}
                  </button>
                </div>
              </div>
            </div>
            <div className="composer-disclaimer">Lyftr can make mistakes. Check important information.</div>
          </div>
          {messages.length > 0 && !loading && messages.some((message) => message.role === 'assistant') && (
            <div className="last-actions">
              {[...messages].reverse().find((message) => message.role === 'assistant') && (
                <button type="button" className="copy-latest" onClick={() => copyMessage([...messages].reverse().find((message) => message.role === 'assistant'))}>
                  <Icon name="copy" size={13} />{copiedId ? 'Copied' : 'Copy latest response'}
                </button>
              )}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
