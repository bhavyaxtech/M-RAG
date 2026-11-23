"use client"

import { ChevronDown, ChevronUp, DatabaseZap } from "lucide-react"
import { useState } from "react"

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import type { Meta } from "@/lib/types"

export function ProvenancePanel({ meta }: { meta: Meta | null }) {
  const [open, setOpen] = useState(false)
  const totals = meta?.corpora.reduce(
    (sum, corpus) => ({
      pages: sum.pages + corpus.totals.pages,
      crops: sum.crops + corpus.totals.visual_vectors,
      vectors: sum.vectors + corpus.totals.vectors,
    }),
    { pages: 0, crops: 0, vectors: 0 }
  )

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="overflow-hidden rounded-xl bg-neutral-200/75">
        <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-3 text-left hover:bg-neutral-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-neutral-500/40">
          <DatabaseZap className="size-4 text-neutral-500" />
          <span className="flex-1 text-[11px] font-semibold uppercase tracking-[0.09em] text-neutral-600">
            Build provenance
          </span>
          {open ? (
            <ChevronUp className="size-4 text-slate-400" />
          ) : (
            <ChevronDown className="size-4 text-slate-400" />
          )}
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="px-3 pb-3 pt-1">
            {meta && totals ? (
              <dl className="grid grid-cols-[112px_minmax(0,1fr)] gap-x-3 gap-y-2 text-[11.5px] leading-snug">
                <ProvenanceRow label="Pages parsed">
                  {totals.pages.toLocaleString()}
                </ProvenanceRow>
                <ProvenanceRow label="Crops captioned">
                  {totals.crops.toLocaleString()}
                </ProvenanceRow>
                <ProvenanceRow label="Vectors built">
                  {totals.vectors.toLocaleString()}
                </ProvenanceRow>
                <ProvenanceRow label="Embedding deployment">
                  {meta.models.embedding}
                </ProvenanceRow>
                <ProvenanceRow label="Generation deployment">
                  {meta.models.generation}
                </ProvenanceRow>
                <ProvenanceRow label="Router deployment">
                  {meta.models.router}
                </ProvenanceRow>
                {meta.corpora.map((corpus) => (
                  <ProvenanceRow
                    key={corpus.corpus_id}
                    label={`${corpus.title} index`}
                  >
                    {corpus.index.type} ·{" "}
                    {corpus.index.dimensions.toLocaleString()}d
                    {corpus.index.normalized ? " · normalized" : ""}
                  </ProvenanceRow>
                ))}
              </dl>
            ) : (
              <p className="text-[11.5px] leading-relaxed text-muted-foreground">
                Provenance metadata is unavailable while the service is offline.
              </p>
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

function ProvenanceRow({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <>
      <dt className="font-semibold text-slate-500">{label}</dt>
      <dd className="m-0 min-w-0 break-words font-medium text-slate-800">
        {children}
      </dd>
    </>
  )
}
