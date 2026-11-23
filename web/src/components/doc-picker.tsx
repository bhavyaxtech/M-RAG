"use client"

import { ArrowRight, FileStack, ImageIcon, Table2, Type } from "lucide-react"

import type { Meta } from "@/lib/types"

export function DocPicker({
  meta,
  onSelectDocument,
  onSelectCollection,
}: {
  meta: Meta | null
  onSelectDocument: (doc: string) => void
  onSelectCollection: (corpusId: string) => void
}) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col px-8 py-12 xl:px-12 xl:py-16">
      <header className="max-w-[760px]">
        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-neutral-400">
          Start with a PDF or library
        </p>
        <h1 className="text-[34px] font-semibold leading-[1.08] tracking-[-0.04em] text-neutral-800 xl:text-[42px]">
          Understand your datasheet.
        </h1>
        <p className="mt-5 max-w-[720px] text-[16px] leading-7 text-neutral-500">
          Start one shared conversation across a library, or choose an individual
          PDF for a focused session. Ask questions across text, tables, and
          diagrams, with sources you can inspect. No PDF selection is needed to
          chat with a library.
        </p>
      </header>

      {meta ? (
        <div className="mt-10 flex flex-col gap-9">
          {meta.corpora.map((corpus) => (
            <section
              key={corpus.corpus_id}
              aria-labelledby={`corpus-${corpus.corpus_id}`}
            >
              <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
                <div className="min-w-0">
                  <h2
                    id={`corpus-${corpus.corpus_id}`}
                    className="text-[14px] font-bold text-slate-900"
                  >
                    {corpus.title}
                  </h2>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">
                    {corpus.blurb}
                  </p>
                </div>
                <span className="shrink-0 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-400">
                  {corpus.documents.length} documents
                </span>
              </div>

              <button
                type="button"
                aria-label={`Chat with all ${corpus.documents.length} PDFs in ${corpus.title}`}
                disabled={corpus.documents.length === 0}
                onClick={() => onSelectCollection(corpus.corpus_id)}
                className="group mb-4 flex w-full items-center justify-between gap-4 rounded-[22px] bg-neutral-800 p-5 text-left text-white transition-colors hover:bg-neutral-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-500/40 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span className="flex min-w-0 items-start gap-3">
                  <FileStack aria-hidden="true" className="mt-0.5 size-5 shrink-0" />
                  <span className="min-w-0">
                    <span className="block text-[17px] font-semibold leading-snug tracking-[-0.02em]">
                      Chat with all {corpus.documents.length} PDFs
                    </span>
                    <span className="mt-1 block text-[12px] leading-relaxed text-neutral-300">
                      {corpus.title} · {corpus.totals.pages.toLocaleString()} pages
                    </span>
                    <span className="mt-2 block text-[12px] leading-relaxed text-neutral-300">
                      One shared conversation across this library.
                    </span>
                  </span>
                </span>
                <ArrowRight aria-hidden="true" className="size-5 shrink-0" />
              </button>

              <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.08em] text-neutral-500">
                Or open an individual PDF
              </p>
              <div className="grid grid-cols-1 gap-3 2xl:grid-cols-2">
                {corpus.documents.map((document) => {
                  const visualPercent = Math.round(document.visual_share * 100)
                  return (
                    <button
                      key={document.doc_id}
                      type="button"
                      onClick={() => onSelectDocument(document.doc_id)}
                      className="group rounded-[22px] bg-white p-5 text-left transition-colors hover:bg-neutral-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-500/40"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <h3 className="text-[17px] font-semibold tracking-[-0.02em] text-neutral-800">
                            {document.title}
                          </h3>
                          <p className="mt-1 flex items-center gap-1.5 text-[12px] font-medium text-slate-500">
                            <FileStack className="size-3.5" />
                            {document.pages.toLocaleString()} pages
                          </p>
                        </div>
                        <span className="flex size-8 items-center justify-center rounded-full bg-neutral-100 text-neutral-400 transition-colors group-hover:bg-neutral-800 group-hover:text-white">
                          <ArrowRight className="size-4" />
                        </span>
                      </div>

                      <dl className="mt-5 grid grid-cols-4 gap-2 bg-neutral-50 px-3 py-3">
                        <Metric
                          icon={Type}
                          value={document.text}
                          label="text segments"
                        />
                        <Metric
                          icon={ImageIcon}
                          value={document.figures}
                          label="figures"
                        />
                        <Metric
                          icon={Table2}
                          value={document.tables}
                          label="tables"
                        />
                        <Metric
                          icon={FileStack}
                          value={document.segments}
                          label="segments"
                        />
                      </dl>

                      <div className="mt-4">
                        <div className="flex items-baseline justify-between gap-4">
                          <span className="text-[11px] font-semibold leading-snug text-slate-600">
                            Share of index built from figures and tables
                          </span>
                          <span className="text-[16px] font-semibold tabular-nums text-neutral-700">
                            {visualPercent}%
                          </span>
                        </div>
                        <div
                          className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"
                          role="progressbar"
                          aria-label={`${document.title} visual share`}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={visualPercent}
                        >
                          <div
                            className="h-full rounded-full bg-neutral-700"
                            style={{
                              width: `${Math.min(100, Math.max(0, visualPercent))}%`,
                            }}
                          />
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="mt-10 rounded-2xl bg-white/70 px-6 py-12 text-center text-sm text-muted-foreground">
          Connect the agent service to load the document catalog.
        </div>
      )}
    </div>
  )
}

function Metric({
  icon: Icon,
  value,
  label,
}: {
  icon: typeof Type
  value: number
  label: string
}) {
  return (
    <div>
      <dt className="flex items-center gap-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-neutral-400">
        <Icon className="size-3" />
        {label}
      </dt>
      <dd className="mt-1 text-[13px] font-semibold tabular-nums text-neutral-700">
        {value.toLocaleString()}
      </dd>
    </div>
  )
}
