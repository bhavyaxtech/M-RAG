"use client"

import { TextShimmer } from "@/components/ui/text-shimmer"
import { progressLabel } from "@/lib/stream-presentation"
import type { Turn } from "@/lib/types"

export function PipelineTrace({ turn }: { turn: Turn }) {
  const label = progressLabel(turn)
  if (!label) return null

  return (
    <div role="status" aria-live="polite" aria-atomic="true" className="py-0.5 text-[13px] text-neutral-500">
      <TextShimmer duration={2.4} className="motion-reduce:animate-none">
        {label}
      </TextShimmer>
    </div>
  )
}
