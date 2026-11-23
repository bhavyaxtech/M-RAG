import type { Turn } from "./types"

/** These are pipeline statuses, not a transcript of the model's reasoning. */
export function progressLabel(turn: Pick<Turn, "streaming" | "answer" | "stages">): string | null {
  if (!turn.streaming || turn.answer) return null
  const activeStage = turn.stages.findLast((stage) => stage.status === "active")?.stage
  if (activeStage === "route") return "Understanding user query"
  if (activeStage === "retrieve") return "Retrieving"
  return "Thinking"
}

/** Smooth network bursts without leaving a long typewriter queue behind. */
export function revealLength(pending: string, elapsedMs: number): number {
  const charactersPerSecond = Math.max(120, pending.length / 0.8)
  let length = Math.min(pending.length, Math.max(1,
    Math.floor(charactersPerSecond * Math.min(elapsedMs, 50) / 1000)))
  // Never render half a UTF-16 surrogate pair (for example an emoji).
  if (length < pending.length && /[\uD800-\uDBFF]/.test(pending[length - 1])) length++
  return length
}
