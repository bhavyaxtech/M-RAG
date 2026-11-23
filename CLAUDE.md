# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

`AGENTS.md` above is the original 2-day build spec and the source of truth for locked decisions (domain, parser, models, vector store, defense-critical outputs). It is written as a forward-looking plan. The pipeline it describes is now built and has been run end to end: five datasheets parsed, captioned, indexed, and hand-scored in `eval/results.csv` / `eval/RESULTS.md`. Read the notes below for what actually exists.

## Running things

All scripts import `scripts.*`, so run them as modules from the repo root, never as file paths:

```bash
python -m scripts.test_azure
```

```bash
python -m scripts.parse
python -m scripts.caption
python -m scripts.embed_and_index
python -m scripts.query "Which module pin is TXD0 on the ESP32-WROOM-32E?" --mode mrag -k 5
python -m scripts.eval_runner
```

Each takes `--help`. Useful flags: `parse.py --pipeline-only` (CPU/no-GPU MinerU backend), `--normalize-only` (re-derive `segments.json` from an existing MinerU run without re-inferring), `--pages-per-batch N` (long PDFs that blow memory); `caption.py --segment-id ID` (re-caption a handful), `--model terra`; `query.py --mode text_only` (baseline).

There are two demos. The Next.js one is the current judge-facing demo; the Streamlit one is the original and still works.

The Next.js demo needs both processes. API first, from the repo root:

```bash
.venv/Scripts/python.exe -m uvicorn api.server:app --port 8000
```

Then the frontend, which proxies nothing and calls the API directly at `http://localhost:8000`:

```bash
pnpm --dir web dev
```

There is also a **bundled single-process build** for handing the demo to someone
else. `api/static/` holds an exported copy of the Next.js app, and `api/server.py`
mounts it at `/` (last, so every `/api/*` route keeps precedence). Running only the
uvicorn command above then serves the UI and the API together on port 8000, with no
Node.js required on the target machine. `run.bat` wraps that for a non-technical
user: it creates `.venv`, installs `requirements-demo.txt` (no mineru, no torch, no
Streamlit), starts the server and opens a browser. `START-HERE.md` is the setup
guide written for that audience.

**`api/static/` is a build artifact that is committed on purpose.** After changing
anything in `web/src`, regenerate it or the bundled demo silently serves stale UI:

```bash
cd web && NEXT_PUBLIC_API_BASE= pnpm build && cd .. && rm -rf api/static && cp -r web/out api/static
```

The empty `NEXT_PUBLIC_API_BASE` is load-bearing. It makes the export call `/api/...`
relative instead of the hardcoded `http://localhost:8000`, so the bundled UI works
regardless of whether it is opened on `localhost` or `127.0.0.1`. `web/next.config.ts`
carries `output: "export"` and `images: { unoptimized: true }` for the same reason;
`pnpm dev` is unaffected.

The Streamlit demo is standalone and must be launched from `app/`, so Streamlit picks up `app/.streamlit/config.toml` (it resolves that file against the working directory, and the forced light theme is part of the demo spec):

```bash
cd app && streamlit run streamlit_app.py
```

Frontend checks, from `web/`: `npx tsc --noEmit` and `npx eslint src --max-warnings 0`. Both are clean; keep them that way.

Offline unit tests live in `scripts/test_*.py`. Run every module except `test_azure.py`, which is a live smoke test against Azure:

```bash
python -m unittest $(ls scripts/test_*.py | grep -v test_azure | sed 's#/#.#; s#\.py$##')
```

Each test module imports `scripts._test_env` first, which pins both providers to `azure` so tests never depend on the local `.env`. New test modules must do the same.

## Providers

`.env` selects providers inside `scripts/azure_client.py`; both default to `azure`.

- `EMBED_PROVIDER=local` embeds with `BAAI/bge-m3` (sentence-transformers, GPU if available) and switches every corpus to `<index_dir>/local/`, i.e. `index/local/` and `index/stm32/local/`. Those indexes come from the same `embed_and_index` code path with their own embedding cache and `run_metadata.json`, so the Azure indexes are never touched. Corpora report `evaluated: false` under it, because the hand-graded results describe the Azure index only. Build them with `EMBED_PROVIDER=local python -m scripts.embed_and_index` (hardware) and `--output-dir index/stm32/local` plus the STM32 doc directories in `document_manifest.json` order; copy that manifest into the local dir too.
- `LLM_PROVIDER=codex` runs router and answer calls through `codex exec` on the user's ChatGPT login: system prompt via `model_instructions_file`, crops via `-i`, read-only sandbox in an empty temp dir, user config ignored. The model is `CODEX_MODEL` or else the account default from `codex debug models`, passed explicitly so provenance is exact. Optional exec flags and `--disable` features are filtered against what the installed CLI reports (`codex exec --help`, `codex features list`), because Codex hard-fails on unknown ones. It streams the answer as one chunk, and each call carries roughly 17-20k input tokens of Codex tool definitions.
- Codex silently ignores unknown `-c` keys, so a build without `model_instructions_file` would drop the system prompt with no error. `python -m scripts.preflight` catches that with a canary token that appears only in the instructions, and checks login, image input and the local embedder. `run.bat` runs it before starting the server, creates a free-mode `.env` when none exists, installs `requirements-local.txt` and the Codex CLI when needed, and starts `codex login` if signed out.
- `RELEVANCE_FLOOR` is per embedding model in `scripts/agent.py`. An embedder without a calibrated floor refuses to start.
- Provider switches set in the process environment beat `.env`; Azure credentials keep the `.env`-wins rule.
- `sentence-transformers` is pinned to 5.x because 6.x requires `transformers>=5`, which breaks MinerU's `transformers<5`.

## Architecture

Four stages, each a standalone CLI writing durable artifacts the next stage reads. Every stage is resumable and cache-backed, so reruns during debugging cost no API calls for already-processed items.

1. `parse.py` shells out to the MinerU CLI (VLM backend, auto-falling back to the pipeline backend), keeps MinerU's raw output under `data/parsed/hardware/<doc>/mineru/`, and normalizes it into `segments.json`: a flat list of `{segment_id, type: text|figure|table, doc, page, text?, image_path?}`. `segment_id` is `<doc>-p<page:04d>-<type>-<n:05d>` and is the join key for everything downstream.
2. `caption.py` sends each figure/table crop to Luna with a dense-transcription prompt and writes the result back into the same `segments.json` as `caption` + `caption_model`, plus a per-document `caption_cache.json` keyed `segment_id -> {model: caption}`. Both are written atomically via temp-file replace, with a checkpoint every 25 segments.
3. `embed_and_index.py` builds one ordered corpus, text records first then visual records, embeds it once with `text-embedding-3-large`, L2-normalizes, and writes both FAISS indexes from that single matrix. Text segments are concatenated per page and re-chunked into balanced ~400-token chunks with new `<doc>-p<page>-text-chunk-<n>` IDs, so text vector IDs do not correspond to parse-time segment IDs. Visual vectors carry the caption text and the original `image_path`.
4. `query.py` embeds the query, searches the chosen index, and makes one Sol generation call. In `mrag` mode any retrieved visual attaches its actual cropped image (not just the caption) to that call; in `text_only` mode a visual hit is impossible by construction and would raise.

`eval_runner.py` runs both modes over `eval/questions.jsonl` into `eval/results.csv`.

### The agent path (demo only)

Neither demo calls `query()`. It drives `scripts/agent.py`, which wraps `query.retrieve()` and the Azure boundary but leaves `query.query()` alone, so the evaluated code path and the demo path stay separable. One turn is:

1. `route_question()` asks Luna for `{route, search_query, confidence, reason}` as JSON. `datasheet` retrieves; `general` skips retrieval entirely. A malformed or failed router response falls back to retrieving with the raw message, because over-retrieving is recoverable and skipping retrieval is not.
2. `gather_evidence()` retrieves top-k, labels the hits `S1..Sn`, and compares the top cosine against `RELEVANCE_FLOOR`.
3. `answer_stream()` picks one of three prompts (grounded, ungrounded, general) and streams from Sol via `generate_stream()`.
4. `cited_labels()` parses `[S1]` markers out of the finished answer and `provenance()` classifies the turn as grounded, general, uncovered, or unsupported. `unsupported` means retrieval cleared the floor but the model cited nothing, which is the honest signal that an answer is not backed by the evidence shown.

The Streamlit UI is split three ways: `streamlit_app.py` orchestrates and holds session state, `app/components.py` turns agent output into markup, `app/styles.py` holds the entire stylesheet. Only `streamlit_app.py` imports from `scripts/`.

## The web stack

`api/` is a FastAPI service that wraps `scripts/agent.py` and streams agent stages over SSE. It is a transport layer only: it holds no retrieval or prompt logic, never imports the OpenAI SDK, and never calls `query.query()`. Endpoints are `/api/health`, `/api/meta` (corpus and model provenance), `/api/chat` (SSE), and `/api/image/{segment_id}` (serves a crop, resolved through a `segment_id -> path` map built once from `metadata.jsonl` and refused unless the path lands inside `data/parsed/`).

`web/` is Next.js 16 / React 19 / Tailwind v4. See `web/AGENTS.md` before editing it. UI components are vendored from the prompt-kit and MagicUI shadcn registries into `web/src/components/ui/`; that directory is third-party source with relaxed lint rules, edited only to fix real breakage. Everything else in `web/src` is authored for this app and fully linted.

The frontend has one route, `/`, the agent chat. The `plain` mode still exists end to end in the backend (`plain_stream` and `PLAIN_PROMPT` in `scripts/agent.py`, the `mode == "plain"` branches in `api/server.py`) and is reachable over `/api/chat`, but no UI currently drives it. `plain` sends the bare question with no retrieval and no framing, which is what a chat assistant answers when the user has not supplied the document. Keep `PLAIN_PROMPT` bare: adding instructions to it makes the comparison flattering rather than honest.

## Invariants that exist for a reason

- **The Azure boundary is `scripts/azure_client.py` and nothing else.** `embed_text()`, `generate()`, and `generate_stream()` are the only functions that touch the OpenAI SDK; deployment names come from `.env` via `scripts/config.py`, never hardcoded model strings. Swapping to local inference must stay a change to those function bodies. Do not import `openai` anywhere else. `generate_stream()` retries only the connection attempt, never mid-stream, since replaying a broken stream would duplicate emitted text.
- **Baseline fairness.** `text_only_index.faiss` is literally the leading `text_record_count` rows of the same normalized matrix added to `mrag_index.faiss`. `write_indexes()` asserts the text/visual split is clean and refuses to write otherwise. Never build the baseline through a separate path.
- **`retrieval_hit` and `answer_score` in `eval/results.csv` are hand-graded and stay distinct.** `eval_runner.py` writes those two columns blank on purpose. Re-running it truncates the CSV and destroys existing grades, so copy the file first if the grades still matter. Never merge the two columns or auto-fill them with a judge model.
- **`index/run_metadata.json`** records embedding model, all deployment names, vector store type, and vector counts per run. Keep it accurate; it is what answers "what exactly did you use".
- Caches are the expensive part: `index/embedding_cache.jsonl` is ~220 MB and keyed by `cache_key` plus a content hash, so edited text re-embeds and unchanged text does not. Never delete it casually.
- **Entrance animations in `app/styles.py` animate transform, never opacity.** A stalled animation timeline pins a running animation to its first frame, so a fade-in can leave evidence cards permanently invisible. Same reason there is no opacity transition on the cited/uncited swap: Streamlit reuses card DOM nodes between reruns, so that swap would animate and could strand a card mid-fade.
- Streamlit selectors here are version-sensitive. `st.container(border=True)` was `stVerticalBlockBorderWrapper` on 1.4x and is a directly-bordered `stVerticalBlock` on 1.6x, and `st.segmented_control` renders as `stButtonGroup`. The stylesheet matches both spellings. Verify against the live DOM before trusting a selector; `requirements.txt` pins no versions.

## Data layout notes

Only `.env` and the heavy re-derivable artifacts are gitignored now. The demo bundle
is committed so a fresh clone runs without re-parsing: source PDFs, both FAISS
indexes, `metadata.jsonl`, and per-document `segments.json` / `bboxes.json` /
`caption_cache.json`, plus the cropped visual images under `mineru/*/auto/images/`.
What stays ignored is `index/embedding_cache.jsonl` (~220 MB, only needed to
re-embed), `data/page_cache/` (regenerated on demand from the source PDFs), and
MinerU's debug output (`*_layout.pdf`, `*_span.pdf`, `*_origin.pdf`, `*_middle.json`,
`*_model.json`, `*_content_list*.json`, `*.md`) which nothing at runtime reads. `image_path` values in `segments.json` and `metadata.jsonl` are repo-root-relative and resolved against `PROJECT_ROOT`, so working directory does not matter for retrieval.

`paper/` is separate from the pipeline: `make_fig.py` renders the architecture figure and `build_paper.py` writes the IEEE paper sections into a `.docx`. Both contain absolute Windows paths to files outside the repo and will not run as-is elsewhere.
