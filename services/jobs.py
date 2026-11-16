"""
Background test jobs.

A test with 20 attempts and a long timeout can take a while. The UI starts a
job, then polls it; the job reports how many attempts have finished, so the
progress bar reflects real completed DNS queries rather than an animation.
"""
from __future__ import annotations

import threading
import time
import uuid

from database import connect_standalone
from database.history import save_test
from dns_engine import DNSQueryEngine
from dns_engine.validation import DNSTestRequest

from .runner import run_dns_test

JOB_TTL_S = 15 * 60
MAX_RUNNING_JOBS = 4


class TooManyJobsError(RuntimeError):
    pass


class JobManager:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _cleanup(self):
        now = time.time()
        for jid in [j for j, v in self._jobs.items() if now - v["created"] > JOB_TTL_S and v["state"] != "running"]:
            self._jobs.pop(jid, None)

    def start(self, req: DNSTestRequest, engine: DNSQueryEngine, db_path: str, save: bool = True) -> str:
        with self._lock:
            self._cleanup()
            running = sum(1 for j in self._jobs.values() if j["state"] == "running")
            if running >= MAX_RUNNING_JOBS:
                raise TooManyJobsError("Too many tests are running. Please wait for one to finish.")
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {
                "id": job_id, "state": "running", "created": time.time(),
                "total": req.attempts * len(req.resolvers), "completed": 0,
                "latest": [], "result": None, "error": None,
                "domain": req.domain, "record_type": req.record_type,
            }

        def on_attempt(attempt: dict):
            with self._lock:
                job = self._jobs.get(job_id)
                if job:
                    job["completed"] += 1
                    job["latest"].append({k: attempt[k] for k in
                                          ("resolver_key", "attempt", "category", "latency_ms")})

        def work():
            try:
                result = run_dns_test(req, engine, on_attempt)
                if save:
                    conn = connect_standalone(db_path)
                    try:
                        result["id"] = save_test(conn, result)
                    finally:
                        conn.close()
                with self._lock:
                    self._jobs[job_id].update(state="done", result=result)
            except Exception:  # never leak internals to the client
                with self._lock:
                    self._jobs[job_id].update(state="error", error="The test could not be completed.")

        threading.Thread(target=work, name=f"dnsguard-job-{job_id[:8]}", daemon=True).start()
        return job_id

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {
                "id": job["id"], "state": job["state"], "total": job["total"], "completed": job["completed"],
                "progress": round(job["completed"] / job["total"] * 100, 1) if job["total"] else 100.0,
                "latest": list(job["latest"][-40:]), "domain": job["domain"], "record_type": job["record_type"],
                "result": job["result"] if job["state"] == "done" else None,
                "error": job["error"],
            }
