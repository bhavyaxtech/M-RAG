"use client"

import { AlertTriangle } from "lucide-react"

import { API_BASE } from "@/lib/api"

/**
 * A silent failure here reads as an empty page during a live demo, so an
 * unreachable service says so explicitly and names the command that fixes it.
 */
export function ApiBanner({ show }: { show: boolean }) {
  if (!show) return null

  return (
    <div className="mb-4 flex items-start gap-2.5 rounded-xl bg-neutral-200 px-3.5 py-2.5 text-[13px] text-neutral-800">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-neutral-500" />
      <div>
        <p className="font-semibold">
          The agent service is not reachable at {API_BASE}.
        </p>
        <p className="mt-0.5 text-neutral-600">
          Start it from the repo root with{" "}
          <code className="rounded bg-neutral-300 px-1 py-0.5 font-mono text-[12px]">
            .venv/Scripts/python.exe -m uvicorn api.server:app --port 8000
          </code>
        </p>
      </div>
    </div>
  )
}
