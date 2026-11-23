"use client"

import { FileStack, FileText, Plus } from "lucide-react"

import { Button } from "@/components/ui/button"
import { collectionSessionKey } from "@/lib/session-store"
import type { Meta, Turn } from "@/lib/types"
import { cn } from "@/lib/utils"

export function DocSidebar({
  meta,
  activeDoc,
  activeCollection,
  threads,
  onSelectDocument,
  onSelectCollection,
  onNewSession,
}: {
  meta: Meta | null
  activeDoc: string | null
  activeCollection: string | null
  threads: Record<string, Turn[]>
  onSelectDocument: (doc: string) => void
  onSelectCollection: (corpusId: string) => void
  onNewSession: () => void
}) {
  return (
    <aside className="flex min-h-0 flex-col rounded-[24px] bg-neutral-200 px-3 py-4 lg:min-h-[560px] lg:py-5 xl:h-full xl:min-h-0">
      <div className="px-2">
        <p className="text-[20px] font-semibold tracking-[-0.035em] text-neutral-800">
          M-RAG
        </p>
        <p className="mt-1 text-[10px] font-medium uppercase tracking-[0.14em] text-neutral-500">
          Document intelligence
        </p>
      </div>

      <nav
        aria-label="Document and collection sessions"
        className="mt-5 flex-1 lg:mt-7 lg:overflow-y-auto"
      >
        {meta ? (
          meta.corpora.map((corpus) => (
            <section key={corpus.corpus_id} className="mb-7">
              <div className="mb-2 px-2">
                <h2 className="text-[10px] font-semibold uppercase tracking-[0.12em] text-neutral-500">
                  {corpus.title}
                </h2>
              </div>

              <button
                type="button"
                aria-label={`Chat with all ${corpus.documents.length} PDFs in ${corpus.title}`}
                aria-pressed={activeCollection === corpus.corpus_id}
                disabled={corpus.documents.length === 0}
                onClick={() => onSelectCollection(corpus.corpus_id)}
                className={cn(
                  "mb-2 w-full rounded-xl border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-500/40 disabled:cursor-not-allowed disabled:opacity-50",
                  activeCollection === corpus.corpus_id
                    ? "border-neutral-800 bg-neutral-800 text-white"
                    : "border-neutral-300 bg-white/80 text-neutral-800 hover:bg-white"
                )}
              >
                <span className="flex items-start gap-2.5">
                  <FileStack aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-semibold leading-snug">
                      Chat with all {corpus.documents.length} PDFs
                    </span>
                    <span className="mt-1 block text-[11px] leading-snug opacity-80">
                      {corpus.totals.pages.toLocaleString()} pages · Shared conversation
                    </span>
                    <span className="mt-2 block text-[10px] font-semibold uppercase tracking-[0.08em]">
                      Saved turns: {threads[collectionSessionKey(corpus.corpus_id)]?.length ?? 0}
                      {activeCollection === corpus.corpus_id && " · Active"}
                    </span>
                  </span>
                </span>
              </button>

              <div className="grid grid-cols-2 gap-1 sm:grid-cols-3 lg:flex lg:flex-col">
                {corpus.documents.map((document) => {
                  const isActive = !activeCollection && document.doc_id === activeDoc
                  const turnCount = threads[document.doc_id]?.length ?? 0
                  return (
                    <button
                      key={document.doc_id}
                      type="button"
                      aria-pressed={isActive}
                      onClick={() => onSelectDocument(document.doc_id)}
                      className={cn(
                        "w-full rounded-xl px-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-500/40",
                        isActive
                          ? "bg-white text-neutral-900"
                          : "text-neutral-600 hover:bg-neutral-300/70"
                      )}
                    >
                      <span className="flex items-start gap-2.5">
                        <FileText
                          className={cn(
                            "mt-0.5 size-4 shrink-0",
                            isActive ? "text-neutral-700" : "text-neutral-400"
                          )}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[13px] font-medium leading-snug text-current">
                            {document.title}
                          </span>
                          <span className="mt-0.5 block text-[11px] text-slate-500">
                            {document.pages.toLocaleString()} pages
                          </span>
                          {isActive && (
                            <span className="mt-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-neutral-500">
                              <span className="size-1.5 rounded-full bg-neutral-500" />
                              Session
                              {turnCount > 0 && ` · ${turnCount} turns`}
                            </span>
                          )}
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>
            </section>
          ))
        ) : (
          <p className="px-2 text-[12px] leading-relaxed text-muted-foreground">
            Document catalog unavailable.
          </p>
        )}
      </nav>

      <div className="hidden pt-3 lg:block">
        <Button
          type="button"
          variant="ghost"
          className="h-9 w-full justify-start gap-2 bg-neutral-300/60 text-neutral-700 hover:bg-white"
          disabled={!activeDoc && !activeCollection}
          onClick={onNewSession}
        >
          <Plus className="size-4" />
          New session
        </Button>
        <p className="mt-2 px-1 text-[10.5px] leading-snug text-muted-foreground">
          Clears only the selected session&apos;s conversation.
        </p>
      </div>
    </aside>
  )
}
