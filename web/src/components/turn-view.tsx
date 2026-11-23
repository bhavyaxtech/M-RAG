"use client"

import { AnswerBody, ProvenanceBadge } from "@/components/answer-body"
import { PipelineTrace } from "@/components/pipeline-trace"
import { WhyPanel } from "@/components/why-panel"
import { Message, MessageContent } from "@/components/ui/message"
import type { Segment, Turn } from "@/lib/types"

export function TurnView({
  turn,
  floor,
  onViewSource,
  onShowSources,
}: {
  turn: Turn
  floor: number
  onViewSource: (segment: Segment) => void
  onShowSources: (turn: Turn) => void
}) {
  return (
    <div className="flex flex-col gap-4 py-2">
      <Message className="justify-end">
        <MessageContent className="max-w-[85%] rounded-[18px] bg-neutral-100 px-4 py-2.5 text-[15px] text-neutral-700">
          {turn.question}
        </MessageContent>
      </Message>
      {turn.scope === "collection" && (
        <span className="self-end text-[10px] font-medium text-neutral-500">Whole collection</span>
      )}

      <article className="grid grid-cols-[26px_minmax(0,1fr)] gap-3">
        <div className="flex size-6 items-center justify-center rounded-md bg-neutral-800 text-[10px] font-semibold text-white">
          M
        </div>
        <div className="min-w-0 pt-0.5">
        {turn.streaming && !turn.answer && (
          <div className="mb-3">
            <PipelineTrace turn={turn} />
          </div>
        )}

        {turn.provenance && (
          <div className="mb-3">
            <ProvenanceBadge
              provenance={turn.provenance}
              requestedPage={turn.requestedPage}
            />
          </div>
        )}

        {turn.error && (
          <p className="rounded-lg bg-neutral-200 px-3 py-2 text-[13px] font-medium text-neutral-800">
            {turn.error}
          </p>
        )}
        {turn.answer && (
          <AnswerBody
            answer={turn.answer}
            segments={turn.segments}
            streaming={turn.streaming && turn.answer.length > 0}
            onViewSource={onViewSource}
          />
        )}

        {!turn.streaming && turn.answer && (
          <div className="mt-3 flex flex-wrap items-start gap-x-4 gap-y-2">
            {turn.segments.length > 0 && (
              <button
                type="button"
                onClick={() => onShowSources(turn)}
                aria-label={`View sources for: ${turn.question}`}
                className="text-[12px] font-medium text-neutral-600 underline-offset-4 hover:underline"
              >
                View {turn.segments.length} sources
              </button>
            )}
            <WhyPanel turn={turn} floor={floor} />
          </div>
        )}
        </div>
      </article>
    </div>
  )
}
