"use client"

import { useCallback, useEffect, useReducer, useRef, useState } from "react"

import { streamChat } from "./api"
import { revealLength } from "./stream-presentation"
import {
  initialSessionState,
  sessionReducer,
  collectionSessionKey,
  sessionKey,
  type SessionAction,
  type SessionTarget,
} from "./session-store"
import type { ChatEvent, HistoryMessage, Turn } from "./types"

const CITATION_MARKER = /\[S(\d+)\]/g

function citedLabelsInAnswer(turn: Turn, answer: string): string[] {
  const availableLabels = new Set(
    turn.segments.map((segment) => segment.label)
  )
  const seenLabels = new Set<string>()
  const citedLabels: string[] = []

  for (const match of answer.matchAll(CITATION_MARKER)) {
    const label = `S${Number(match[1])}`
    if (availableLabels.has(label) && !seenLabels.has(label)) {
      seenLabels.add(label)
      citedLabels.push(label)
    }
  }
  return citedLabels
}

function emptyTurn(question: string): Turn {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    mode: "mrag",
    question,
    answer: "",
    stages: [],
    route: null,
    segments: [],
    grounded: false,
    pageAddressed: false,
    requestedPage: null,
    topScore: 0,
    cited: [],
    provenance: null,
    timings: {},
    models: null,
    error: null,
    streaming: true,
  }
}

type ActiveRequest = {
  controller: AbortController
  sessionKey: string
  turn: Turn
  tokenBuffer: string
  animationFrame: number | null
  lastRevealAt: number
  discard: boolean
}

function reduceTurn(turn: Turn, event: Exclude<ChatEvent, { type: "token" }>): Turn {
  switch (event.type) {
    case "stage": {
      const stages = turn.stages.filter((entry) => entry.stage !== event.stage)
      return {
        ...turn,
        stages: [...stages, { stage: event.stage, status: event.status }],
      }
    }
    case "route":
      return {
        ...turn,
        route: {
          route: event.route,
          search_query: event.search_query,
          page: event.page,
          confidence: event.confidence,
          reason: event.reason,
          fallback: event.fallback,
        },
      }
    case "evidence":
      return {
        ...turn,
        segments: event.segments,
        grounded: event.grounded,
        pageAddressed: event.page_addressed,
        requestedPage: event.requested_page,
        topScore: event.top_score,
      }
    case "done":
      return {
        ...turn,
        answer: event.answer || turn.answer,
        cited: event.cited,
        provenance: event.provenance,
        timings: event.timings_ms,
        models: event.models,
        streaming: false,
      }
    case "error":
      return { ...turn, error: event.message, streaming: false }
  }
}

/** Keep each library conversation independent of individual PDF conversations. */
export function useSession() {
  const [session, dispatch] = useReducer(sessionReducer, initialSessionState)
  const [activeTurn, setActiveTurn] = useState<Turn | null>(null)
  const [running, setRunning] = useState(false)
  const activeTargetRef = useRef<SessionTarget | null>(null)
  const requestRef = useRef<ActiveRequest | null>(null)

  const dispatchSession = useCallback((action: SessionAction) => {
    dispatch(action)
  }, [])

  const publish = useCallback((request: ActiveRequest) => {
    if (
      requestRef.current === request &&
      activeTargetRef.current !== null &&
      sessionKey(activeTargetRef.current) === request.sessionKey
    ) {
      setActiveTurn(request.turn)
    }
  }, [])

  const flush = useCallback(
    (request: ActiveRequest, immediate = false) => {
      request.animationFrame = null
      if (!request.tokenBuffer) return
      const now = performance.now()
      const count = immediate || document.hidden || window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? request.tokenBuffer.length
        : revealLength(request.tokenBuffer, now - request.lastRevealAt)
      request.lastRevealAt = now
      const pendingTokens = request.tokenBuffer.slice(0, count)
      request.tokenBuffer = request.tokenBuffer.slice(count)
      const accumulatedAnswer = request.turn.answer + pendingTokens
      request.turn = {
        ...request.turn,
        answer: accumulatedAnswer,
        cited: citedLabelsInAnswer(request.turn, accumulatedAnswer),
      }
      publish(request)
    },
    [publish]
  )

  // Pace large network chunks as well as batching small deltas. Keep receiving
  // SSE while the display catches up, including after the server's done frame.
  const scheduleFlush = useCallback(
    (request: ActiveRequest) => {
      if (request.animationFrame !== null) return
      const tick = () => {
        flush(request)
        if (request.tokenBuffer && !request.discard) {
          request.animationFrame = requestAnimationFrame(tick)
        }
      }
      request.animationFrame = requestAnimationFrame(tick)
    },
    [flush]
  )

  const abandonRequest = useCallback(() => {
    const request = requestRef.current
    if (!request) return
    request.discard = true
    request.controller.abort()
    if (request.animationFrame !== null) {
      cancelAnimationFrame(request.animationFrame)
      request.animationFrame = null
    }
    request.tokenBuffer = ""
    requestRef.current = null
    setRunning(false)
  }, [])

  const cancel = useCallback(() => {
    requestRef.current?.controller.abort()
  }, [])

  const selectDocument = useCallback(
    (doc: string) => {
      if (activeTargetRef.current?.scope === "document" && doc === activeTargetRef.current.doc) return
      abandonRequest()
      activeTargetRef.current = { scope: "document", doc }
      setActiveTurn(null)
      dispatchSession({ type: "select_document", doc })
    },
    [abandonRequest, dispatchSession]
  )

  const selectCollection = useCallback(
    (corpusId: string) => {
      if (activeTargetRef.current?.scope === "collection" && corpusId === activeTargetRef.current.corpusId) return
      abandonRequest()
      activeTargetRef.current = { scope: "collection", corpusId }
      setActiveTurn(null)
      dispatchSession({ type: "select_collection", corpusId })
    },
    [abandonRequest, dispatchSession]
  )

  const newSession = useCallback(() => {
    const target = activeTargetRef.current
    if (!target) return
    abandonRequest()
    setActiveTurn(null)
    dispatchSession({ type: "clear_thread", sessionKey: sessionKey(target) })
  }, [abandonRequest, dispatchSession])

  const run = useCallback(
    async (message: string) => {
      const target = activeTargetRef.current
      if (!target || requestRef.current) return
      const key = sessionKey(target)
      const scope = target.scope

      // A library owns one history across all its PDFs, without importing
      // unrelated conversations from a document or a different library.
      const sessionThread = session.threads[key] ?? []
      const history: HistoryMessage[] = sessionThread.filter((turn) => !turn.error && (turn.scope ?? "document") === scope).flatMap((turn) => [
        { role: "user" as const, content: turn.question },
        { role: "assistant" as const, content: turn.answer },
      ])

      const request: ActiveRequest = {
        controller: new AbortController(),
        sessionKey: key,
        turn: { ...emptyTurn(message), scope },
        tokenBuffer: "",
        animationFrame: null,
        lastRevealAt: performance.now(),
        discard: false,
      }
      requestRef.current = request
      setRunning(true)
      setActiveTurn(request.turn)

      try {
        for await (const event of streamChat({
          message,
          mode: "mrag",
          doc: target.scope === "document" ? target.doc : null,
          corpusId: target.scope === "collection" ? target.corpusId : null,
          scope,
          k: scope === "collection" ? 8 : 5,
          history,
          signal: request.controller.signal,
        })) {
          if (event.type === "token") {
            request.tokenBuffer += event.text
            scheduleFlush(request)
            continue
          }

          if (event.type === "done") {
            // Do not replace the paced answer with the entire final response.
            // Abort and hidden tabs must not get stuck waiting for animation.
            while (request.tokenBuffer && !request.controller.signal.aborted) {
              if (document.hidden) {
                if (request.animationFrame !== null) cancelAnimationFrame(request.animationFrame)
                flush(request, true)
                break
              }
              await new Promise((resolve) => setTimeout(resolve, 16))
            }
            if (request.controller.signal.aborted) {
              throw new DOMException("Aborted", "AbortError")
            }
          }
          request.turn = reduceTurn(request.turn, event)
          publish(request)
        }
      } catch (error) {
        request.turn = {
          ...request.turn,
          error: (error as Error).name === "AbortError"
            ? "Stopped. Any text shown is an unfinished answer."
            : (error as Error).message,
          streaming: false,
        }
        publish(request)
      } finally {
        if (request.animationFrame !== null) {
          cancelAnimationFrame(request.animationFrame)
          request.animationFrame = null
        }
        flush(request, true)
        request.turn = { ...request.turn, streaming: false }

        if (!request.discard) {
          dispatchSession({ type: "append_turn", sessionKey: key, turn: request.turn })
        }

        if (requestRef.current === request) {
          requestRef.current = null
          setRunning(false)
          setActiveTurn(null)
        }
      }
    },
    [dispatchSession, flush, publish, scheduleFlush, session.threads]
  )

  useEffect(
    () => () => {
      const request = requestRef.current
      if (!request) return
      request.discard = true
      request.controller.abort()
      if (request.animationFrame !== null) {
        cancelAnimationFrame(request.animationFrame)
      }
    },
    []
  )

  const activeKey = session.activeCollection
    ? collectionSessionKey(session.activeCollection)
    : session.activeDoc
  const thread = activeKey
    ? (session.threads[activeKey] ?? [])
    : []

  return {
    activeDoc: session.activeDoc,
    activeCollection: session.activeCollection,
    threads: session.threads,
    thread,
    activeTurn,
    running,
    selectDocument,
    selectCollection,
    newSession,
    run,
    cancel,
  }
}
