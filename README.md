# M-RAG: multimodal retrieval over hardware datasheets

I built M-RAG to answer questions about hardware datasheets when the answer sits in a figure or table. Pinout diagrams, package drawings and dense electrical-characteristics tables hold most of the values an engineer looks up, and plain text extraction misses them. The pipeline parses each datasheet into text chunks, figures and tables, captions every figure and table with a vision model, and indexes captions and text in one embedding space. At question time it retrieves the top segments, attaches the original crops of any figures or tables to the model call, and answers with inline citations that open the source page. It is for engineers and students who work from datasheets and want page-level evidence. The hardware corpus covers five datasheets. A second corpus of 20 STM32F103 reference documents is indexed but not evaluated.

## Results

I scored both methods by hand on 18 questions over the five hardware datasheets. Thirteen need a value or mapping from a figure or table. Five are prose controls. Both methods share text extraction, 300 to 500 token chunking, `text-embedding-3-large` embeddings, top-5 exact retrieval and `gpt-5.6-sol` generation. The text-only index is the same index with the visual-caption vectors removed, so the visual vectors and their attached crops are the only variable.

| Question split | Method | Correct | Accuracy |
|---|---|---:|---:|
| Visual-required (13) | M-RAG | 8 | 61.5% |
| Visual-required (13) | Text-only | 0 | 0.0% |
| Prose controls (5) | M-RAG | 4 | 80.0% |
| Prose controls (5) | Text-only | 4 | 80.0% |
| All (18) | M-RAG | 12 | 66.7% |
| All (18) | Text-only | 4 | 22.2% |

Text-only gave one partially correct visual answer, which does not count as correct.

Sources: `eval/RESULTS.md` (summary tables) and `eval/results.csv` (36 rows, one per method and question, with manual `answer_score` and `retrieval_hit` columns).

The sample is small. One visual question is worth 7.7 points. The eval covers one domain and one grader. The head-to-head against a consumer chat product in `eval/chatgpt_comparison.md` is a blank template, so that comparison has not been run.

## How it works

The hardware corpus runs these stages in order. The STM32 collection runs the same stages through `scripts/ingest_collection.py`.

1. **Parse.** `scripts/parse.py` runs MinerU over each PDF in `data/raw/hardware/`. It tries the VLM backend first and falls back to the pipeline backend. The output is normalized into `segments.json` with `text`, `figure` and `table` segments, page numbers and crop images. `--pages-per-batch` splits long documents.
2. **Bounding boxes.** `scripts/extract_bboxes.py` matches each visual segment to its MinerU region and writes `bboxes.json`. The page viewer uses these to highlight the source area.
3. **Caption.** `scripts/caption.py` sends each figure or table crop to `gpt-5.6-luna` (default) or `gpt-5.6-terra`. The prompt asks for a dense transcription with labels, units and min/typ/max values. Captions go into `caption` and `caption_model` in `segments.json` and are cached in `caption_cache.json`.
4. **Chunk and embed.** `scripts/embed_and_index.py` chunks prose into balanced pieces of 300 to 500 tokens by a whitespace-token estimate, keeps each caption as its own record, and embeds everything with `text-embedding-3-large`. Vectors are normalized. Embeddings are cached in `embedding_cache.jsonl`.
5. **Index.** The same matrix feeds two exact `IndexFlatIP` FAISS indexes. `mrag_index.faiss` holds text and visual captions. `text_only_index.faiss` holds the leading text rows only. `metadata.jsonl` maps each vector ID to its segment, document, page, type and image path.
6. **Route.** `scripts/agent.py` (`route_question`) asks `gpt-5.6-luna` for a JSON route: `datasheet`, `general` or `out_of_scope`. For datasheet questions it also returns a standalone search query and a page number if the user named one. Malformed output falls back to `datasheet` retrieval.
7. **Retrieve.** `gather_evidence` calls `scripts/query.py` (`retrieve`), which embeds the query, runs exact search and applies an optional document or page filter. Collection-scope questions go through `scripts/linked_retrieval.py`, which drops navigation text and diversifies hits so one long manual does not fill the context.
8. **Gate.** If the top cosine score is below `RELEVANCE_FLOOR` (0.42), the answer says the detail could not be verified from the sources found. I set that threshold from score distributions on this index and have not tested it on another.
9. **Generate.** `answer_stream` calls `gpt-5.6-sol`. Visual hits go in as their original crops next to their captions. Text hits go in as text. The model must cite segments inline as `[S1]`, `[S2]` and so on. `cited_labels` keeps only citations that match retrieved labels, and `provenance` classifies the answer as `grounded`, `page_addressed`, `general`, `out_of_scope`, `uncovered` or `unsupported`.
10. **Azure boundary.** `scripts/azure_client.py` is the only module that imports the OpenAI SDK. It exposes `embed_text`, `generate` and `generate_stream`, retries transient errors, and can enforce an optional spend ledger (`scripts/usage_budget.py`).

Plain mode skips stages 6 to 9 and sends the question straight to `gpt-5.6-sol`. The demo uses it as a no-retrieval control.

The one-shot path `scripts/query.py` (`query`) is the code that produced `eval/results.csv`. `scripts/eval_runner.py` runs both methods over `eval/questions.jsonl`. It leaves the grade columns blank for manual scoring.

## API

The FastAPI app is in `api/server.py`. On startup it loads the registry, index metadata, crop paths and bounding boxes once.

- `GET /api/health` returns `{"status": "ok", "indexes_ready": true}`.
- `GET /api/meta` returns corpora, document and vector counts, model names and `relevance_floor`.
- `POST /api/chat` streams one turn as server-sent events. Body fields: `message` (required), `mode` (`mrag`, `text_only` or `plain`), `doc`, `corpus_id`, `scope` (`document` or `collection`), `history` (the last six messages are used) and `k` (1 to 20, default 5). An unknown `doc` or `corpus_id` returns 404. Mismatched selectors return 422.
- `GET /api/image/{segment_id}` returns the crop for a visual segment.
- `GET /api/page/{doc}/{page}` renders one PDF page at 144 DPI and caches it in `data/page_cache/`.
- `/` serves the exported Next.js UI from `api/static/` when that directory exists.

Each event is a `data: <json>` line followed by a blank line. The event types are:

```json
{"type":"stage","stage":"route|retrieve|read|answer","status":"active|done"}
{"type":"route","route":"datasheet|general|out_of_scope","search_query":"...","page":null,"confidence":0.9,"reason":"...","fallback":false}
{"type":"evidence","grounded":true,"page_addressed":false,"requested_page":null,"top_score":0.61,"segments":[{"label":"S1","segment_id":"...","doc":"...","doc_title":"...","page":10,"type":"figure","score":0.6,"text":"...","image_url":"/api/image/...","page_url":"/api/page/.../10","bbox":null}]}
{"type":"token","text":"..."}
{"type":"done","answer":"...","cited":["S1"],"provenance":"grounded","timings_ms":{"route":0,"retrieve":0,"first_token":0,"total":0},"models":{"generation":"...","router":"..."}}
{"type":"error","message":"..."}
```

A datasheet turn emits `stage route active`, the `route` event, `stage route done`, `stage retrieve active`, `evidence`, `stage retrieve done`, `stage read active` when visual evidence supports it, `stage answer active`, the `token` events, `stage read done` on the first token, and `done`. The web client in `web/src/lib/api.ts` stops reading at `done` or `error`.

## Run it locally

You need Python 3.10 to 3.13 (I use 3.12) and either an Azure OpenAI resource with the deployments below, or free mode.

**Free mode** needs no Azure account. Put `EMBED_PROVIDER=local` and `LLM_PROVIDER=codex` in `.env`: queries are embedded with `BAAI/bge-m3` on your machine against the committed `index/local` indexes, and answers come from the Codex CLI signed in to a ChatGPT account. Install `requirements-local.txt` on top of the demo requirements, and run `python -m scripts.preflight` to check the setup. On Windows, `run.bat` does all of this when no `.env` exists; `START-HERE.md` walks through it. The hand-graded evaluation describes the Azure index only.

1. For Azure, copy `.env.example` to `.env` and set these variables. `scripts/config.py` requires all seven when a provider is `azure` (the default):
   - `AZURE_OPENAI_API_KEY`
   - `AZURE_OPENAI_ENDPOINT`
   - `AZURE_OPENAI_API_VERSION`
   - `AZURE_OPENAI_SOL_DEPLOYMENT` (answers and plain mode)
   - `AZURE_OPENAI_LUNA_DEPLOYMENT` (routing and default captioning)
   - `AZURE_OPENAI_TERRA_DEPLOYMENT` (alternate captioning)
   - `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` (`text-embedding-3-large`)

2. Install and start the API:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-demo.txt
.venv\Scripts\python.exe -m uvicorn api.server:app --port 8000
```

Open http://localhost:8000. `run.bat` runs the same install and start steps and opens the browser.

3. Rebuild the hardware indexes. This needs `requirements.txt` (which pulls in MinerU and its model dependencies) and makes paid Azure calls for captioning and embedding:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m scripts.parse
.venv\Scripts\python.exe -m scripts.extract_bboxes
.venv\Scripts\python.exe -m scripts.caption
.venv\Scripts\python.exe -m scripts.embed_and_index
```

Restart the API after a rebuild. It loads indexes at startup.

4. Ask one question from the command line. The output is JSON with retrieved segment IDs and the answer:

```powershell
.venv\Scripts\python.exe -m scripts.query "Which module pin is TXD0 on the ESP32-WROOM-32E?" --mode mrag
```

5. Rerun the evaluation. This makes paid calls and writes to `eval/results.csv` by default, which overwrites the committed grades. Pass `--output` to write somewhere else.

```powershell
.venv\Scripts\python.exe -m scripts.eval_runner --output eval\results_rerun.csv
```

6. Optional: run the Next.js UI in dev mode on port 3000. Its API base defaults to `http://localhost:8000`, and `NEXT_PUBLIC_API_BASE` overrides it. The API's CORS config allows `localhost:3000`.

```powershell
cd web
pnpm install
pnpm dev
```

7. Tests use `unittest`. Run from the repo root:

```powershell
.venv\Scripts\python.exe -m unittest discover -p "test_*.py"
```

## Repo layout

- `api/`: FastAPI app (`server.py`), request model (`models.py`) and the exported UI in `static/`.
- `scripts/`: parsing, captioning, indexing, retrieval, generation, eval runner, STM32 collection tooling, and `test_*.py` unit tests.
- `web/`: Next.js 16 frontend source. `next.config.ts` sets `output: "export"`. The exported files live in `api/static/`, which the API serves.
- `app/`: older Streamlit demo UI. `run.bat` does not use it. It is still listed in `.claude/launch.json`.
- `paper/`: scripts and figures for the write-up.
- `eval/`: hand-written questions, graded results, the summary, and the blank ChatGPT comparison template.
- `corpora.json`: the corpus and document registry that the API and scripts read. Each corpus has an `evaluated` flag.
- `data/raw/`: source PDFs. `hardware/` has the five datasheets. `stm32/` has 20 ST documents with `*.source.json` provenance. `atmega_revision_study/` has three files that are not registered in `corpora.json`.
- `data/parsed/`: per-document MinerU output, `segments.json`, `bboxes.json`, crop images and `caption_cache.json`. Most of the repo's size is here.
- `data/collections/`: STM32 collection catalog and README.
- `data/page_cache/`: rendered page PNGs, created at runtime and gitignored.
- `index/`: FAISS indexes, `metadata.jsonl` and `run_metadata.json` for the hardware corpus. `index/stm32/` holds the collection's indexes. Embedding caches are gitignored.
- `output/`: logs, verification JSON and screenshots from builds and checks. Nothing reads these at runtime.
- `.agents/`, `.claude/`: agent skill copies and the launch configuration.
- `run.bat`, `START-HERE.md`: Windows launcher and setup guide for the demo.

## Limitations

- One domain, five datasheets, 18 hand-written questions, one grader. The eval does not test the cross-domain claim.
- Retrieval is the bottleneck. Multimodal retrieval missed 5 of 13 visual sources. Misses include ESP32 electrical values, RP2040 limit and timing values, and an LM317 table that never reached top-5. The RESULTS file records the details.
- Visual retrieval depends on caption quality. Captions come from a vision model and are not checked against the image.
- The relevance floor is calibrated on this index only.
- Answers and indexing depend on Azure OpenAI. Nothing runs offline, and both indexing and evaluation cost money.
- The API has no authentication. `run.bat` binds to localhost by default. Do not expose port 8000 without adding auth, because every chat request spends against the Azure key.
- The STM32 collection is a historical reference set, not the latest release, and it is not evaluated. Some files came from third-party mirrors, which `data/raw/stm32/manifest.json` records. Vendor PDFs and mirror copies are committed for reproducibility. Their redistribution terms belong to the vendors.
- About 680 MB of PDFs, crops and indexes are committed in `data/` and `index/`.
- `requirements.txt` has no version pins. `requirements-demo.txt` is pinned.
- The launcher and setup guide are Windows-only. The Python entry points should run elsewhere, but the docs do not cover that.
- The ChatGPT head-to-head has not been run.
