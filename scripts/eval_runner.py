"""Run the hand-scored M-RAG versus text-only evaluation matrix."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, cast

from scripts.query import QueryMode, query


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS_PATH = PROJECT_ROOT / "eval" / "questions.jsonl"
DEFAULT_RESULTS_PATH = PROJECT_ROOT / "eval" / "results.csv"
MODES: tuple[QueryMode, ...] = ("mrag", "text_only")
RESULT_FIELDS: tuple[str, ...] = (
    "question",
    "mode",
    "doc",
    "requires_visual",
    "retrieved_segment_ids",
    "generated_answer",
    "model_used",
    "retrieval_hit",
    "answer_score",
)


class EvaluationError(RuntimeError):
    """Raised when evaluation inputs or query outputs are invalid."""


@dataclass(frozen=True)
class EvaluationQuestion:
    question: str
    doc: str
    ground_truth_answer: str
    requires_visual: bool


@dataclass(frozen=True)
class EvaluationSummary:
    total_questions: int
    successful_by_mode: dict[QueryMode, int]
    failed_by_mode: dict[QueryMode, int]

    @property
    def total_failures(self) -> int:
        return sum(self.failed_by_mode.values())


def _required_string(payload: dict[str, Any], field: str, location: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{location} has no non-empty {field!r} field.")
    return value.strip()


def load_questions(path: Path = DEFAULT_QUESTIONS_PATH) -> list[EvaluationQuestion]:
    """Read and validate the manual evaluation question set."""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise EvaluationError(f"Evaluation questions file not found: {path}")

    questions: list[EvaluationQuestion] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise EvaluationError(f"Could not read evaluation questions {path}: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        location = f"{path}:{line_number}"
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationError(f"Invalid JSON at {location}: {exc}") from exc
        if not isinstance(payload, dict):
            raise EvaluationError(f"Question at {location} is not an object.")

        requires_visual = payload.get("requires_visual")
        if not isinstance(requires_visual, bool):
            raise EvaluationError(
                f"{location} has a non-boolean 'requires_visual' field."
            )
        questions.append(
            EvaluationQuestion(
                question=_required_string(payload, "question", location),
                doc=_required_string(payload, "doc", location),
                ground_truth_answer=_required_string(
                    payload,
                    "ground_truth_answer",
                    location,
                ),
                requires_visual=requires_visual,
            )
        )

    if not questions:
        raise EvaluationError(f"Evaluation questions file is empty: {path}")
    return questions


def _result_values(result: dict[str, Any]) -> tuple[str, str, str]:
    segment_ids = result.get("retrieved_segment_ids")
    answer = result.get("answer")
    deployment = result.get("deployment")
    if (
        not isinstance(segment_ids, list)
        or not all(isinstance(segment_id, str) for segment_id in segment_ids)
        or not isinstance(answer, str)
        or not answer.strip()
        or not isinstance(deployment, str)
        or not deployment.strip()
    ):
        raise EvaluationError("query() returned an invalid evaluation result.")
    return json.dumps(segment_ids, ensure_ascii=False), answer, deployment


def _base_row(question: EvaluationQuestion, mode: QueryMode) -> dict[str, str]:
    return {
        "question": question.question,
        "mode": mode,
        "doc": question.doc,
        "requires_visual": "true" if question.requires_visual else "false",
        "retrieved_segment_ids": "[]",
        "generated_answer": "",
        "model_used": "",
        # These fields are intentionally never populated automatically. They
        # remain independent manual judgments in the final evaluation table.
        "retrieval_hit": "",
        "answer_score": "",
    }


def run_evaluation(
    questions_path: Path = DEFAULT_QUESTIONS_PATH,
    results_path: Path = DEFAULT_RESULTS_PATH,
    k: int = 5,
) -> EvaluationSummary:
    """Run every question in both modes and write the unscored CSV rows."""
    if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
        raise ValueError("k must be a positive integer")

    questions = load_questions(questions_path)
    results_path = results_path.expanduser().resolve()
    results_path.parent.mkdir(parents=True, exist_ok=True)
    successful: dict[QueryMode, int] = {mode: 0 for mode in MODES}
    failed: dict[QueryMode, int] = {mode: 0 for mode in MODES}
    total_runs = len(questions) * len(MODES)
    run_number = 0

    try:
        results_file = results_path.open("w", encoding="utf-8", newline="")
    except OSError as exc:
        raise EvaluationError(f"Could not open evaluation results {results_path}: {exc}") from exc

    with results_file:
        writer = csv.DictWriter(results_file, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        results_file.flush()

        for question_number, evaluation_question in enumerate(questions, start=1):
            for mode in MODES:
                run_number += 1
                row = _base_row(evaluation_question, mode)
                print(
                    f"[{run_number}/{total_runs}] Question {question_number} — {mode}",
                    flush=True,
                )
                try:
                    result = query(evaluation_question.question, mode, k=k)
                    retrieved_ids, answer, deployment = _result_values(result)
                    row["retrieved_segment_ids"] = retrieved_ids
                    row["generated_answer"] = answer
                    row["model_used"] = deployment
                    successful[mode] += 1
                    print("  OK", flush=True)
                except Exception as exc:
                    # One Azure or retrieval failure must not hide the status of
                    # the remaining question/mode pairs. KeyboardInterrupt and
                    # SystemExit still propagate because they are BaseException.
                    failed[mode] += 1
                    print(
                        f"  FAILED: {type(exc).__name__}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )

                writer.writerow(row)
                results_file.flush()

    return EvaluationSummary(
        total_questions=len(questions),
        successful_by_mode=successful,
        failed_by_mode=failed,
    )


def print_summary(summary: EvaluationSummary, results_path: Path) -> None:
    print("\nEvaluation summary:")
    for mode in MODES:
        successful = summary.successful_by_mode[mode]
        failed = summary.failed_by_mode[mode]
        print(
            f"  {mode}: {successful}/{summary.total_questions} successful "
            f"({failed} failed)"
        )
    print(f"Results: {results_path.expanduser().resolve()}")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run every evaluation question through M-RAG and the text-only "
            "baseline, leaving retrieval and answer scoring blank for humans."
        )
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=DEFAULT_QUESTIONS_PATH,
        help="input questions JSONL (default: eval/questions.jsonl)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help="output CSV (default: eval/results.csv)",
    )
    parser.add_argument("-k", type=int, default=5, help="retrieval depth (default: 5)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        summary = run_evaluation(
            questions_path=args.questions,
            results_path=args.output,
            k=args.k,
        )
    except (EvaluationError, OSError, ValueError) as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print_summary(summary, cast(Path, args.output))
    return 1 if summary.total_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
