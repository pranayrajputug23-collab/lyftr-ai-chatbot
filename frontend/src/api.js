const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()

export function getApiBaseUrl() {
  return configuredBaseUrl ? configuredBaseUrl.replace(/\/+$/, '') : ''
}

function describeValidation(detail) {
  if (Array.isArray(detail)) {
    const first = detail[0]
    if (first?.loc?.includes('message')) return 'Please enter a message between 1 and 4,000 characters.'
    if (first?.loc?.includes('session_id')) return 'This chat session is invalid. Please refresh and try again.'
    return first?.msg || 'Please check your message and try again.'
  }
  return typeof detail === 'string' ? detail : 'Please check your message and try again.'
}

export async function sendChatMessage({ sessionId, message, systemPrompt, signal }) {
  const baseUrl = getApiBaseUrl()
  if (!baseUrl) {
    throw new Error('The backend URL is not configured. Set VITE_API_BASE_URL and restart the frontend.')
  }

  const body = { session_id: sessionId, message }
  if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim()

  let response
  try {
    response = await fetch(`${baseUrl}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('Could not reach the chat service. Check your connection and try again.')
  }

  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 422) throw new Error(describeValidation(payload.detail))
    if (response.status === 503) {
      throw new Error('The AI service is temporarily unavailable. Please try again in a moment.')
    }
    throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Something went wrong. Please try again.')
  }
  return payload
}
