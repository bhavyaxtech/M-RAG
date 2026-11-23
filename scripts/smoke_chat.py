"""Exercise the real chat API and save outputs for manual prompt review.

This uses the server's configured models (billable if hosted). It does not
grade factual accuracy or overwrite the original retrieval evaluation.
"""

import argparse
import json
from pathlib import Path
import time
import urllib.request


CASES = [
    ("pin_explanation", "esp32-wroom-32e-32ue",
     "Which module pin is TXD0? Explain the difference between the module pin number and GPIO number in simple terms."),
    ("concept", "lm317",
     "What does line regulation mean? Explain it simply, not just the datasheet numbers."),
    ("unsupported", "esp32-wroom-32e-32ue",
     "What is the maximum Wi-Fi range in metres guaranteed by this datasheet?"),
    ("wrong_document", "lm317", "Which pin is TXD0 on the ESP32?"),
    ("missing_page", "esp32-wroom-32e-32ue", "Explain the diagram on page 9999."),
]


def request_answer(base_url, name, document, question, history=None):
    payload = {"message": question, "doc": document, "mode": "mrag", "history": history or []}
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    events = []
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            for line in response:
                if line.startswith(b"data:"):
                    events.append(json.loads(line[5:]))
    except Exception as exc:
        events.append({"type": "error", "message": str(exc)})
    return {
        "name": name, "request": payload, "seconds": round(time.monotonic() - started, 2),
        "events": events,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def record(result):
        results.append(result)
        # Save each completed case so a later failure does not lose the run.
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        done = next((event for event in result["events"] if event["type"] == "done"), None)
        print(json.dumps({"name": result["name"], "seconds": result["seconds"], "done": done,
                          "errors": [event for event in result["events"] if event["type"] == "error"]}), flush=True)

    for name, document, question in CASES:
        record(request_answer(args.base_url, name, document, question))
        if name == "pin_explanation":
            done = next((event for event in results[-1]["events"] if event["type"] == "done"), None)
            if done:
                history = [{"role": "user", "content": question}, {"role": "assistant", "content": done["answer"]}]
                record(request_answer(args.base_url, "followup", document,
                                      "I still don't get the difference. Explain it without jargon.", history))

    failed = any(not any(event["type"] == "done" for event in result["events"]) or
                 any(event["type"] == "error" for event in result["events"]) for result in results)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
