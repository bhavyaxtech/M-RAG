"use client"

import { cn } from "@/lib/utils"
import type { Turn } from "@/lib/types"

export function TraceLine({
  turn,
  totalPages = 0,
}: {
  turn: Turn
  totalPages?: number
}) {
  const parts: string[] = []
  if (turn.mode === "plain") {
    parts.push("answered with no retrieval")
  } else if (turn.route?.route === "datasheet") {
    if (turn.pageAddressed && turn.requestedPage) {
      const pageTotal = totalPages > 0 ? ` of ${totalPages.toLocaleString()}` : ""
      parts.push(`read page ${turn.requestedPage}${pageTotal} directly`)
    } else {
      parts.push("searched the index")
    }
    parts.push(`${turn.segments.length} segments retrieved`)
    const visuals = turn.segments.filter(
      (segment) => segment.type !== "text"
    ).length
    if (visuals > 0 && turn.mode === "mrag") {
      parts.push(`${visuals} crops read`)
    }
  } else if (turn.route) {
    parts.push("answered directly")
  }
  if (turn.timings.total) {
    parts.push(`${(turn.timings.total / 1000).toFixed(1)}s`)
  }
  if (parts.length === 0) return null

  return (
    <div className={cn("text-[12px] font-medium text-muted-foreground")}>
      {parts.join(" · ")}
    </div>
  )
}
