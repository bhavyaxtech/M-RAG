"""Bounded, resumable live-API spot checks; never assigns accuracy grades."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output/stm32/live_validation"
BASE_URL = "http://127.0.0.1:8012"


def run_case(case):
    path = OUTPUT / f"{case['id']}-{case['mode']}.json"
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if any(event["type"] == "done" for event in saved["events"]):
            return f"Cached: {path.name}"
        raise RuntimeError(f"Inspect prior failed attempt before retrying: {path}")
    payload = {
        "message": case["question"], "mode": case["mode"],
        "doc": case.get("doc", "stm32-ds5319"),
        "scope": case.get("scope", "collection"), "k": 8,
    }
    report = {
        "case": case, "request": payload,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "events": [], "answer_score": None,
        "review_status": "ungraded_live_response",
    }
    started = time.monotonic()
    try:
        request = Request(BASE_URL + "/api/chat", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=180) as response:
            for line in response:
                if line.startswith(b"data:"):
                    report["events"].append(json.loads(line[5:]))
    except Exception as exc:
        report["events"].append({"type": "error", "message": str(exc)})
    report["seconds"] = round(time.monotonic() - started, 2)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    completed = any(event["type"] == "done" for event in report["events"])
    errors = [event for event in report["events"] if event["type"] == "error"]
    return f"{path.name}: completed={completed}, errors={errors}, {report['seconds']}s"


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    candidates = [json.loads(line) for line in
                  (ROOT / "eval/stm32/questions.candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    candidates.append({
        "id": "lqfp48-usart1", "doc": "stm32-ds5319", "scope": "document",
        "question": "For STM32F103C8 in the LQFP48 package, what physical pin numbers carry PA9 and PA10, and which default USART1 signals do they provide? Cite the package-specific source.",
    })
    cases = [dict(case, mode=mode) for case in candidates for mode in ("mrag", "text_only")]
    cases.extend([
        {"id": "missing-page", "question": "Explain the diagram on page 9999.",
         "doc": "stm32-ds5319", "scope": "document", "mode": "mrag"},
        {"id": "wrong-component", "question": "Which pin is TXD0 on the ESP32-WROOM-32E?",
         "doc": "stm32-ds5319", "scope": "document", "mode": "mrag"},
    ])
    with ThreadPoolExecutor(max_workers=2) as executor:
        for result in executor.map(run_case, cases):
            print(result, flush=True)


if __name__ == "__main__":
    main()
