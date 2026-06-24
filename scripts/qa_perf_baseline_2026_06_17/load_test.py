#!/usr/bin/env python3
"""
End-to-end perf baseline for the live AI-Billing-Audit portal.

Drives the live VPS at https://ai-billing-audit.ashbi.ca with three load
shapes and records per-stage timings from outside the system:

  1) 1 encounter POSTed serially           -> time-to-first-result
  2) 10 encounters POSTed in parallel      -> p50, p95 time-to-all-done
  3) 50 encounters POSTed                  -> total wall clock

Per-stage breakdown captured from the public surface:
  - api_handler_ms    = HTTP latency of the POST /encounters/upload/submit
  - queue_wait_ms     = started_at  - submitted_at   (from /jobs/<id>)
  - runner_ms         = finished_at - started_at     (from /jobs/<id>)
  - end_to_end_ms     = finished_at - submitted_at   (sum of the two above)
  - poll_to_terminal  = wall clock from last POST to terminal status for all jobs

Notes on the pipeline shape (verified 2026-06-17):
  - The live /encounters/upload/submit -> queue pipeline does NOT call the
    LLM auditor. The runner is _default_runner() in job_queue.py, which
    calls synth_agent.generate(). There is no LLM inference stage in the
    upload path; the LLM auditor (run_audit in auditor.py) is invoked
    locally by scripts/eval_*.py, not by the live portal.
  - There is no DB write in the upload path. /jobs/<id> returns the
    in-memory Job state; the durable trail is logs/upload_jobs.jsonl
    (also no Postgres).
  - "time-to-first-finding" therefore is "time-to-first-done" today. The
    QA_PERF_BASELINE.md report documents this gap so the numbers can be
    compared against future runs that wire run_audit() into the queue.

Raw results land in run_*.json files alongside this script.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE_URL = os.environ.get("ABA_BASE_URL", "https://ai-billing-audit.ashbi.ca")
SUBMIT_PATH = "/encounters/upload/submit"
JOB_PATH_TMPL = "/encounters/upload/jobs/{job_id}"

POLL_INTERVAL_S = 0.05       # 50ms between status polls per job
POLL_DEADLINE_S = 120.0      # a single job gets 2min before we call it stuck


def make_paste_row(seq: int) -> dict:
    """Build a paste-form row that /encounters/upload/submit accepts.

    Uses the same shape the live form posts — we never set source/source_filename
    explicitly, /paste would, but /submit infers source='paste' from the missing
    fields. We use a 10-digit NPI, two CPT codes, a valid YYYY-MM-DD date, and
    a unique encounter_id per row.
    """
    eid = f"ENC-PERF-{seq:04d}-{uuid.uuid4().hex[:8]}"
    return {
        "encounter_id": eid,
        "patient_id": f"PAT-{seq:05d}",
        "NPI": f"1{seq:09d}"[-10:],
        "date_of_service": "2024-06-01",
        "CPT_codes": ["99213", "99214"],
        "source": "paste",
        "source_filename": "(perf-baseline)",
        "errors": [],
    }


def submit_one(seq: int, *, session: requests.Session) -> dict:
    """POST a single row to /encounters/upload/submit and return per-request record."""
    row = make_paste_row(seq)
    payload = json.dumps({"rows": [row]})
    t0 = time.monotonic()
    try:
        resp = session.post(
            f"{BASE_URL}{SUBMIT_PATH}",
            data={"payload": payload},
            timeout=30,
        )
    except requests.RequestException as exc:
        return {
            "seq": seq,
            "encounter_id": row["encounter_id"],
            "ok": False,
            "error": f"http_error: {exc}",
            "submit_latency_ms": (time.monotonic() - t0) * 1000.0,
        }
    submit_ms = (time.monotonic() - t0) * 1000.0
    if resp.status_code != 200:
        return {
            "seq": seq,
            "encounter_id": row["encounter_id"],
            "ok": False,
            "error": f"http_{resp.status_code}: {resp.text[:200]}",
            "submit_latency_ms": submit_ms,
        }
    try:
        body = resp.json()
    except ValueError as exc:
        return {
            "seq": seq,
            "encounter_id": row["encounter_id"],
            "ok": False,
            "error": f"json_error: {exc}",
            "submit_latency_ms": submit_ms,
        }
    jobs = body.get("jobs") or []
    rejected = body.get("rejected") or []
    if rejected:
        return {
            "seq": seq,
            "encounter_id": row["encounter_id"],
            "ok": False,
            "error": f"rejected_by_server: {rejected}",
            "submit_latency_ms": submit_ms,
        }
    if not jobs:
        return {
            "seq": seq,
            "encounter_id": row["encounter_id"],
            "ok": False,
            "error": "no_jobs_returned",
            "submit_latency_ms": submit_ms,
        }
    j = jobs[0]
    return {
        "seq": seq,
        "encounter_id": row["encounter_id"],
        "ok": True,
        "job_id": j.get("job_id"),
        "submit_latency_ms": submit_ms,
        "submit_responded_at": time.time(),
    }


def poll_job(job_id: str, *, session: requests.Session, deadline_s: float = POLL_DEADLINE_S) -> dict:
    """Poll /encounters/upload/jobs/<id> until terminal status. Return the final record."""
    url = f"{BASE_URL}{JOB_PATH_TMPL.format(job_id=job_id)}"
    t0 = time.monotonic()
    polls = 0
    while time.monotonic() - t0 < deadline_s:
        try:
            resp = session.get(url, timeout=10)
        except requests.RequestException:
            time.sleep(POLL_INTERVAL_S)
            continue
        polls += 1
        if resp.status_code == 404:
            # job not in memory (server restart) — call it done with the caveat
            return {
                "job_id": job_id,
                "ok": False,
                "error": "job_404_lost",
                "poll_count": polls,
                "poll_ms": (time.monotonic() - t0) * 1000.0,
            }
        if resp.status_code != 200:
            time.sleep(POLL_INTERVAL_S)
            continue
        job = resp.json()
        status = job.get("status")
        if status in ("done", "failed"):
            return {
                "job_id": job_id,
                "ok": status == "done",
                "status": status,
                "error": job.get("error", ""),
                "submitted_at": job.get("submitted_at"),
                "started_at": job.get("started_at"),
                "finished_at": job.get("finished_at"),
                "result": job.get("result") or {},
                "poll_count": polls,
                "poll_ms": (time.monotonic() - t0) * 1000.0,
            }
        time.sleep(POLL_INTERVAL_S)
    return {
        "job_id": job_id,
        "ok": False,
        "error": "poll_deadline_exceeded",
        "poll_count": polls,
        "poll_ms": (time.monotonic() - t0) * 1000.0,
    }


def per_request_record(submit: dict, job: dict) -> dict:
    """Compute per-stage timings for a single accepted job."""
    submitted = submit.get("submit_responded_at")
    sa = job.get("submitted_at")
    sta = job.get("started_at")
    fa = job.get("finished_at")
    queue_wait_ms = ((sta - sa) * 1000.0) if (sta and sa) else None
    runner_ms = ((fa - sta) * 1000.0) if (fa and sta) else None
    end_to_end_ms = ((fa - sa) * 1000.0) if (fa and sa) else None
    return {
        "seq": submit["seq"],
        "encounter_id": submit["encounter_id"],
        "job_id": submit["job_id"],
        "ok": job.get("ok", False),
        "status": job.get("status"),
        "error": job.get("error", ""),
        "submit_latency_ms": submit["submit_latency_ms"],
        "queue_wait_ms": queue_wait_ms,
        "runner_ms": runner_ms,
        "end_to_end_ms": end_to_end_ms,
        "poll_count": job.get("poll_count"),
        "poll_ms": job.get("poll_ms"),
        "result": job.get("result"),
    }


def percentile(values: list[float], p: float) -> float:
    """Plain percentile (linear interpolation, no numpy)."""
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] * (c - k) + s[c] * (k - f)


def summarize(records: list[dict]) -> dict:
    """Build the per-stage summary for a list of per-request records."""
    ok_records = [r for r in records if r.get("ok") and r.get("end_to_end_ms") is not None]
    end_to_ends = [r["end_to_end_ms"] for r in ok_records]
    queue_waits = [r["queue_wait_ms"] for r in ok_records if r["queue_wait_ms"] is not None]
    runners = [r["runner_ms"] for r in ok_records if r["runner_ms"] is not None]
    submits = [r["submit_latency_ms"] for r in records if r.get("submit_latency_ms") is not None]
    n = len(records)
    n_ok = len(ok_records)
    n_failed = n - n_ok
    summary = {
        "n": n,
        "n_ok": n_ok,
        "n_failed": n_failed,
        "submit_latency_ms": {
            "min": min(submits) if submits else None,
            "max": max(submits) if submits else None,
            "median": statistics.median(submits) if submits else None,
            "mean": statistics.fmean(submits) if submits else None,
        },
        "queue_wait_ms": {
            "min": min(queue_waits) if queue_waits else None,
            "max": max(queue_waits) if queue_waits else None,
            "median": statistics.median(queue_waits) if queue_waits else None,
            "mean": statistics.fmean(queue_waits) if queue_waits else None,
        },
        "runner_ms": {
            "min": min(runners) if runners else None,
            "max": max(runners) if runners else None,
            "median": statistics.median(runners) if runners else None,
            "mean": statistics.fmean(runners) if runners else None,
        },
        "end_to_end_ms": {
            "min": min(end_to_ends) if end_to_ends else None,
            "max": max(end_to_ends) if end_to_ends else None,
            "median": statistics.median(end_to_ends) if end_to_ends else None,
            "mean": statistics.fmean(end_to_ends) if end_to_ends else None,
            "p50": percentile(end_to_ends, 50) if end_to_ends else None,
            "p95": percentile(end_to_ends, 95) if end_to_ends else None,
            "p99": percentile(end_to_ends, 99) if end_to_ends else None,
        },
    }
    return summary


def run_shape(shape_name: str, n: int, *, parallel: bool, run_id: str, out_dir: Path) -> dict:
    """Run one load shape. Returns the run record (per-request + summary + wall clock)."""
    print(f"\n=== {shape_name}: n={n} parallel={parallel} run_id={run_id} ===", flush=True)
    session = requests.Session()
    started_wall = time.monotonic()

    submit_results: list[dict] = []
    if parallel:
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [pool.submit(submit_one, i, session=session) for i in range(1, n + 1)]
            for f in as_completed(futures):
                submit_results.append(f.result())
    else:
        for i in range(1, n + 1):
            submit_results.append(submit_one(i, session=session))

    submit_done_wall = time.monotonic()
    submit_window_ms = (submit_done_wall - started_wall) * 1000.0

    successful_submits = [r for r in submit_results if r.get("ok")]
    print(f"  submit phase: {len(successful_submits)}/{n} accepted in {submit_window_ms:.0f}ms", flush=True)
    if not successful_submits:
        return {
            "shape": shape_name,
            "n": n,
            "parallel": parallel,
            "run_id": run_id,
            "submit_window_ms": submit_window_ms,
            "records": submit_results,
            "summary": summarize([]),
            "wall_clock_ms": (time.monotonic() - started_wall) * 1000.0,
        }

    # Poll all jobs to terminal
    job_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(32, n)) as pool:
        futures = {r["job_id"]: pool.submit(poll_job, r["job_id"], session=session) for r in successful_submits}
        for jid, f in futures.items():
            try:
                job_results.append(f.result())
            except Exception as exc:
                job_results.append({"job_id": jid, "ok": False, "error": f"poll_exception: {exc}"})

    all_done_wall = time.monotonic()
    poll_window_ms = (all_done_wall - submit_done_wall) * 1000.0
    total_wall_ms = (all_done_wall - started_wall) * 1000.0

    # Map back to per-request records
    submit_by_id = {r["job_id"]: r for r in successful_submits}
    records: list[dict] = []
    for jr in job_results:
        sr = submit_by_id.get(jr["job_id"])
        if sr is None:
            # shouldn't happen, but keep the record for inspection
            records.append({"ok": jr.get("ok", False), "error": "submit_record_missing", "job_id": jr["job_id"]})
            continue
        records.append(per_request_record(sr, jr))

    summary = summarize(records)
    run_record = {
        "shape": shape_name,
        "n": n,
        "parallel": parallel,
        "run_id": run_id,
        "started_at_wall": started_wall,
        "submit_window_ms": submit_window_ms,
        "poll_window_ms": poll_window_ms,
        "wall_clock_ms": total_wall_ms,
        "summary": summary,
        "records": records,
    }

    out_path = out_dir / f"run_{shape_name}_{run_id}.json"
    out_path.write_text(json.dumps(run_record, indent=2, default=str))
    print(
        f"  total wall clock: {total_wall_ms:.0f}ms  "
        f"(submit_window={submit_window_ms:.0f}ms, poll_window={poll_window_ms:.0f}ms)  "
        f"p50={summary['end_to_end_ms']['p50']:.1f}ms  p95={summary['end_to_end_ms']['p95']:.1f}ms",
        flush=True,
    )
    print(f"  raw -> {out_path}", flush=True)
    return run_record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--shape",
        choices=["1", "10", "50", "all"],
        default="all",
    )
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d_%H%M%S"))
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else Path(__file__).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    shapes = []
    if args.shape in ("1", "all"):
        shapes.append(("serial_1", 1, False))
    if args.shape in ("10", "all"):
        shapes.append(("parallel_10", 10, True))
    if args.shape in ("50", "all"):
        shapes.append(("batch_50", 50, True))

    runs = []
    for shape_name, n, parallel in shapes:
        runs.append(run_shape(shape_name, n, parallel=parallel, run_id=args.run_id, out_dir=out_dir))

    print("\n=== aggregate across this invocation ===", flush=True)
    agg_path = out_dir / f"aggregate_{args.run_id}.json"
    agg_path.write_text(json.dumps({"run_id": args.run_id, "base_url": BASE_URL, "runs": runs}, indent=2, default=str))
    print(f"  aggregate -> {agg_path}", flush=True)

    for r in runs:
        s = r["summary"]
        print(
            f"  {r['shape']:>15}  n={r['n']:>3}  ok={s['n_ok']:>3}  "
            f"submit_p50={s['submit_latency_ms']['median']:>7.1f}ms  "
            f"queue_p50={s['queue_wait_ms']['median']:>7.1f}ms  "
            f"runner_p50={s['runner_ms']['median']:>7.1f}ms  "
            f"e2e_p50={s['end_to_end_ms']['p50']:>7.1f}ms  "
            f"e2e_p95={s['end_to_end_ms']['p95']:>7.1f}ms  "
            f"wall={r['wall_clock_ms']:>7.0f}ms",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
