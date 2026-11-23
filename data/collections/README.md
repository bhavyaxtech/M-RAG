# STM32 connected-document collection

## What is here

20 distinct ST-authored documents, **1,837 physical PDF pages**, focused on STM32F103 medium-density devices and related STM32F1 programming/design guidance. This is a historical research collection, **not a latest-release engineering reference**. Broad-family manuals and notes require device/density checks; errata additionally require silicon-revision checks.

Manufacturer downloads timed out during collection. The existing datasheet was reused; the other files were obtained from explicitly recorded mirrors. Covers/document IDs and checksums were checked. Mirror files were not byte-compared with live manufacturer downloads. `data/raw/stm32/manifest.json` records provenance, cover text, physical page counts, revisions, and document references with source pages. The catalog distinguishes manufacturer URLs from download URLs.

| ID | Document | Physical pages | Document revision |
|---|---|---:|---|
| DS5319 | STM32F103x8/xB datasheet | 114 | 20 |
| RM0008 | STM32F1 reference manual | 1134 | 20 |
| ES096 | STM32F101/102/103 medium-density errata | 31 | 15 |
| PM0056 | Cortex-M3 programming manual | 156 | 6 |
| PM0075 | STM32F10xxx Flash programming manual | 31 | 2 |
| AN2586 | STM32F10xxx hardware development | 28 | 7 |
| AN2594 | STM32F10xxx EEPROM emulation | 16 | 3 |
| AN2606 | STM32 system-memory boot mode | 27 | 9 |
| AN3155 | USART protocol used in STM32 bootloader | 37 | 2 |
| AN2834 | Improving STM32 ADC accuracy | 28 | 1 |
| AN3116 | STM32F10xxx ADC modes and applications | 18 | 1 |
| AN2548 | Using STM32F0/F1/F3/Gx/Lx DMA controller | 14 | 3 |
| AN2824 | STM32F10xxx I2C optimized examples | 16 | 4 |
| AN2820 | Driving bipolar stepper motors with STM32F103 | 23 | 2 |
| AN2629 | STM32F10xxx low-power modes | 43 | 2 |
| AN2557 | STM32F10xxx in-application programming over USART | 16 | 8 |
| AN2821 | STM32F10xxx RTC clock/calendar implementation | 28 | 2 |
| AN2867 | Oscillator design guide for STM32 MCUs | 23 | 3 |
| AN1709 | EMC design guide for STM8 STM32 and legacy MCUs | 38 | not extracted |
| AN2592 | 32-bit timer resolution using STM32F101/F103 timer linking | 16 | 1 |

There are 18 directed document-reference relationships within the selected collection, extracted from explicit document IDs printed in the PDFs. These are evidence of a reference, not automatic evidence of applicability or precedence.

Some archived PDFs have inconsistent printed page-total footers. Citations and the page viewer use **one-based physical PDF page numbers**. The principal RM0008 file here is revision 20 and 1,134 physical pages; it is not the 1,136-page edition mentioned during initial planning.

## Run / resume

From the repository root with the existing virtual environment:

```powershell
.venv/Scripts/python.exe -m scripts.collect_stm32
.venv/Scripts/python.exe -m scripts.ingest_collection
.venv/Scripts/python.exe -m scripts.ingest_collection --execute --stage parse
.venv/Scripts/python.exe -m scripts.ingest_collection --execute --stage pilot
.venv/Scripts/python.exe -m scripts.ingest_collection --execute --stage build
.venv/Scripts/python.exe -m scripts.collection_status
```

The no-flag ingestion command performs no API calls and writes a timestamped progress snapshot to `output/stm32/preflight.json`: completed documents/pages, completed batches in the current document, and cached captions. After inspecting the three-caption pilot, `--execute --stage all` resumes parsing and then captions/indexes the collection. Do not run two parsing jobs or two caption/index writers simultaneously. The optional `--execute --stage caption` prepares already-completed documents while a separate parser is still working; wait for both workers before starting the final build. Parsing uses full MinerU's pipeline backend in resumable page batches; no text-extraction fallback is being substituted. Captions and embeddings are cached. Source checksum changes stop reuse rather than silently mixing artifacts.

For this large reference manual, `python -m scripts.prepare_batches --execute --workers 4` prepares reusable captions/embeddings from the contiguous completed RM0008 batches while parsing continues. The final build accepts `--caption-workers 4`; both commands default to one request at a time. This parallelizes Azure requests, not the GPU parser. One coordinator writes caption caches, successful in-flight results are saved even when another request fails, and the shared usage ledger remains serialized. Stop or finish the progressive worker before starting the final build; both own the same single-writer lock.

`scripts.collection_status` is read-only and also accepts `--json`. It distinguishes finalized PDFs, partial page coverage, and progressive caption snapshots. Progressive counts may overlap canonical caches and must not be added blindly to finalized totals. Page-parsing percentages are not end-to-end completion percentages.

The identical DS5319 file reuses the existing full MinerU parse and 139 cached captions. PDF checksums, every visual crop, and segment identity were verified before reuse. Original hardware artifacts were not modified. The reuse receipt records that historical caption model snapshots are unavailable rather than assigning today's model snapshot to older captions.

Long captions and dense text are split below the embedding model's input limit using its tokenizer, without truncation. Split captions retain the original document, page, crop, and bbox identity. Small inputs retain their cache keys. Visual page overlays are generated before publication.

The new indexes are separate under `index/stm32/`. Both retrieval methods share the same text chunking and embeddings. The original hardware indexes and scored evaluation files are not rebuilt. Only a complete 20-document build is added to `corpora.json`; restart the API after publication because it loads its registry/index metadata at startup.

## Using the app

Choose **Chat with all 20 PDFs** in the STM32 library on the landing page or sidebar. This opens one shared library session without selecting a PDF. Every question searches the STM32 corpus, and follow-ups use that library conversation's history. Individual PDF sessions remain available and separate. Switching to a PDF and back preserves the library conversation in the current tab; reloading the page does not persist conversations. **New session** clears only the selected conversation.

Click citations to open the actual source document/page without leaving the library session. A document session also offers **Open shared session for all 20 PDFs**. Collection requests use `scope: "collection"`, `corpus_id: "stm32"`, and `doc: null`; legacy document-anchored collection requests remain supported. Collection mode does not search unrelated corpora. A shared index enables cross-PDF retrieval even when two documents do not explicitly reference one another; extracted reference links guide selection but are not a requirement for a PDF to be searchable.

Collection retrieval embeds the question once, searches the shared exact FAISS index, reserves both introductory and detailed evidence for explicitly named document IDs, follows a bounded number of explicit references printed on retrieved pages, and diversifies the remaining results by document. Original user document IDs are retained even when the router rewrites the question. It is a first implementation, not a proven multi-hop reasoner. The inherited 0.42 relevance threshold has not been calibrated on this collection. Broad comparisons may need more than the default eight evidence segments; API k is capped at 20.

## Verification and limitations

- Offline tests: `python -m unittest scripts.test_chat_behavior scripts.test_collection scripts.test_collection_api scripts.test_collection_status scripts.test_prepare_batches scripts.test_caption_concurrency -v`.
- Frontend transport tests: `node --experimental-strip-types --test web/tests/chat-flow.test.mjs`.
- Frontend build: `npm --prefix web run build`.
- The successful real two-document smoke run is stored separately in `output/stm32/cross_document_smoke.json`. It is **not** a scored 20-document evaluation.
- A subsequent 18-document prepared-subset run in `output/stm32/preview_smoke.json` retrieves and cites all three requested sources (AN2594, AN2557, PM0075) in both modes. It exposed overly aggressive document diversity, so explicitly named sources now retain more detailed passages. Before/after outputs are saved separately. Neither run establishes factual accuracy or complete retrieval; some requested programming restrictions were still not found.
- After all 20 documents are indexed, run `python -m scripts.smoke_collection --execute`. It verifies shared baseline vectors, then checks that a real answer retrieves/cites both named documents in each retrieval mode. Results go to `output/stm32/full_collection_smoke.json`; citation integrity is not a factual-accuracy score, and answers remain ungraded pending human review.
- The local completion queue additionally serves the app on port 8012 and runs `python -m output.stm32.verify_app`. This checks all 20 API document/page counts, first/last-page HTTP rendering, existence of indexed crops, and byte-identical HTTP crops sampled by document. Its report is `output/stm32/app_verification.json`; these are transport/source-integrity checks, not visual QA. Queue progress/failures are recorded in `output/stm32/completion_status.json`.
- Generated captions need human inspection, especially diagrams and complex tables. This session's image-view tool was unavailable; selected pilot captions were checked against selectable PDF text, not a full visual audit.
- New-pipeline metered API calls record exact returned model snapshots and usage in `output/stm32/azure_usage.json`. Local estimated usage is not an Azure account-wide billing cap, and hosted app queries are not part of this ingestion ledger.
- Do not claim that these examples require vision merely because they involve tables: many tables expose selectable text. Compare against a baseline with the same document collection.
