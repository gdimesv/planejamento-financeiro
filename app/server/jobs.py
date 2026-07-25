from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Job:
    id: str
    kind: str
    cliente: str
    mes: str
    status: str = "running"  # running | done | error
    returncode: int | None = None
    output: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "cliente": self.cliente,
            "mes": self.mes,
            "status": self.status,
            "returncode": self.returncode,
            "output": self.output,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def start_scraper_job(kind: str, cliente: str, mes: str) -> Job:
    """Dispara um coletor numa thread e devolve o Job para acompanhamento.

    Os scrapers abrem um Chromium para login manual, entao rodam por minutos;
    a thread mantem o processo vivo enquanto o front faz polling em get_job().
    """
    job = Job(id=uuid.uuid4().hex[:12], kind=kind, cliente=cliente, mes=mes)
    with _lock:
        _jobs[job.id] = job

    def _run() -> None:
        from pipeline.orchestrator import run_scraper

        try:
            result = run_scraper(kind, cliente, mes)
            job.output = result.output
            job.returncode = result.returncode
            job.status = "done" if result.ok else "error"
        except Exception as exc:  # noqa: BLE001 - superficie de erro do subprocess
            job.output = f"{type(exc).__name__}: {exc}"
            job.status = "error"
        finally:
            job.finished_at = time.time()

    threading.Thread(target=_run, name=f"scraper-{kind}", daemon=True).start()
    return job


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)
