import assert from "node:assert/strict"
import { test } from "node:test"
import { progressLabel, revealLength } from "../src/lib/stream-presentation.ts"

test("one status follows real pipeline stages, then disappears for output", () => {
  const turn = { streaming: true, answer: "", stages: [] }
  assert.equal(progressLabel(turn), "Thinking")
  turn.stages = [{ stage: "route", status: "active" }]
  assert.equal(progressLabel(turn), "Understanding user query")
  turn.stages = [{ stage: "route", status: "done" }, { stage: "retrieve", status: "active" }]
  assert.equal(progressLabel(turn), "Retrieving")
  turn.stages.push({ stage: "retrieve", status: "done" }, { stage: "answer", status: "active" })
  assert.equal(progressLabel(turn), "Thinking")
  turn.answer = "First words"
  assert.equal(progressLabel(turn), null)
  turn.streaming = false
  turn.answer = ""
  assert.equal(progressLabel(turn), null)
})

test("non-retrieval answers never invent a retrieval stage", () => {
  assert.equal(progressLabel({ streaming: true, answer: "", stages: [
    { stage: "route", status: "done" }, { stage: "answer", status: "active" },
  ] }), "Thinking")
})

test("burst pacing preserves exact markdown and Unicode without a final dump", () => {
  const answer = "## Result\n\n**Voltage** is 3.3 V 🧪 [S1].\n\n".repeat(100)
  let remaining = answer
  let displayed = ""
  let frames = 0
  assert.ok(revealLength(remaining, 16) < remaining.length / 10)
  while (remaining) {
    const length = revealLength(remaining, 16)
    displayed += remaining.slice(0, length)
    remaining = remaining.slice(length)
    frames++
    assert.ok(frames < 1000)
  }
  assert.equal(displayed, answer)
  assert.ok(frames > 1)
  assert.equal(revealLength("🧪x", 16), 2)
  assert.equal(revealLength("", 16), 0)
})
