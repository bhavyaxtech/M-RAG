import type { ChatEvent, HistoryMessage, Meta, Mode } from "./types"

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ??
  (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "")

export function imageUrl(path: string | null): string | null {
  if (!path) return null
  return path.startsWith("http") ? path : `${API_BASE}${path}`
}

export async function fetchMeta(signal?: AbortSignal): Promise<Meta> {
  const response = await fetch(`${API_BASE}/api/meta`, { signal })
  if (!response.ok) {
    throw new Error(`Corpus metadata unavailable (${response.status})`)
  }
  return (await response.json()) as Meta
}

export type StreamChatOptions = {
  message: string
  mode: Mode
  doc: string | null
  corpusId?: string | null
  scope?: "document" | "collection"
  history?: HistoryMessage[]
  k?: number
  signal?: AbortSignal
}

/**
 * Stream one turn from the agent service.
 *
 * The transport is SSE over POST, so EventSource cannot be used. Frames are
 * split on the blank-line delimiter and any partial trailing frame is carried
 * into the next chunk, because a network chunk boundary can fall anywhere.
 */
export async function* streamChat({
  message,
  mode,
  doc,
  corpusId = null,
  scope = "document",
  history = [],
  k = 5,
  signal,
}: StreamChatOptions): AsyncGenerator<ChatEvent> {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, mode, doc, corpus_id: corpusId, scope, history, k }),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(
      `The answer service is unavailable (${response.status}). Please try again.`
    )
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() ?? ""
      // Some proxies omit the final blank line. Do not drop the done event.
      if (done && buffer.trim()) frames.push(buffer)

      for (const frame of frames) {
        const payload = frame
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n")
        if (!payload) continue

        let event: ChatEvent
        try {
          event = JSON.parse(payload) as ChatEvent
          if (!event || typeof event !== "object" || typeof event.type !== "string") {
            throw new Error("Invalid event")
          }
        } catch {
          throw new Error("The response could not be read completely. Please try again.")
        }
        yield event
        if (event.type === "done" || event.type === "error") return
      }
      if (done) break
    }
    throw new Error("The connection ended before the answer finished. Please try again.")
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
