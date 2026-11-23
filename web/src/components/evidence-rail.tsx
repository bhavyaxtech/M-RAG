"use client"

import { FileSearch } from "lucide-react"
import { motion, useReducedMotion } from "motion/react"
import Image from "next/image"

import { imageUrl } from "@/lib/api"
import type { Segment } from "@/lib/types"
import { cn } from "@/lib/utils"

const INLINE_MARKUP = /<\/?(?:sup|sub|b|i|em|strong|br|span|u)\b[^>]*>/g

function clean(text: string): string {
  return text.replace(INLINE_MARKUP, "").replace(/\s+/g, " ").trim()
}

export function EvidenceCard({
  segment,
  cited,
  index,
  readingVisual,
  onViewPage,
}: {
  segment: Segment
  cited: boolean
  index: number
  readingVisual: boolean
  onViewPage: (segment: Segment) => void
}) {
  const src = imageUrl(segment.image_url)
  const reduceMotion = useReducedMotion() === true
  const visualReading = readingVisual && segment.type !== "text"

  return (
    <motion.article
      id={`segment-${segment.label}`}
      initial={reduceMotion ? false : { y: 5, opacity: 0 }}
      animate={{
        y: 0,
        opacity: visualReading && !reduceMotion ? [0.72, 1, 0.72] : 1,
      }}
      transition={
        visualReading && !reduceMotion
          ? { duration: 1.2, repeat: Infinity, ease: "easeInOut" }
          : { duration: 0.22, delay: Math.min(index, 5) * 0.045 }
      }
      className={cn(
        "rounded-[18px] bg-white p-3.5",
        cited && "bg-neutral-200/70"
      )}
    >
      <div className="mb-3 flex items-start gap-3">
        <span
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold",
            cited
              ? "bg-neutral-800 text-white"
              : "bg-neutral-100 text-neutral-500"
          )}
        >
          {segment.label}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[12.5px] font-semibold text-neutral-700">
            {segment.doc_title}
          </p>
          <p className="mt-0.5 text-[10.5px] font-medium uppercase tracking-[0.08em] text-neutral-400">
            Page {segment.page} · {segment.type} · {segment.score.toFixed(3)}
          </p>
        </div>
      </div>

      <div className="mb-3 h-px overflow-hidden bg-neutral-100">
        <motion.div
          className="h-full origin-left bg-neutral-700"
          initial={reduceMotion ? false : { scaleX: 0 }}
          animate={{ scaleX: Math.max(0, Math.min(segment.score, 1)) }}
          transition={{
            duration: reduceMotion ? 0 : 0.38,
            delay: reduceMotion ? 0 : Math.min(index, 5) * 0.045,
          }}
        />
      </div>

      {src ? (
        <div className="relative flex justify-center overflow-hidden rounded-xl bg-neutral-50">
          <Image
            src={src}
            alt={`${segment.type} from ${segment.doc_title} page ${segment.page}`}
            width={640}
            height={400}
            unoptimized
            className="max-h-[360px] w-auto object-contain mix-blend-multiply"
          />
        </div>
      ) : (
        <p className="line-clamp-[8] text-[13px] leading-relaxed text-neutral-600">
          {clean(segment.text)}
        </p>
      )}

      <button
        type="button"
        disabled={!segment.page_url}
        onClick={() => onViewPage(segment)}
        className="mt-3 inline-flex items-center gap-1.5 text-[11.5px] font-medium text-neutral-500 transition-colors hover:text-neutral-900 focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 disabled:cursor-not-allowed disabled:text-neutral-300"
      >
        <FileSearch className="size-3.5" />
        {segment.page_url
          ? `Open page ${segment.page}`
          : `Page ${segment.page} unavailable`}
      </button>
    </motion.article>
  )
}

export function EvidenceRail({
  segments,
  cited,
  emptyMessage,
  readingVisuals = false,
  onViewPage,
}: {
  segments: Segment[]
  cited: string[]
  emptyMessage: string
  readingVisuals?: boolean
  onViewPage: (segment: Segment) => void
}) {
  const citedSet = new Set(cited)

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2 px-1">
        <h2 className="text-[12px] font-semibold uppercase tracking-[0.11em] text-neutral-500">
          Evidence
        </h2>
        {segments.length > 0 && (
          <span className="text-[11px] font-medium text-neutral-400">
            {segments.length} found · {cited.length} cited
          </span>
        )}
      </div>

      {segments.length === 0 ? (
        <p className="px-4 py-8 text-center text-[13px] leading-relaxed text-neutral-400">
          {emptyMessage}
        </p>
      ) : (
        segments.map((segment, index) => (
          <EvidenceCard
            key={segment.segment_id}
            segment={segment}
            cited={citedSet.has(segment.label)}
            index={index}
            readingVisual={readingVisuals}
            onViewPage={onViewPage}
          />
        ))
      )}
    </div>
  )
}
