# M-RAG — 2-Day Build Spec (Hardware Datasheet Domain)

## Objective

Build a working Multimodal RAG pipeline for hardware/electronics datasheets, alongside a text-only RAG baseline built on the identical codepath, and produce a real hand-scored evaluation table showing where multimodal retrieval beats text-only retrieval. This is the implementation phase of the M-RAG paper already defended (Meng & Tong's architecture-only system is the prior work being generalized). This build covers one domain, not the cross-domain claim from the full pitch — that scope cut is deliberate and is explained in the "Scope cut vs. the full pitch" section below so it can be stated plainly if asked.

## Locked decisions for this build

- **Domain:** hardware/electronics datasheets only. Two-domain cross-domain validation is out of scope for this build.
- **Parsing:** MinerU2.5-Pro, full pipeline, not a lightweight fallback.
- **Captioning + generation:** GPT-5.6 family (Sol / Terra / Luna), served through Azure OpenAI, not the direct OpenAI API. Inference runs on existing Azure credits. Confirmed GA as of this build (July 9, 2026, pricing reduced further July 30, 2026) — availability of specific deployments still depends on what's been provisioned on the Azure resource, checked in Hour 0.
- **Embeddings:** `text-embedding-3-large`, also served through Azure OpenAI. Same reasoning as before — no native multimodal embedding model exists in this family, so every figure/table gets captioned into text first, and everything (prose chunks + captions) goes through this one text embedder into a shared space. The provider change doesn't affect this reasoning, only the endpoint the embed call hits.
- **Vector store:** FAISS, flat/exact index (`IndexFlatIP`, normalized embeddings). Document count is small enough that approximate indexing (IVF/HNSW) adds complexity with no benefit here.
- **Demo:** Streamlit, single page, light theme, card-based layout. Full UI spec in the Demo section below.

This is the first real exercise of the deployment-agnostic design below — `embed_text()` and `generate()` now point at Azure instead of direct OpenAI, and nothing else in the pipeline changes. If a further swap to local inference happens later, it's the same two function bodies again.

## Scope cut vs. the full pitch

The original pitch (cross-domain, benchmarked M-RAG) argues the differentiator is running the *identical* pipeline across structurally different document types. This build proves the pipeline works and is fairly benchmarked within one domain; it does not prove the cross-domain claim. If a panelist asks why: the honest answer is time — two domains done properly needs double the data collection, double the parsing debugging, and a hand-graded eval set split two ways, none of which fits two days without risking a pipeline that runs on both domains but was never actually validated on either. The architecture is written to be domain-agnostic (nothing below is hardware-specific except the data source and question wording), so adding a second domain later is a data-collection-and-eval-set task, not a re-architecture.

## Deployment-agnostic design (enterprise / local-inference note)

The architecture — parse, embed both modalities into one space, retrieve, generate — does not assume a cloud API. It only assumes something can embed text and something can caption/generate from an image, which local models can do as well as hosted ones. This build uses OpenAI for speed, but the code must not hardcode that assumption: every embedding call goes through one function (`embed_text(text) -> vector`), and every captioning/generation call goes through one function (`generate(prompt, images=None) -> text`), each defined once in `scripts/` and imported everywhere else. Swapping the OpenAI calls inside those two functions for a local endpoint (e.g. Ollama or vLLM serving an open-weight vision model) is then a function-body change, not an architecture change. Do not scatter raw `openai.*` calls across `parse.py`, `caption.py`, `embed_and_index.py`, and `query.py` — every one of those files should call `embed_text()` or `generate()`, never the API client directly. This is the concrete basis for the enterprise/on-prem deployment claim: it should be checkable in the code, not just asserted in the write-up.

## Repo structure

```
mrag-project/
  data/
    raw/hardware/              # source PDFs
    parsed/hardware/<doc>/     # MinerU output: text blocks + cropped images, per doc
  index/
    mrag_index.faiss           # text chunks + visual captions
    text_only_index.faiss      # text chunks only, baseline
    metadata.jsonl             # vector_id -> {doc, page, type, image_path?, text}
  eval/
    questions.jsonl            # QA test set
    results.csv                # scored output
  app/
    streamlit_app.py
    .streamlit/
      config.toml           # light theme, see Demo UI spec
  scripts/
    parse.py
    caption.py
    embed_and_index.py
    query.py
  requirements.txt
  .env                          # OPENAI_API_KEY, not committed
```

## Dataset (Phase 1 — pull these five)

Pick datasheets with both a pinout diagram and a dense electrical-characteristics or timing table, so every document contributes to both the visual-required and control question pools.

- Raspberry Pi Pico (RP2040) datasheet — raspberrypi.com
- Espressif ESP32-WROOM-32E/UE datasheet — espressif.com
- Microchip ATmega328P datasheet — microchip.com
- Texas Instruments LM317 datasheet — ti.com
- STMicroelectronics STM32F103C8 datasheet — st.com

All five are public manufacturer PDFs, no login wall, no license ambiguity. Confirm the exact current URL for each on Day 1 Hour 1 rather than trusting a hardcoded link — manufacturer doc paths shift.

## Build plan

### Day 1 — parsing through indexing (~10 hours)

**Hour 0–1: Environment setup.** Install `mineru` (`pip install mineru`, currently in the 3.1.x/3.3 line, Apache-based license since v3.1.0 so no AGPL contamination concern). `gpt-5.6-sol` and `gpt-5.6-luna` are very likely already deployed on the Azure resource from prior LiteLLM proxy work — confirm they still exist under those names and, critically, confirm they accept image input (that prior work only exercised text chat completions, never vision). `gpt-5.6-terra` should also already exist as a deployment; keep it as a captioning fallback, not the default — spot-check two or three real table captions with Luna first and only switch if something's actually wrong. The one deployment that's genuinely new is `text-embedding-3-large`; create it if it isn't already there. Deployment type (Standard vs. Global Standard) isn't worth deliberating on a Tier 5 resource — default quota at that tier is well past anything this project's call volume touches. Set `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, and the four deployment names in `.env`; `embed_text()`/`generate()` read deployment name from config, not a hardcoded model string, since Azure calls route by deployment name rather than model name. If the LiteLLM proxy is still running, pointing `embed_text()`/`generate()` at its OpenAI-compatible endpoint instead of the raw Azure SDK skips re-solving auth and routing that's already working. Install `faiss-cpu`, `streamlit`, `pymupdf`, `tenacity`.

*Guardrail:* MinerU2.5-Pro's default backend can be GPU-heavy. If setup stalls past the 1-hour box or no GPU is available, switch to MinerU's non-VLM pipeline backend — same tool, same decision (full MinerU2.5-Pro), lighter runtime mode. Do not silently swap to a different parser; swap the backend flag only.

Retry-with-backoff on `embed_text()`/`generate()` (`tenacity`, a few lines) is still worth having as basic hygiene against transient network errors, but on a Tier 5 resource it's not covering a real rate-limit risk — the Hour 7–9 captioning batch is nowhere near that ceiling.

**Hour 1–3: Data collection.** Download the five datasheets into `data/raw/hardware/`.

**Hour 3–7: Parsing.** Run MinerU on all five PDFs. Output per document: segments tagged `type: "text" | "figure" | "table"`, with doc name, page number, and for visual segments a path to the cropped image plus any caption MinerU found nearby. This is the highest-risk block — dense electrical tables are exactly where layout parsers mis-segment, so it gets the largest time box. Save structured JSON per document under `data/parsed/`.

**Hour 7–9: Captioning.** For every `figure`/`table` segment, send the cropped image to GPT-5.6 Luna (cheap, high-volume — this runs once per figure, potentially 30–60 calls across five datasheets) with a prompt demanding a dense, factual description: actual pin numbers and labels in a pinout diagram, actual numeric ranges in an electrical-characteristics table. Not a vague one-line caption. Cache every caption to disk keyed by segment ID before moving on — do not regenerate on reruns.

**Hour 9–10: Embedding and indexing.** Chunk text segments to roughly 300–500 tokens. Embed every text chunk and every visual caption with `text-embedding-3-large`. Build `mrag_index` (everything) and `text_only_index` (text chunks only, excluding visual-caption vectors — nearly free once `mrag_index` exists). Write `metadata.jsonl` mapping vector ID to displayable info.

### Day 2 — retrieval, eval, demo (~10 hours)

**Hour 0–2: Retrieval + generation wiring.** Implement the query path: embed the query, retrieve top-k (k=5) from the relevant index. M-RAG path: for any retrieved figure/table segment, load the actual cropped image (not just its caption) alongside retrieved text chunks, send query + text + images to GPT-5.6 Sol in one generation call. Text-only path: identical flow against `text_only_index`, where nothing visual is ever attached. Smoke-test with two or three manual questions before moving to the eval set — confirm the pipeline actually runs end to end before spending time writing questions against it.

**Hour 2–4: Build the eval set.** 18 questions total in `eval/questions.jsonl`, fields: `question, doc, ground_truth_answer, requires_visual (true/false)`.
- 13 questions where the ground-truth answer exists only in a figure or table, not restated in prose (e.g. "What is the maximum continuous output current listed in the LM317's electrical characteristics table?", "Which GPIO pin is mapped to UART0 TX on the ESP32-WROOM-32E pinout diagram?").
- 5 control questions where the answer is in the prose text, to confirm M-RAG doesn't regress on ordinary text questions.

**Hour 4–6: Run the comparison.** Run all 18 questions through both pipelines. Log per question: retrieval hit (was the correct source segment in the top-k, yes/no) and the generated answer, to `eval/results.csv`.

**Hour 6–7: Score and build the results table.** Grade by hand: correct / partially correct / incorrect / no answer, against ground truth. At 18 questions × 2 pipelines this is 36 gradings — faster and more trustworthy than standing up an automated judge at this scale. Produce a results table: method × (retrieval hit rate, answer accuracy), split by `requires_visual`.

**Hour 7–9: Streamlit demo.** Build against the UI spec below, not default Streamlit styling — this gets driven live in front of a panel, so the visual gap between "default Streamlit app" and "deliberately designed interface" is worth the time box it's given.

**Hour 9–10: Write-up, rehearsal, buffer.** One-page results write-up tying the numbers to the stated hypothesis. Reserve the tail of this block for whatever broke earlier and didn't get fixed in place.

## Demo UI spec

Light theme, forced via `.streamlit/config.toml` rather than left to client default (Streamlit's dark-mode auto-detection is not reliable enough to trust for a live demo):

```toml
[theme]
base="light"
primaryColor="#2563EB"
backgroundColor="#FFFFFF"
secondaryBackgroundColor="#F3F4F6"
textColor="#111827"
font="sans serif"
```

Type scale, applied via one injected CSS block at the top of `streamlit_app.py` — Streamlit's default heading sizes are inconsistent across versions, so don't rely on `st.title`/`st.header` defaults alone:

- Page title: 26–28px, semibold
- Section labels ("Retrieved segments", "Answer"): 15px, semibold, slight letter-spacing, uppercase
- Body and answer text: 16px, regular, 1.5 line height
- Segment metadata (source doc, page, type badge): 12–13px, medium weight, muted gray
- Query input text: 16px, matches body

Layout, top to bottom:

1. **Header block.** Title, one-line description. Domain is fixed text, not a selector — this build is single-domain, a dropdown with one option is worse than no dropdown.
2. **Toggle.** M-RAG vs. text-only baseline, styled as a two-option pill/segmented control, not a default checkbox — this is the control the whole demo hinges on, it should read as the primary interactive element.
3. **Query block.** Bordered container (`st.container(border=True)`), text input plus submit button, full width.
4. **Results, two columns on desktop / stacked on narrow width.** Left: "Retrieved segments" as a bordered card containing one smaller bordered sub-card per retrieved segment — each sub-card shows a type badge (Text / Table / Figure), source document and page number, and content (rendered image for visual hits, text snippet for text hits). Right: "Answer" as its own bordered card, larger body text, with a small metadata footer showing which model/deployment generated it — this footer is what makes defense-critical output #5 (model/version logged per run) visible in the demo itself, not just in a CSV.

Every retrieved segment renders, not only the one most used in the answer — this is what makes the multi-segment claim (differentiation point 5 in the pitch) demonstrable live instead of asserted.

## Defense-critical outputs — verify before presenting

Carried over from the full spec, minus the domain-breakout requirement (moot at one domain).

1. `eval/results.csv` contains real scored rows from an actual run, not placeholder data. This is the single output that matters most.
2. `results.csv` has `retrieval_hit (bool)` and `answer_score` as distinct fields, never merged into one pass/fail number. A wrong answer with a correct retrieval hit is a generation failure; a wrong answer with a failed retrieval hit is a retrieval failure — these need to be tellable apart.
3. `text_only_index` is built from the exact same chunking and embedding code path as `mrag_index`, just excluding visual-caption vectors — not a separately built comparison system.
4. The Streamlit demo shows all top-k retrieved segments, not only the one used most heavily in the answer — this is what makes "we don't restrict to a single top-1 pair" demonstrable live.
5. The exact embedding and captioning/generation model names and versions used are logged alongside the run output (in the CSV or a run-metadata file) — needed to answer "what exactly did you use" if asked.

## Implementation notes

- Cache captions and embeddings to disk after generating them once. Reruns during debugging should never re-hit the API for segments already processed.
- Do not hand-roll OCR or layout parsing. MinerU already does this — wrapping its output is the job.
- Do not attempt to reimplement any of the literature-review models (LayoutLM, LayoutLMv3, Donut, BLIP-2, VisualBERT, CLIP). Those are surveyed prior work establishing the approach is sound, not a build checklist.
- Verify exact OpenAI model name strings against the live account before hardcoding them into scripts — snapshot suffixes shift and a stale hardcoded name is a common last-minute break.
