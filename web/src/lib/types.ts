export type Mode = "mrag" | "text_only" | "plain"

export type StageName = "route" | "retrieve" | "read" | "answer"

export type SegmentType = "text" | "figure" | "table"

export type Provenance =
  | "grounded"
  | "page_addressed"
  | "general"
  | "out_of_scope"
  | "uncovered"
  | "unsupported"
  | "plain"

export type Segment = {
  label: string
  segment_id: string
  doc: string
  doc_title: string
  page: number
  type: SegmentType
  score: number
  text: string
  image_url: string | null
  page_url: string | null
  bbox: [number, number, number, number] | null
}

export type RouteInfo = {
  route: "datasheet" | "general" | "out_of_scope"
  search_query: string
  page: number | null
  confidence: number
  reason: string
  fallback: boolean
}

export type Timings = {
  route?: number
  retrieve?: number
  first_token?: number
  total?: number
}

export type ChatEvent =
  | { type: "stage"; stage: StageName; status: "active" | "done" }
  | ({ type: "route" } & RouteInfo)
  | {
      type: "evidence"
      grounded: boolean
      page_addressed: boolean
      requested_page: number | null
      top_score: number
      segments: Segment[]
    }
  | { type: "token"; text: string }
  | {
      type: "done"
      answer: string
      cited: string[]
      provenance: Provenance
      timings_ms: Timings
      models: { generation: string; router: string }
    }
  | { type: "error"; message: string }

export type HistoryMessage = { role: "user" | "assistant"; content: string }

export type DocumentMeta = {
  doc_id: string
  title: string
  pages: number
  segments: number
  text: number
  figures: number
  tables: number
  text_vectors: number
  visual_vectors: number
  visual_share: number
  has_pdf: boolean
}

export type CorpusMeta = {
  corpus_id: string
  title: string
  blurb: string
  evaluated: boolean
  documents: DocumentMeta[]
  totals: {
    documents: number
    pages: number
    segments: number
    text_vectors: number
    visual_vectors: number
    vectors: number
  }
  index: { type: string; normalized: boolean; dimensions: number }
}

export type Meta = {
  corpora: CorpusMeta[]
  models: { embedding: string; generation: string; router: string }
  relevance_floor: number
}

/** One assistant turn, accumulated from the event stream. */
export type Turn = {
  id: string
  scope?: "document" | "collection"
  mode: Mode
  question: string
  answer: string
  stages: { stage: StageName; status: "active" | "done" }[]
  route: RouteInfo | null
  segments: Segment[]
  grounded: boolean
  pageAddressed: boolean
  requestedPage: number | null
  topScore: number
  cited: string[]
  provenance: Provenance | null
  timings: Timings
  models: { generation: string; router: string } | null
  error: string | null
  streaming: boolean
}
