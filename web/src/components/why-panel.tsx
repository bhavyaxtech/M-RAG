"use client"

import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ui/reasoning"
import type { Turn } from "@/lib/types"

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="pt-px text-[11px] font-semibold uppercase tracking-[0.03em] text-muted-foreground">
        {label}
      </dt>
      <dd className="m-0 text-[13px] leading-snug">{children}</dd>
    </>
  )
}

export function WhyPanel({ turn, floor }: { turn: Turn; floor: number }) {
  const byLabel = new Map(turn.segments.map((segment) => [segment.label, segment]))
  const unused = turn.segments
    .filter((segment) => !turn.cited.includes(segment.label))
    .map((segment) => segment.label)

  return (
    <Reasoning>
      <ReasoningTrigger className="text-[12px] font-medium text-neutral-500 hover:text-neutral-800">
        Why this answer
      </ReasoningTrigger>
      <ReasoningContent
        className="mt-2"
        contentClassName="bg-neutral-50 px-3 py-2.5"
      >
        <dl className="grid grid-cols-[108px_1fr] gap-x-3 gap-y-1.5">
          <Row label="Route">
            {turn.route
              ? `${
                  turn.route.route === "datasheet"
                    ? "datasheet question"
                    : turn.route.route === "out_of_scope"
                      ? "question about a different document"
                      : "general conversation"
                }${
                  turn.route.fallback
                    ? ", router fell back to searching"
                    : ` (confidence ${turn.route.confidence.toFixed(2)})`
                }`
              : "unknown"}
          </Row>
          {turn.route?.route === "datasheet" && (
            <>
              <Row label="Searched for">{turn.route.search_query}</Row>
              <Row label="Relevance">
                {turn.pageAddressed
                  ? `Looked up page ${turn.requestedPage} directly; no similarity cutoff applied.`
                  : `Top match ${turn.topScore.toFixed(3)}, ${turn.topScore >= floor ? "at or above" : "below"} the ${floor.toFixed(2)} cutoff.`}
              </Row>
              <Row label="Cited">
                {turn.cited.length > 0
                  ? turn.cited
                      .map((label) => {
                        const segment = byLabel.get(label)
                        return segment
                          ? `${label} ${segment.doc_title} p.${segment.page} ${segment.type}`
                          : label
                      })
                      .join(", ")
                  : "nothing cited, treat this answer as unsupported"}
              </Row>
              {unused.length > 0 && (
                <Row label="Unused">
                  {unused.join(", ")}, still listed as evidence
                </Row>
              )}
            </>
          )}
          <Row label="Evidence">
            {turn.route?.route === "datasheet"
              ? `${turn.segments.length} sources retrieved. Citations are not independent fact-checks.`
              : turn.route?.route === "out_of_scope"
                ? "No sources searched; select the matching document."
                : "No document sources searched."}
          </Row>
          {turn.models && (
            <Row label="Models">
              {turn.models.generation} · routed by {turn.models.router}
            </Row>
          )}
        </dl>
      </ReasoningContent>
    </Reasoning>
  )
}
