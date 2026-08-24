from __future__ import annotations

import sys
from pathlib import Path

# Garante que os modulos do motor (core, ingest, main, pipeline) estejam no path,
# permitindo rodar `uvicorn server.app:app` a partir da raiz ou de app/.
APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import yaml
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from pipeline.gate import evaluate_gate
from pipeline.goals import (
    load_asset_map,
    load_ativos_mes,
    load_aporte_usado,
    load_objetivos,
    save_asset_map,
    save_aporte_usado,
    save_objetivos,
    save_planned_moves,
)
from pipeline.orchestrator import save_internacional_from_pdf
from pipeline.state import (
    MonthState,
    Step,
    StepStatus,
    client_dir,
    compute_month_state,
    month_input_dir,
)
from server.jobs import get_job, start_scraper_job

PROJECT_ROOT = APP_DIR.parent
CLIENTES_DIR = PROJECT_ROOT / "clientes"
VALID_SCRAPERS = {"xp", "suno_fiis", "suno_acoes"}

SERVER_DIR = Path(__file__).resolve().parent
STATIC_DIR = SERVER_DIR / "static"
TEMPLATES_DIR = SERVER_DIR / "templates"

COLLECT_GROUPS = [
    {"kind": "xp", "label": "XP (posição + extrato)", "step_ids": ["xp_posicao", "xp_extrato"]},
    {"kind": "suno_fiis", "label": "Carteira recomendada de FIIs (Suno)", "step_ids": ["suno_fiis"]},
    {"kind": "suno_acoes", "label": "Carteira recomendada de Ações (Suno)", "step_ids": ["suno_acoes"]},
]

app = FastAPI(title="Planejamento Financeiro")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


@app.post("/api/report/{cliente}/{mes}")
def api_report(cliente: str, mes: str, body: ReportBody) -> dict:
    from main import run as run_report

    state = compute_month_state(cliente, mes)
    gate = evaluate_gate(state)
    if not gate.ready:
        raise HTTPException(409, {"message": "Relatorio bloqueado", "blocking": gate.blocking})

    aporte = body.aporte
    if aporte is None:
        cfg_file = client_dir(cliente) / "objetivos.yaml"
        cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
        aporte = float(cfg.get("aporte_mensal_padrao", 0.0) or 0.0)

    out = run_report(cliente, mes, float(aporte))
    save_aporte_usado(cliente, mes, float(aporte))
    return {"ok": True, "path": str(out), "url": f"/report/{cliente}/{mes}"}


@app.get("/report/{cliente}/{mes}", response_class=HTMLResponse)
def serve_report(cliente: str, mes: str) -> FileResponse:
    html_path = client_dir(cliente) / "outputs" / mes / "relatorio.html"
    if not html_path.exists():
        raise HTTPException(404, "Relatorio ainda nao gerado para este mes.")
    return FileResponse(html_path, media_type="text/html")


@app.post("/report/{cliente}/{mes}/movimentos")
def report_movimentos(cliente: str, mes: str, movimentos: str = Form("")):
    from main import run as run_report

    save_planned_moves(cliente, mes, movimentos)
    output_file = client_dir(cliente) / "outputs" / mes / "relatorio.html"
    if output_file.exists():
        aporte = load_aporte_usado(cliente, mes)
        if aporte is None:
            aporte = _aporte_default(cliente)
        run_report(cliente, mes, aporte)
    return RedirectResponse(f"/report/{cliente}/{mes}", status_code=303)


# --- Helpers de listagem ---

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


# --- Helpers do wizard de setup ---

def _group_status(steps_by_id: dict[str, Step], step_ids: list[str]) -> str:
    relevant = [steps_by_id[sid] for sid in step_ids]
    if all(s.status == StepStatus.OK for s in relevant):
        return "ok"
    if any(s.required for s in relevant):
        return "pending"
    return "warn"


def _collect_groups(state: MonthState) -> list[dict]:
    steps_by_id = {s.id: s for s in state.steps}
    groups = []
    for g in COLLECT_GROUPS:
        relevant = [steps_by_id[sid] for sid in g["step_ids"]]
        groups.append(
            {
                "kind": g["kind"],
                "label": g["label"],
                "status": _group_status(steps_by_id, g["step_ids"]),
                "detail": "; ".join(s.detail for s in relevant if s.detail),
                "files": [f for s in relevant for f in s.files],
            }
        )
    return groups


def _aporte_default(cliente: str) -> float:
    cfg_file = client_dir(cliente) / "objetivos.yaml"
    if not cfg_file.exists():
        return 0.0
    cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    return float(cfg.get("aporte_mensal_padrao", 0.0) or 0.0)


def _panel_context(cliente: str, mes: str, oob: bool = False) -> dict:
    state = compute_month_state(cliente, mes)
    steps_by_id = {s.id: s for s in state.steps}
    return {
        "cliente": cliente,
        "mes": mes,
        "groups": _collect_groups(state),
        "internacional": steps_by_id["internacional"],
        "diag_steps": [steps_by_id["classificacao"], steps_by_id["mom"]],
        "gate": evaluate_gate(state),
        "aporte_default": _aporte_default(cliente),
        "oob": oob,
    }


# --- Helpers de objetivos ---

def _is_blank(value) -> bool:
    return value is None or value == "" or (isinstance(value, float) and value != value)


def _objetivos_text(data: dict) -> str:
    lines = []
    for o in data.get("objetivos", []):
        prazo = o.get("prazo_meses")
        valor_alvo = o.get("valor_alvo")
        lines.append(
            ",".join(
                [
                    str(o.get("id", "")),
                    str(o.get("descricao", "")),
                    str(o.get("tipo", "")),
                    "" if _is_blank(valor_alvo) else str(valor_alvo),
                    "" if _is_blank(prazo) else str(int(prazo)) if float(prazo).is_integer() else str(prazo),
                    str(o.get("prioridade", "")),
                ]
            )
        )
    return "\n".join(lines)


def _parse_objetivos_text(texto: str) -> list[dict]:
    objetivos = []
    for line in texto.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        parts += [""] * (6 - len(parts))
        oid, descricao, tipo, valor_alvo, prazo_meses, prioridade = parts[:6]
        if not oid:
            continue
        objetivos.append(
            {
                "id": oid,
                "descricao": descricao,
                "tipo": tipo or "valor_alvo",
                "valor_alvo": float(valor_alvo) if valor_alvo else 0.0,
                "prazo_meses": int(float(prazo_meses)) if prazo_meses else None,
                "prioridade": prioridade or "media",
            }
        )
    return objetivos


# --- Helpers de classificacao de ativos ---

def _classificacao_context(cliente: str, mes: str, somente_novos: bool, saved: bool = False) -> dict:
    objetivos = load_objetivos(cliente).get("objetivos", [])
    objetivo_ids = [o.get("id", "") for o in objetivos if o.get("id")]

    ativos_df = load_ativos_mes(cliente, mes)
    mapa_df = load_asset_map(cliente)

    if not ativos_df.empty:
        merged = ativos_df.merge(mapa_df, how="left", on="ativo")
    else:
        merged = mapa_df.copy()
        if "classe_macro" not in merged.columns:
            merged["classe_macro"] = ""
        if "valor_total" not in merged.columns:
            merged["valor_total"] = 0.0

    if "peso" not in merged.columns:
        merged["peso"] = 1.0
    merged["peso"] = merged["peso"].fillna(1.0)

    if somente_novos:
        merged = merged[merged["objetivo_id"].isna() | (merged["objetivo_id"].astype(str).str.strip() == "")]

    return {
        "cliente": cliente,
        "mes": mes,
        "objetivo_ids": objetivo_ids,
        "rows": merged.to_dict(orient="records"),
        "somente_novos": somente_novos,
        "saved": saved,
    }


# --- Paginas ---

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    clientes = [{"id": c, "meses": _list_meses(c)} for c in _list_clientes()]
    return templates.TemplateResponse("index.html", {"request": request, "clientes": clientes})


@app.get("/setup/{cliente}/{mes}", response_class=HTMLResponse)
def setup_page(request: Request, cliente: str, mes: str):
    return templates.TemplateResponse(
        "setup.html", {"request": request, **_panel_context(cliente, mes)}
    )


@app.post("/setup/{cliente}/{mes}/collect/{kind}", response_class=HTMLResponse)
def setup_collect(request: Request, cliente: str, mes: str, kind: str):
    if kind not in VALID_SCRAPERS:
        raise HTTPException(400, f"Coletor invalido: {kind}")
    job = start_scraper_job(kind, cliente, mes)
    label = next((g["label"] for g in COLLECT_GROUPS if g["kind"] == kind), kind)
    return templates.TemplateResponse(
        "_job_banner.html",
        {"request": request, "cliente": cliente, "mes": mes, "job": job.as_dict(), "label": label},
    )


@app.get("/setup/{cliente}/{mes}/job/{job_id}", response_class=HTMLResponse)
def setup_job_status(cliente: str, mes: str, job_id: str) -> HTMLResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job nao encontrado")
    label = next((g["label"] for g in COLLECT_GROUPS if g["kind"] == job.kind), job.kind)
    banner = templates.get_template("_job_banner.html").render(
        cliente=cliente, mes=mes, job=job.as_dict(), label=label
    )
    if job.status == "running":
        return HTMLResponse(banner)
    panel = templates.get_template("_panel.html").render(**_panel_context(cliente, mes, oob=True))
    return HTMLResponse(banner + panel)


@app.post("/setup/{cliente}/{mes}/internacional", response_class=HTMLResponse)
async def setup_internacional(
    request: Request, cliente: str, mes: str, arquivo: UploadFile = File(...), cotacao: float = Form(...)
):
    conteudo = await arquivo.read()
    erro = None
    nome = (arquivo.filename or "").lower()
    if not nome.endswith(".pdf"):
        erro = "Envie o extrato em PDF da XP International (Apex)."
    elif cotacao <= 0:
        erro = "Informe a cotação USD/BRL do dia (maior que zero)."
    else:
        try:
            resumo = save_internacional_from_pdf(cliente, mes, conteudo, cotacao)
        except Exception:
            resumo = {"posicoes": 0, "dividendos": 0}
        if resumo["posicoes"] == 0:
            erro = (
                "Não encontrei posições no PDF. Confira se é o extrato mensal completo "
                "da XP International (não um resumo/print parcial)."
            )

    return templates.TemplateResponse(
        "_panel.html",
        {"request": request, **_panel_context(cliente, mes), "internacional_error": erro},
    )


@app.post("/setup/{cliente}/{mes}/generate-report", response_class=HTMLResponse)
def setup_generate_report(request: Request, cliente: str, mes: str, aporte: float = Form(...)):
    from main import run as run_report

    state = compute_month_state(cliente, mes)
    gate = evaluate_gate(state)
    if not gate.ready:
        return templates.TemplateResponse(
            "_report_result.html", {"request": request, "ok": False, "reasons": gate.blocking}
        )
    run_report(cliente, mes, aporte)
    save_aporte_usado(cliente, mes, aporte)
    return templates.TemplateResponse(
        "_report_result.html", {"request": request, "ok": True, "cliente": cliente, "mes": mes}
    )


@app.get("/objetivos/{cliente}", response_class=HTMLResponse)
def objetivos_page(request: Request, cliente: str):
    data = load_objetivos(cliente)
    return templates.TemplateResponse(
        "objetivos.html",
        {
            "request": request,
            "cliente": cliente,
            "nome": data.get("cliente", {}).get("nome", cliente.title()),
            "aporte_mensal_padrao": float(data.get("aporte_mensal_padrao", 0.0) or 0.0),
            "objetivos_text": _objetivos_text(data),
            "saved": False,
        },
    )


@app.post("/objetivos/{cliente}", response_class=HTMLResponse)
def objetivos_save(
    request: Request,
    cliente: str,
    nome: str = Form(...),
    aporte_mensal_padrao: float = Form(0.0),
    objetivos_text: str = Form(""),
):
    payload = {
        "cliente": {"id": cliente, "nome": nome},
        "aporte_mensal_padrao": float(aporte_mensal_padrao),
        "objetivos": _parse_objetivos_text(objetivos_text),
    }
    save_objetivos(cliente, payload)
    return templates.TemplateResponse(
        "objetivos.html",
        {
            "request": request,
            "cliente": cliente,
            "nome": nome,
            "aporte_mensal_padrao": aporte_mensal_padrao,
            "objetivos_text": objetivos_text,
            "saved": True,
        },
    )


@app.get("/classificacao/{cliente}/{mes}", response_class=HTMLResponse)
def classificacao_page(request: Request, cliente: str, mes: str, somente_novos: bool = True):
    return templates.TemplateResponse(
        "classificacao.html", {"request": request, **_classificacao_context(cliente, mes, somente_novos)}
    )


@app.post("/classificacao/{cliente}/{mes}", response_class=HTMLResponse)
def classificacao_save(
    request: Request,
    cliente: str,
    mes: str,
    ativo: list[str] = Form(default=[]),
    objetivo_id: list[str] = Form(default=[]),
    peso: list[str] = Form(default=[]),
    somente_novos: bool = Form(False),
):
    edited_rows = [{"ativo": a, "objetivo_id": o, "peso": p} for a, o, p in zip(ativo, objetivo_id, peso)]
    if somente_novos:
        mapa_df = load_asset_map(cliente)
        if not mapa_df.empty:
            edited_assets = {r["ativo"] for r in edited_rows}
            existing = mapa_df[~mapa_df["ativo"].astype(str).isin(edited_assets)]
            edited_rows = existing.to_dict(orient="records") + edited_rows
    save_asset_map(cliente, edited_rows)
    return templates.TemplateResponse(
        "classificacao.html",
        {"request": request, **_classificacao_context(cliente, mes, somente_novos, saved=True)},
    )
