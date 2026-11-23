import type { Turn } from "./types"

export type SessionState = {
  activeDoc: string | null
  activeCollection: string | null
  threads: Record<string, Turn[]>
}

export type SessionTarget =
  | { scope: "document"; doc: string }
  | { scope: "collection"; corpusId: string }

export function collectionSessionKey(corpusId: string): string {
  return `collection:${corpusId}`
}

export function sessionKey(target: SessionTarget): string {
  return target.scope === "collection" ? collectionSessionKey(target.corpusId) : target.doc
}

export type SessionAction =
  | { type: "select_document"; doc: string }
  | { type: "select_collection"; corpusId: string }
  | { type: "append_turn"; sessionKey: string; turn: Turn }
  | { type: "clear_thread"; sessionKey: string }

export const initialSessionState: SessionState = {
  activeDoc: null,
  activeCollection: null,
  threads: {},
}

export function sessionReducer(
  state: SessionState,
  action: SessionAction
): SessionState {
  switch (action.type) {
    case "select_document":
      return action.doc === state.activeDoc
        ? state
        : { ...state, activeDoc: action.doc, activeCollection: null }
    case "select_collection":
      return action.corpusId === state.activeCollection
        ? state
        : { ...state, activeDoc: null, activeCollection: action.corpusId }
    case "append_turn": {
      const currentThread = state.threads[action.sessionKey] ?? []
      if (currentThread.some((turn) => turn.id === action.turn.id)) return state
      return {
        ...state,
        threads: {
          ...state.threads,
          [action.sessionKey]: [...currentThread, action.turn],
        },
      }
    }
    case "clear_thread":
      return {
        ...state,
        threads: { ...state.threads, [action.sessionKey]: [] },
      }
    default:
      return state
  }
}
