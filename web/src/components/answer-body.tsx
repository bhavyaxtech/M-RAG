"use client"

import { useMemo } from "react"
import type { Components } from "react-markdown"

import { Markdown } from "@/components/ui/markdown"
import type { Provenance, Segment } from "@/lib/types"
import { cn } from "@/lib/utils"

const CITATION = /\[S(\d+)\]/g

const PROVENANCE_STYLE: Record<Provenance, { label: string; className: string }> =
  {
    grounded: { label: "Sources cited", className: "bg-neutral-100 text-neutral-600" },
    page_addressed: {
      label: "From requested page",
      className: "bg-neutral-200 text-neutral-700",
    },
    general: {
      label: "General knowledge",
      className: "bg-neutral-100 text-neutral-600",
    },
    out_of_scope: {
      label: "Different document",
      className: "bg-neutral-200 text-neutral-700",
    },
    uncovered: {
      label: "Could not verify",
      className: "bg-neutral-200 text-neutral-700",
    },
    unsupported: {
      label: "No sources cited",
      className: "bg-neutral-800 text-white",
    },
    plain: { label: "No retrieval", className: "bg-neutral-100 text-neutral-600" },
  }

export function ProvenanceBadge({
  provenance,
  requestedPage,
}: {
  provenance: Provenance
  requestedPage?: number | null
}) {
  const style = PROVENANCE_STYLE[provenance]
  const label =
    provenance === "page_addressed" && requestedPage
      ? `From page ${requestedPage}`
      : style.label
  return (
    <span
      className={cn(
        "inline-flex animate-[pop_0.18s_ease-out_both] items-center rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-[0.055em] motion-reduce:animate-none",
        style.className
      )}
    >
      {label}
    </span>
  )
}

/**
 * Renders the answer as one markdown document.
 *
 * Citations are rewritten into inline links before parsing rather than
 * splitting the string around them: splitting would put each fragment in its
 * own block and shatter every paragraph the model wrote. Markers naming a
 * segment that was not retrieved are dropped, so the UI never offers a citation
 * it cannot honour.
 */
export function AnswerBody({
  answer,
  segments,
  streaming,
  onViewSource,
}: {
  answer: string
  segments: Segment[]
  streaming?: boolean
  onViewSource: (segment: Segment) => void
}) {
  const sourcesByLabel = useMemo(
    () => new Map(segments.map((segment) => [segment.label, segment])),
    [segments]
  )

  const source = useMemo(
    () =>
      answer.replace(CITATION, (marker, index) => {
        const label = `S${Number(index)}`
        return sourcesByLabel.has(label) ? `[${label}](#segment-${label})` : ""
      }),
    [answer, sourcesByLabel]
  )

  const components = useMemo<Partial<Components>>(
    () => ({
      a({ href, children, ...props }) {
        const target = typeof href === "string" ? href : ""
        if (!target.startsWith("#segment-")) {
          return (
            <a
              href={target}
              target="_blank"
              rel="noreferrer"
              className="text-neutral-800 underline decoration-neutral-400 underline-offset-2"
              {...props}
            >
              {children}
            </a>
          )
        }
        const segment = sourcesByLabel.get(target.slice("#segment-".length))
        if (!segment) return <>{children}</>
        return (
          <button
            type="button"
            onClick={() => onViewSource(segment)}
            aria-label={`Open source ${segment.label}: ${segment.doc_title}, page ${segment.page}`}
            className="mx-0.5 inline-flex cursor-pointer items-center rounded bg-neutral-100 px-1.5 align-[1px] text-[11px] font-semibold text-neutral-700 no-underline transition-colors hover:bg-neutral-200 hover:text-neutral-950"
          >
            {children}
          </button>
        )
      },
      table({ children }) {
        return (
          <div className="my-3 max-w-full overflow-x-auto rounded-lg bg-neutral-50">
            <table className="w-full border-collapse text-left text-[14px] [&_td]:px-3 [&_td]:py-2 [&_th]:bg-neutral-100 [&_th]:px-3 [&_th]:py-2 [&_th]:font-semibold [&_tr:nth-child(even)]:bg-neutral-100/60">
              {children}
            </table>
          </div>
        )
      },
    }),
    [onViewSource, sourcesByLabel]
  )

  return (
    <div className="min-w-0 max-w-none break-words text-[16px] leading-[1.65] [&_h1]:mb-2 [&_h1]:mt-4 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-4 [&_h2]:font-semibold [&_li]:my-1 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_strong]:font-semibold [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
      <Markdown components={components}>{source}</Markdown>
      {streaming && (
        <span className="ml-0.5 inline-block h-[1em] w-[2px] animate-[blink_0.9s_step-end_infinite] bg-neutral-700 align-text-bottom motion-reduce:animate-none" />
      )}
    </div>
  )
}
