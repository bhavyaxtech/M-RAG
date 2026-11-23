"use client"

import { ArrowUp, Square } from "lucide-react"
import { useCallback, useEffect, useState } from "react"

import { ApiBanner } from "@/components/api-banner"
import { DocPicker } from "@/components/doc-picker"
import { DocSidebar } from "@/components/doc-sidebar"
import { EvidenceRail } from "@/components/evidence-rail"
import { PageViewer } from "@/components/page-viewer"
import { PipelineTrace } from "@/components/pipeline-trace"
import { ProvenancePanel } from "@/components/provenance-panel"
import { TurnView } from "@/components/turn-view"
import { Button } from "@/components/ui/button"
import {
  ChatContainerContent,
  ChatContainerRoot,
} from "@/components/ui/chat-container"
import {
  PromptInput,
  PromptInputActions,
  PromptInputTextarea,
} from "@/components/ui/prompt-input"
import { PromptSuggestion } from "@/components/ui/prompt-suggestion"
import { fetchMeta } from "@/lib/api"
import type { Meta, Segment, Turn } from "@/lib/types"
import { useSession } from "@/lib/use-session"

const EMPTY_EVIDENCE =
  "Retrieved figures, tables, and text from this document will appear here."

const DOCUMENT_SUGGESTIONS: Record<string, string[]> = {
  "esp32-wroom-32e-32ue": [
    "Which module pin is TXD0? Explain what that pin does.",
    "How many UART interfaces does the ESP32 have?",
  ],
  lm317: [
    "Which pin and tab are OUTPUT on the LM317 TO-220 package?",
    "How does the LM317 recover after an overload? Explain simply.",
  ],
  stm32f103c8: [
    "Which physical pin is PA9 in the LQFP48 package?",
    "Explain the ADC conversion times at a 14 MHz ADC clock.",
  ],
  atmega328p: [
    "Which pin is PD1/TXD on the 28-pin PDIP package?",
    "Explain how analog input voltage maps to the ADC's digital value.",
  ],
  rp2040: [
    "Why is the RP2040 SRAM divided into six banks? Explain simply.",
    "What does the block diagram show about how the RP2040 works?",
  ],
}

export default function ChatPage() {
  const [input, setInput] = useState("")
  const [meta, setMeta] = useState<Meta | null>(null)
  const [apiDown, setApiDown] = useState(false)
  const [viewerSegment, setViewerSegment] = useState<Segment | null>(null)
  const [evidenceTurnId, setEvidenceTurnId] = useState<string | null>(null)
  const {
    activeDoc,
    activeCollection,
    threads,
    thread,
    activeTurn,
    running,
    selectDocument,
    selectCollection,
    newSession,
    run,
    cancel,
  } = useSession()

  useEffect(() => {
    const controller = new AbortController()
    fetchMeta(controller.signal)
      .then((value) => {
        setMeta(value)
        setApiDown(false)
      })
      .catch((error: Error) => {
        if (error.name === "AbortError") return
        setMeta(null)
        setApiDown(true)
      })
    return () => controller.abort()
  }, [])

  const activeCorpus = meta?.corpora.find((corpus) =>
    activeCollection
      ? corpus.corpus_id === activeCollection
      : corpus.documents.some((document) => document.doc_id === activeDoc)
  )
  const activeDocument = activeCorpus?.documents.find(
    (document) => document.doc_id === activeDoc
  )
  const searchCollection = activeCollection !== null
  const hasActiveSession = Boolean(searchCollection ? activeCorpus : activeDocument)
  const activeTitle = (searchCollection ? activeCorpus?.title : activeDocument?.title) ?? ""
  const activePages = (searchCollection ? activeCorpus?.totals.pages : activeDocument?.pages) ?? 0
  const latestTurn = activeTurn ?? thread[thread.length - 1] ?? null
  const evidenceTurn =
    thread.find((turn) => turn.id === evidenceTurnId) ?? latestTurn
  const readingVisuals =
    evidenceTurn?.streaming === true &&
    evidenceTurn.stages.some(
      (stage) => stage.stage === "read" && stage.status === "active"
    )
  const suggestions = searchCollection ? (activeCollection === "stm32" ? [
    "Compare AN2594 EEPROM emulation with AN2557 USART programming. Cite both PDFs.",
    "How do AN3116 ADC modes and AN2548 DMA configuration work together?",
  ] : [
    "Compare the components in this library and cite the relevant PDFs.",
    "Which documents should I consult for pinouts and electrical limits?",
  ]) : DOCUMENT_SUGGESTIONS[activeDoc ?? ""] ?? [
    "What does this component do? Explain in plain language.",
    "Explain the pinout and the important electrical limits.",
  ]

  const handleSelectDocument = useCallback(
    (doc: string) => {
      setInput("")
      setViewerSegment(null)
      setEvidenceTurnId(null)
      selectDocument(doc)
    },
    [selectDocument]
  )

  const handleSelectCollection = useCallback(
    (corpusId: string) => {
      setInput("")
      setViewerSegment(null)
      setEvidenceTurnId(null)
      selectCollection(corpusId)
    },
    [selectCollection]
  )

  const submit = useCallback(
    (text: string) => {
      const question = text.trim()
      if (!question || running || !hasActiveSession) return
      setInput("")
      setEvidenceTurnId(null)
      void run(question)
    },
    [hasActiveSession, run, running]
  )

  const handleViewPage = useCallback((segment: Segment) => {
    setViewerSegment(segment)
  }, [])

  const closePageViewer = useCallback(() => {
    setViewerSegment(null)
  }, [])

  const handleShowSources = useCallback((turn: Turn) => {
    setEvidenceTurnId(turn.id)
    document.getElementById("evidence-panel")?.scrollIntoView({ block: "nearest" })
  }, [])

  return (
    <div className="app-canvas min-h-dvh p-3 text-neutral-700 lg:p-4">
      <div className="mx-auto grid min-h-[calc(100dvh-1.5rem)] max-w-[1680px] grid-cols-1 gap-3 lg:grid-cols-[220px_minmax(480px,1fr)] xl:h-[calc(100dvh-2rem)] xl:min-h-0 xl:grid-cols-[220px_minmax(480px,1fr)_360px]">
        <DocSidebar
          meta={meta}
          activeDoc={activeDoc}
          activeCollection={activeCollection}
          threads={threads}
          onSelectDocument={handleSelectDocument}
          onSelectCollection={handleSelectCollection}
          onNewSession={newSession}
        />

        <main className="flex min-h-[720px] min-w-0 flex-col overflow-hidden rounded-[24px] bg-white xl:h-full xl:min-h-0">
          <div className="px-6 pt-5">
            <ApiBanner show={apiDown} />
          </div>

          {!hasActiveSession ? (
            <div className="min-h-0 flex-1 overflow-y-auto">
              <DocPicker meta={meta} onSelectDocument={handleSelectDocument} onSelectCollection={handleSelectCollection} />
            </div>
          ) : (
            <>
              <header className="px-7 pb-5 pt-2">
                <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-neutral-400">
                  {searchCollection ? "Shared library session" : activeCorpus?.title}
                </p>
                <div className="mt-1 flex items-end justify-between gap-4">
                  <div>
                    <h1 className="text-[24px] font-semibold tracking-[-0.03em] text-neutral-800">
                      {activeTitle}
                    </h1>
                    <p className="mt-1 text-[12px] text-muted-foreground">
                      {searchCollection
                        ? `All ${activeCorpus?.documents.length} PDFs Â· ${activePages.toLocaleString()} pages Â· one conversation`
                        : `${activePages.toLocaleString()} pages Â· this document only`}
                    </p>
                  </div>
                  <span className="rounded-full bg-neutral-100 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.09em] text-neutral-500">
                    Active
                  </span>
                </div>
                <div className="mt-4" aria-label="Search scope">
                  {searchCollection ? (
                    <p className="text-[12px] leading-relaxed text-neutral-500">
                      Every question searches this library. Follow-ups share the same conversation; citations open the original PDF.
                    </p>
                  ) : (
                    <button
                      type="button"
                      disabled={running}
                      onClick={() => activeCorpus && handleSelectCollection(activeCorpus.corpus_id)}
                      className="rounded-full bg-neutral-100 px-4 py-2 text-[12px] font-medium text-neutral-600 transition-colors hover:bg-neutral-200 disabled:opacity-50"
                    >
                      Open shared session for all {activeCorpus?.documents.length} PDFs
                    </button>
                  )}
                </div>
              </header>

              <ChatContainerRoot className="min-h-0 flex-1 px-7">
                <ChatContainerContent className="mx-auto flex max-w-[780px] flex-col gap-5 py-6">
                  {thread.length === 0 && !activeTurn && (
                    <div className="flex flex-col gap-2 py-6">
                      <p className="mb-3 text-center text-[13px] leading-relaxed text-muted-foreground">
                        {searchCollection
                          ? "Ask across documents, compare their guidance, and keep following up here. Open any citation to inspect its source PDF."
                          : "Ask for a fact or an explanation. Open a source citation to check the original page."}
                      </p>
                      {suggestions.map((suggestion) => (
                        <PromptSuggestion
                          key={suggestion}
                          onClick={() => submit(suggestion)}
                        >
                          {suggestion}
                        </PromptSuggestion>
                      ))}
                    </div>
                  )}

                  {thread.map((turn) => (
                    <TurnView
                      key={turn.id}
                      turn={turn}
                      floor={meta?.relevance_floor ?? 0.42}
                      onViewSource={handleViewPage}
                      onShowSources={handleShowSources}
                    />
                  ))}
                  {activeTurn && (
                    <TurnView
                      turn={activeTurn}
                      floor={meta?.relevance_floor ?? 0.42}
                      onViewSource={handleViewPage}
                      onShowSources={handleShowSources}
                    />
                  )}
                </ChatContainerContent>
              </ChatContainerRoot>

              <div className="bg-white px-7 pb-5 pt-3">
                <PromptInput
                  value={input}
                  onValueChange={setInput}
                  isLoading={running}
                  onSubmit={() => submit(input)}
                  className="mx-auto max-w-[780px] border-0 bg-neutral-100 shadow-none"
                >
                  <PromptInputTextarea
                    aria-label={`Question about ${activeTitle}`}
                    placeholder={searchCollection ? `Ask across all ${activeCorpus?.documents.length} PDFs` : `Ask a question about ${activeTitle}`}
                  />
                  <PromptInputActions className="justify-between px-1 pt-2">
                    <span className="text-[10.5px] font-medium text-muted-foreground">
                      {searchCollection ? `Searching all ${activeCorpus?.documents.length} PDFs` : `Searching ${activeTitle} only`}
                    </span>
                    {/* PromptInputAction cannot wrap this Button: both primitives
                        render buttons, which would create invalid nested markup. */}
                    <Button
                      size="icon"
                      aria-label={running ? "Stop generating" : "Send"}
                      disabled={!running && (!input.trim() || apiDown)}
                      className="size-9 rounded-full bg-neutral-800 hover:bg-neutral-700"
                      onClick={() => (running ? cancel() : submit(input))}
                    >
                      {running ? (
                        <Square className="size-4 fill-white text-white" />
                      ) : (
                        <ArrowUp className="size-5 text-white" />
                      )}
                    </Button>
                  </PromptInputActions>
                </PromptInput>
              </div>
            </>
          )}
        </main>

        <aside className="flex min-h-[480px] min-w-0 flex-col overflow-hidden rounded-[24px] bg-neutral-100 lg:col-span-2 lg:min-h-0 xl:col-span-1 xl:h-full">
          <div id="evidence-panel" className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
            {evidenceTurn && (
              <p className="mb-3 px-1 text-[12px] leading-relaxed text-neutral-500">
                Sources for: <span className="text-neutral-700">{evidenceTurn.question}</span>
              </p>
            )}
            {evidenceTurn?.streaming && evidenceTurn.segments.length === 0 ? (
              <div className="flex flex-col gap-3">
                <h2 className="text-[12px] font-semibold uppercase tracking-[0.11em] text-neutral-500">
                  Evidence
                </h2>
                <div className="px-1 py-2">
                  <PipelineTrace
                    turn={evidenceTurn}
                  />
                </div>
              </div>
            ) : (
              <EvidenceRail
                segments={evidenceTurn?.segments ?? []}
                cited={evidenceTurn?.cited ?? []}
                emptyMessage={
                  hasActiveSession
                    ? searchCollection ? "Sources from across this library will appear here, with their document names and pages." : EMPTY_EVIDENCE
                    : "Choose a library or a single PDF to start a session."
                }
                readingVisuals={readingVisuals}
                onViewPage={handleViewPage}
              />
            )}
          </div>
          <div className="p-4 pt-2">
            <ProvenancePanel meta={meta} />
          </div>
        </aside>
      </div>
      <PageViewer
        segment={viewerSegment}
        totalPages={meta?.corpora.flatMap((corpus) => corpus.documents).find((document) => document.doc_id === viewerSegment?.doc)?.pages ?? 0}
        onClose={closePageViewer}
      />
    </div>
  )
}
