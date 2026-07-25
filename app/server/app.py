from __future__ import annotations

import sys
from pathlib import Path

# Garante que os modulos do motor (core, ingest, main, pipeline) estejam no path,
# permitindo rodar `uvicorn server.app:app` a partir da raiz ou de app/.
APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from pipeline.gate import evaluate_gate
from pipeline.orchestrator import save_internacional
from pipeline.state import (
    MonthState,
    client_dir,
    compute_month_state,
    month_input_dir,
)
from server.jobs import get_job, start_scraper_job

PROJECT_ROOT = APP_DIR.parent
CLIENTES_DIR = PROJECT_ROOT / "clientes"
VALID_SCRAPERS = {"xp", "suno_fiis", "suno_acoes"}

app = FastAPI(title="Planejamento Financeiro")


# --- Serializacao ---

def _state_payload(state: MonthState) -> dict:
    gate = evaluate_gate(state)
    return {
        "cliente": state.cliente_id,
        "mes": state.mes,
        "steps": [
            {
                "id": s.id,
                "label": s.label,
                "status": s.status.value,
                "required": s.required,
                "detail": s.detail,
                "files": s.files,
                "updated_at": s.updated_at,
            }
            for s in state.steps
        ],
        "gate": {"ready": gate.ready, "blocking": gate.blocking, "warnings": gate.warnings},
    }


# --- Modelos de entrada ---

class InternacionalRow(BaseModel):
    classe: str = ""
    ativo: str
    valor: float | str = ""


class InternacionalBody(BaseModel):
    rows: list[InternacionalRow]


class ReportBody(BaseModel):
    aporte: float | None = None


# --- API ---

@app.get("/api/status/{cliente}/{mes}")
def api_status(cliente: str, mes: str) -> dict:
    return _state_payload(compute_month_state(cliente, mes))


@app.post("/api/run/{kind}/{cliente}/{mes}")
def api_run(kind: str, cliente: str, mes: str) -> dict:
    if kind not in VALID_SCRAPERS:
        raise HTTPException(400, f"Coletor invalido: {kind}")
    job = start_scraper_job(kind, cliente, mes)
    return {"job_id": job.id, "status": job.status}


@app.get("/api/job/{job_id}")
def api_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job nao encontrado")
    return job.as_dict()


@app.post("/api/internacional/{cliente}/{mes}")
def api_internacional(cliente: str, mes: str, body: InternacionalBody) -> dict:
    save_internacional(cliente, mes, [row.model_dump() for row in body.rows])
    return _state_payload(compute_month_state(cliente, mes))


@app.post("/api/report/{cliente}/{mes}")
def api_report(cliente: str, mes: str, body: ReportBody) -> dict:
    from main import run as run_report

    state = compute_month_state(cliente, mes)
    gate = evaluate_gate(state)
    if not gate.ready:
        raise HTTPException(409, {"message": "Relatorio bloqueado", "blocking": gate.blocking})

    import yaml

    aporte = body.aporte
    if aporte is None:
        cfg_file = client_dir(cliente) / "objetivos.yaml"
        cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
        aporte = float(cfg.get("aporte_mensal_padrao", 0.0) or 0.0)

    out = run_report(cliente, mes, float(aporte))
    return {"ok": True, "path": str(out), "url": f"/report/{cliente}/{mes}"}


@app.get("/report/{cliente}/{mes}", response_class=HTMLResponse)
def serve_report(cliente: str, mes: str) -> FileResponse:
    html_path = client_dir(cliente) / "outputs" / mes / "relatorio.html"
    if not html_path.exists():
        raise HTTPException(404, "Relatorio ainda nao gerado para este mes.")
    return FileResponse(html_path, media_type="text/html")


# --- Indice provisorio (o wizard rico vem na Fase 3) ---

def _list_clientes() -> list[str]:
    if not CLIENTES_DIR.exists():
        return []
    return sorted(p.name for p in CLIENTES_DIR.iterdir() if p.is_dir())


def _list_meses(cliente: str) -> list[str]:
    base = CLIENTES_DIR / cliente / "inputs"
    if not base.exists():
        return []
    return sorted(
        (p.name for p in base.iterdir() if p.is_dir() and p.name != "_templates"),
        reverse=True,
    )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    linhas = []
    for cliente in _list_clientes():
        meses = _list_meses(cliente)
        itens = "".join(
            f'<li><a href="/api/status/{cliente}/{mes}">{mes}</a> '
            f'&middot; <a href="/report/{cliente}/{mes}">relatorio</a></li>'
            for mes in meses
        )
        linhas.append(f"<h2>{cliente}</h2><ul>{itens or '<li>sem meses</li>'}</ul>")
    corpo = "".join(linhas) or "<p>Nenhum cliente encontrado.</p>"
    return f"<!doctype html><meta charset=utf-8><title>Planejamento Financeiro</title>{corpo}"
