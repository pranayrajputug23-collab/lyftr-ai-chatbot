import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import App from './App.jsx'

const chatReply = (overrides = {}) => ({
  session_id: 'from-server',
  reply: 'A thoughtful response.',
  metadata: {
    resolution_source: 'LIVE_INFERENCE',
    model: 'openai/gpt-4o-mini',
    latency_ms: 321,
    input_tokens: 42,
    output_tokens: 8,
    key_id: 'key_1',
    fallback_attempts: 0,
  },
  ...overrides,
})

function mockJsonResponse(payload, status = 200) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  }))
}

describe('Lyftr chat', () => {
  it('sends only the latest message with a fresh session and renders all response metadata', async () => {
    mockJsonResponse(chatReply())
    render(<App />)
    const input = screen.getByTestId('chat-input')
    fireEvent.change(input, { target: { value: '  Help me think this through  ' } })
    fireEvent.click(screen.getByTestId('send-button'))

    expect(input.value).toBe('')
    const assistant = await screen.findByTestId('assistant-message')
    expect(assistant.textContent).toContain('A thoughtful response.')
    expect(screen.getByTestId('meta-source').textContent).toContain('LIVE_INFERENCE')
    expect(screen.getByTestId('meta-model').textContent).toContain('openai/gpt-4o-mini')
    expect(screen.getByTestId('meta-latency').textContent).toContain('321 ms')
    expect(screen.getByTestId('meta-input-tokens').textContent).toContain('42 in')
    expect(screen.getByTestId('meta-output-tokens').textContent).toContain('8 out')

    const [url, request] = fetch.mock.calls[0]
    expect(url).toMatch(/\/chat$/)
    const body = JSON.parse(request.body)
    expect(body).toEqual({ session_id: expect.stringMatching(/^s-/), message: 'Help me think this through' })
    expect(body).not.toHaveProperty('messages')
    expect(body).not.toHaveProperty('history')
  })

  it('sends the optional system prompt and submits with Enter', async () => {
    mockJsonResponse(chatReply())
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /system prompt/i }))
    fireEvent.change(screen.getByTestId('system-prompt-input'), { target: { value: 'Be concise.' } })
    const input = screen.getByTestId('chat-input')
    fireEvent.change(input, { target: { value: 'Hello' } })
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })

    await screen.findByTestId('assistant-message')
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toMatchObject({ message: 'Hello', system_prompt: 'Be concise.' })
  })

  it.each([
    [422, { detail: [{ loc: ['body', 'message'], msg: 'invalid' }] }, 'Please enter a message between 1 and 4,000 characters.'],
    [503, { detail: 'all providers unavailable' }, 'The AI service is temporarily unavailable. Please try again in a moment.'],
  ])('shows a readable message for HTTP %s', async (status, payload, message) => {
    mockJsonResponse(payload, status)
    render(<App />)
    fireEvent.change(screen.getByTestId('chat-input'), { target: { value: 'Try this' } })
    fireEvent.click(screen.getByTestId('send-button'))
    expect((await screen.findByRole('alert')).textContent).toContain(message)
  })

  it('creates a different session after a fresh page mount', async () => {
    mockJsonResponse(chatReply())
    const firstRender = render(<App />)
    fireEvent.change(screen.getByTestId('chat-input'), { target: { value: 'First' } })
    fireEvent.keyDown(screen.getByTestId('chat-input'), { key: 'Enter', code: 'Enter' })
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
    const firstSessionId = JSON.parse(fetch.mock.calls[0][1].body).session_id

    firstRender.unmount()
    render(<App />)
    fireEvent.change(screen.getByTestId('chat-input'), { target: { value: 'Second' } })
    fireEvent.keyDown(screen.getByTestId('chat-input'), { key: 'Enter', code: 'Enter' })
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    const secondSessionId = JSON.parse(fetch.mock.calls[1][1].body).session_id
    expect(secondSessionId).not.toBe(firstSessionId)
  })
})
