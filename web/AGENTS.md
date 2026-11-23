# Working in `web/`

This is Next.js 16 with React 19.2 and Tailwind v4. It has breaking changes against
what you likely remember. Read the relevant guide in `node_modules/next/dist/docs/`
(resolved from this file's directory) before writing any code, and heed deprecation
notices. `node_modules/next/dist/docs/01-app/02-guides/upgrading/version-16.md` is the
breaking-change list.

The ones that bite in this app:

- Turbopack is the default bundler for both `dev` and `build`.
- Async Request APIs are enforced: `params` and `searchParams` are Promises and the
  synchronous compatibility shim from 15 is gone.
- `middleware` is renamed to `proxy`.

## What this app is

The judge-facing frontend for the M-RAG demo. It is a pure client of the FastAPI
service in `../api`, which streams agent stages over SSE. This app never talks to
Azure or FAISS itself, and holds no retrieval logic.

UI components come from [prompt-kit](https://prompt-kit.com) (chat primitives) and
[MagicUI](https://magicui.design) (motion), both installed as shadcn registry
components into `src/components/ui/`. They are vendored source, so edit them directly
rather than wrapping them in another abstraction layer.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
