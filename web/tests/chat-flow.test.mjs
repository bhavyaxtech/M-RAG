import assert from "node:assert/strict"
import { afterEach, test } from "node:test"

import { streamChat } from "../src/lib/api.ts"
import { collectionSessionKey, initialSessionState, sessionReducer, sessionKey } from "../src/lib/session-store.ts"

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

const encoder = new TextEncoder()
const doneEvent = { type: "done", answer: "Complete", cited: [], provenance: "general" }
const options = { message: "Question", mode: "mrag", doc: "lm317" }

function mockStream(chunks) {
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk)
      controller.close()
    },
  }))
}

async function collect() {
  const events = []
  for await (const event of streamChat(options)) events.push(event)
  return events
}

test("SSE decodes split UTF-8 characters and frames", async () => {
  const bytes = encoder.encode(`data: ${JSON.stringify({ type: "token", text: "10 µs" })}\n\ndata: ${JSON.stringify(doneEvent)}\n\n`)
  mockStream(Array.from(bytes, (byte) => new Uint8Array([byte])))
  assert.deepEqual(await collect(), [{ type: "token", text: "10 µs" }, doneEvent])
})

test("SSE accepts CRLF and a final event without a blank line", async () => {
  mockStream([": keepalive\r\n\r\ndata: {\"type\":\"token\",\"text\":\"Hello\"}\r\n\r\n", `data: ${JSON.stringify(doneEvent)}`])
  assert.equal((await collect()).at(-1).type, "done")
})

test("SSE supports multiline data fields", async () => {
  mockStream([`data: {"type":"token",\ndata: "text":"Hello"}\n\ndata: ${JSON.stringify(doneEvent)}\n\n`])
  assert.equal((await collect())[0].text, "Hello")
})

test("truncated responses do not silently count as completed answers", async () => {
  mockStream(['data: {"type":"token","text":"Partial"}\n\n'])
  await assert.rejects(collect, /before the answer finished/)
})

test("malformed frames surface a readable error", async () => {
  mockStream(["data: {broken}\n\n"])
  await assert.rejects(collect, /could not be read completely/)
})

test("server error is preserved as a terminal event", async () => {
  mockStream(['data: {"type":"error","message":"Model unavailable"}\n\n'])
  assert.deepEqual(await collect(), [{ type: "error", message: "Model unavailable" }])
})

test("a non-200 API response is reported", async () => {
  globalThis.fetch = async () => new Response("Unavailable", { status: 503 })
  await assert.rejects(collect, /503/)
})

test("production requests use the page's own server by default", async () => {
  let requestedUrl
  globalThis.fetch = async (url) => {
    requestedUrl = url
    return new Response(`data: ${JSON.stringify(doneEvent)}\n\n`)
  }
  await collect()
  assert.equal(requestedUrl, "/api/chat")
})

test("collection scope is transmitted with the anchor document", async () => {
  let payload
  globalThis.fetch = async (_url, request) => {
    payload = JSON.parse(request.body)
    return new Response(`data: ${JSON.stringify(doneEvent)}\n\n`)
  }
  for await (const _event of streamChat({ ...options, scope: "collection", k: 8 })) {}
  assert.equal(payload.doc, "lm317")
  assert.equal(payload.scope, "collection")
  assert.equal(payload.k, 8)
})

test("document conversations remain separate and duplicate turns are ignored", () => {
  const first = { id: "first", question: "LM317 question" }
  const second = { id: "second", question: "ESP32 question" }
  let state = sessionReducer(initialSessionState, { type: "append_turn", sessionKey: "lm317", turn: first })
  state = sessionReducer(state, { type: "append_turn", sessionKey: "esp32", turn: second })
  state = sessionReducer(state, { type: "append_turn", sessionKey: "lm317", turn: first })
  assert.deepEqual(state.threads.lm317, [first])
  assert.deepEqual(state.threads.esp32, [second])
  state = sessionReducer(state, { type: "clear_thread", sessionKey: "lm317" })
  assert.deepEqual(state.threads.lm317, [])
  assert.deepEqual(state.threads.esp32, [second])
})

test("library request selects its corpus without a PDF anchor", async () => {
  let payload
  globalThis.fetch = async (_url, request) => {
    payload = JSON.parse(request.body)
    return new Response(`data: ${JSON.stringify(doneEvent)}\n\n`)
  }
  const history = [{ role: "user", content: "Compare AN2594 and AN2557" }, { role: "assistant", content: "They serve different purposes." }]
  for await (const _event of streamChat({ ...options, doc: null, corpusId: "stm32", scope: "collection", k: 8, history })) {}
  assert.equal(payload.doc, null)
  assert.equal(payload.corpus_id, "stm32")
  assert.equal(payload.scope, "collection")
  assert.deepEqual(payload.history, history)
})

test("library history survives PDF navigation without mixing conversations", () => {
  const libraryKey = collectionSessionKey("stm32")
  const libraryTurn = { id: "library", scope: "collection", question: "Compare AN2594 and AN2557" }
  const documentTurn = { id: "document", scope: "document", question: "PA9 pin" }
  let state = sessionReducer(initialSessionState, { type: "select_collection", corpusId: "stm32" })
  assert.equal(state.activeDoc, null)
  assert.equal(state.activeCollection, "stm32")
  state = sessionReducer(state, { type: "append_turn", sessionKey: libraryKey, turn: libraryTurn })
  state = sessionReducer(state, { type: "select_document", doc: "stm32-ds5319" })
  assert.equal(state.activeCollection, null)
  state = sessionReducer(state, { type: "append_turn", sessionKey: "stm32-ds5319", turn: documentTurn })
  state = sessionReducer(state, { type: "select_collection", corpusId: "stm32" })
  assert.deepEqual(state.threads[libraryKey], [libraryTurn])
  assert.deepEqual(state.threads["stm32-ds5319"], [documentTurn])
  state = sessionReducer(state, { type: "clear_thread", sessionKey: libraryKey })
  assert.deepEqual(state.threads[libraryKey], [])
  assert.deepEqual(state.threads["stm32-ds5319"], [documentTurn])
  assert.notEqual(libraryKey, collectionSessionKey("hardware"))
  assert.equal(sessionKey({ scope: "collection", corpusId: "stm32" }), libraryKey)
  assert.equal(sessionKey({ scope: "document", doc: "stm32-ds5319" }), "stm32-ds5319")
})
