"use client"

/* eslint-disable @next/next/no-img-element -- The API supplies page images with
   unknown intrinsic dimensions; a native image preserves its rendered aspect
   ratio so the fractional bbox overlay stays aligned. */

import { FileWarning, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import { imageUrl } from "@/lib/api"
import type { Segment } from "@/lib/types"

const FOCUSABLE = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",")

function PageImage({ segment }: { segment: Segment }) {
  const [failed, setFailed] = useState(false)
  const source =
    imageUrl(
      `/api/page/${encodeURIComponent(segment.doc)}/${segment.page}`
    ) ?? ""

  if (failed) {
    return (
      <div
        className="flex min-h-72 max-w-xl flex-col items-center justify-center gap-3 rounded-xl bg-neutral-200 px-8 text-center text-neutral-800"
        role="status"
      >
        <FileWarning className="size-7 text-neutral-500" aria-hidden />
        <div>
          <p className="font-semibold">Page preview unavailable</p>
          <p className="mt-1 text-sm leading-relaxed text-neutral-600">
            The API could not render this page. The source PDF may not be
            available on the backend.
          </p>
        </div>
      </div>
    )
  }

  const [x0, y0, x1, y1] = segment.bbox ?? [0, 0, 0, 0]

  return (
    <div className="relative inline-block max-w-full overflow-hidden rounded-sm bg-white leading-none shadow-2xl">
      <img
        src={source}
        alt={`Full page ${segment.page} from ${segment.doc_title}`}
        draggable={false}
        onError={() => setFailed(true)}
        className="block h-auto max-h-[calc(100dvh-13rem)] w-auto max-w-full object-contain"
      />
      {segment.bbox && (
        <div
          aria-label={`Location of evidence ${segment.label}`}
          className="pointer-events-none absolute box-border border-[3px] border-neutral-800 bg-neutral-500/10 shadow-[0_0_0_1px_rgba(255,255,255,0.9),0_0_0_5px_rgba(38,38,38,0.14)]"
          style={{
            left: `${x0 * 100}%`,
            top: `${y0 * 100}%`,
            width: `${(x1 - x0) * 100}%`,
            height: `${(y1 - y0) * 100}%`,
          }}
        />
      )}
    </div>
  )
}

export function PageViewer({
  segment,
  totalPages,
  onClose,
}: {
  segment: Segment | null
  totalPages: number
  onClose: () => void
}) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!segment) return

    const trigger =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    closeButtonRef.current?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== "Tab") return

      const dialog = dialogRef.current
      if (!dialog) return
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE)
      ).filter((element) => element.getClientRects().length > 0)

      if (focusable.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!dialog.contains(document.activeElement)) {
        event.preventDefault()
        first.focus()
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener("keydown", handleKeyDown)
    return () => {
      document.removeEventListener("keydown", handleKeyDown)
      document.body.style.overflow = previousOverflow
      trigger?.focus()
    }
  }, [onClose, segment])

  if (!segment) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/68 p-4 backdrop-blur-[2px]"
      onClick={(event) => {
        if (event.currentTarget === event.target) onClose()
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="page-viewer-title"
        aria-describedby="page-viewer-provenance"
        tabIndex={-1}
        className="flex max-h-[calc(100dvh-2rem)] w-full max-w-5xl flex-col overflow-hidden rounded-[22px] bg-white shadow-[0_30px_90px_rgba(15,15,15,0.38)] outline-none"
      >
        <header className="flex items-center justify-between gap-4 px-5 py-3.5">
          <div className="min-w-0">
            <h2
              id="page-viewer-title"
              className="truncate text-[15px] font-bold text-slate-950"
            >
              {segment.doc_title}
            </h2>
            <p className="mt-0.5 text-[12px] font-medium text-slate-500">
              Page {segment.page.toLocaleString()} of{" "}
              {totalPages.toLocaleString()}
            </p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close page viewer"
            className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-neutral-100 text-neutral-600 transition-colors hover:bg-neutral-200 hover:text-neutral-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-500/50"
          >
            <X className="size-4.5" aria-hidden />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-auto bg-slate-900 p-4 text-center sm:p-6">
          <PageImage
            key={`${segment.segment_id}-${segment.page}`}
            segment={segment}
          />
        </div>

        <footer
          id="page-viewer-provenance"
          className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-neutral-100 px-5 py-3 text-[12px]"
        >
          <span className="rounded bg-neutral-800 px-1.5 py-0.5 font-semibold text-white">
            {segment.label}
          </span>
          <span className="font-bold uppercase tracking-[0.08em] text-slate-700">
            {segment.type}
          </span>
          <span className="text-slate-300" aria-hidden>
            /
          </span>
          <span className="font-medium tabular-nums text-slate-600">
            relevance {segment.score.toFixed(3)}
          </span>
        </footer>
      </div>
    </div>
  )
}
