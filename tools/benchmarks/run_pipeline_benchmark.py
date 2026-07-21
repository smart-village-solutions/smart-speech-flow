#!/usr/bin/env python3
"""Run repeatable text or audio pipeline benchmarks against the API gateway.

Run each model in ``primary_only`` or ``candidate_only`` mode. Do not use this
tool's end-to-end results from ``shadow_compare`` as a model comparison.
"""

import argparse
import hashlib
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURES = ROOT / "tests/fixtures/audio/translation/duration_set"


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[round((len(ordered) - 1) * fraction)]


def summary(values: list[float], errors: int, timeouts: int) -> dict[str, float | int]:
    attempts = max(1, len(values) + errors + timeouts)
    return {
        "count": len(values), "mean_ms": round(statistics.mean(values), 2) if values else 0,
        "median_ms": round(statistics.median(values), 2) if values else 0,
        "p95_ms": round(percentile(values, 0.95), 2), "min_ms": round(min(values), 2) if values else 0,
        "max_ms": round(max(values), 2) if values else 0, "error_rate": errors / attempts,
        "timeout_rate": timeouts / attempts,
    }


def load_cases(fixtures: Path) -> list[dict[str, Any]]:
    source = json.loads((fixtures / "transcripts.json").read_text(encoding="utf-8"))
    cases = []
    for item in source["fixtures"]:
        path = fixtures / item["file"]
        source_lang = item["language"]
        cases.append({**item, "path": path, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "target_lang": "en" if source_lang == "de" else "de"})
    return cases


def create_session(base_url: str, target_lang: str) -> str:
    response = requests.post(f"{base_url}/api/session/create", params={"customer_language": target_lang}, timeout=10)
    response.raise_for_status()
    return response.json()["session_id"]


def request_case(base_url: str, session_id: str, case: dict[str, Any], pipeline: str) -> dict[str, Any]:
    url = f"{base_url}/api/session/{session_id}/message"
    client_type = "admin" if case["language"] == "de" else "customer"
    started = time.perf_counter()
    if pipeline == "text":
        response = requests.post(url, json={"text": case["text"], "source_lang": case["language"],
                    "target_lang": case["target_lang"], "client_type": client_type}, timeout=120)
    else:
        with case["path"].open("rb") as audio:
            response = requests.post(url, data={"source_lang": case["language"], "target_lang": case["target_lang"], "client_type": client_type},
                files={"file": (case["file"], audio, "audio/wav")}, timeout=180)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    data = response.json()
    steps = {step["name"]: step for step in data.get("pipeline_metadata", {}).get("steps", [])}
    refinement = steps.get("refinement", {})
    comparison = refinement.get("refinement_comparison", {})
    return {"id": case["file"], "duration_ms": elapsed_ms, "pipeline_total_ms": data.get("processing_time_ms"),
            "refinement_ms": refinement.get("duration_ms"), "refinement_status": comparison.get("primary_status"),
            "metadata": data.get("pipeline_metadata")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pipeline", choices=("text", "audio"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    cases = load_cases(args.fixtures)
    if args.limit:
        cases = cases[:args.limit]
    session_language = lambda case: case["target_lang"] if case["language"] == "de" else case["language"]
    sessions = {language: create_session(args.base_url.rstrip("/"), language) for language in {session_language(case) for case in cases}}
    for _ in range(args.warmups):
        case = cases[0]
        request_case(args.base_url.rstrip("/"), sessions[session_language(case)], case, args.pipeline)
    results, errors, timeouts = [], 0, 0
    for _ in range(args.runs):
        for case in cases:
            try:
                results.append(request_case(args.base_url.rstrip("/"), sessions[session_language(case)], case, args.pipeline))
            except requests.Timeout:
                timeouts += 1
            except requests.RequestException:
                errors += 1
    totals = [item["duration_ms"] for item in results]
    refinements = [item["refinement_ms"] for item in results if item["refinement_ms"] is not None]
    refinement_errors = sum(item.get("refinement_status") == "error" for item in results)
    # Refinement metadata currently reports only success/error, not a timeout status.
    refinement_timeouts = 0
    manifest_cases = [{key: value for key, value in case.items() if key != "path"} for case in cases]
    report = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "pipeline": args.pipeline,
              "warmups": args.warmups, "runs": args.runs, "cases": manifest_cases, "results": results,
              "summary": {"end_to_end": summary(totals, errors, timeouts), "refinement": summary(refinements, refinement_errors, refinement_timeouts)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
