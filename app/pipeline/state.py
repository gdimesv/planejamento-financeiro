from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import pandas as pd

from core.classification import classify_positions
from core.goals import find_unmapped_assets
from ingest.loader import load_month_inputs, month_previous
from ingest.normalizer import normalize_position


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = PROJECT_ROOT / "data" / "mapping" / "fundos_rules.yaml"


class StepStatus(str, Enum):
    OK = "ok"
    PENDING = "pending"
    WARN = "warn"


@dataclass
class Step:
    id: str
    label: str
    status: StepStatus
    required: bool
    detail: str = ""
    files: list[str] = field(default_factory=list)
    updated_at: str | None = None


@dataclass
class MonthState:
    cliente_id: str
    mes: str
    steps: list[Step]

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)


# --- Deteccao de arquivos (espelha os predicados de ingest/loader.py) ---

_INT_TOKENS = ("_int", "internacional", "exterior", "usa")


def _is_extrato(name: str) -> bool:
    return "extrato" in name


def _is_m0(name: str) -> bool:
    return "m0" in name


def _is_internacional(name: str) -> bool:
    return _is_m0(name) and any(token in name for token in _INT_TOKENS)


def _is_xp_posicao(name: str) -> bool:
    return _is_m0(name) and not _is_internacional(name) and not _is_extrato(name)


def _is_fii_recommendation(name: str) -> bool:
    return "fii" in name and ("recomend" in name or "carteira" in name)


def _is_stock_recommendation(name: str) -> bool:
    return "acoes" in name and ("recomend" in name or "carteira" in name)


def client_dir(cliente_id: str) -> Path:
    return PROJECT_ROOT / "clientes" / cliente_id


def month_input_dir(cliente_id: str, mes: str) -> Path:
    return client_dir(cliente_id) / "inputs" / mes


def _matching_files(base: Path, predicate) -> list[Path]:
    if not base.exists():
        return []
    return sorted(
        (
            p
            for p in base.glob("*")
            if p.is_file() and ".bak-" not in p.name and predicate(p.name.lower())
        ),
        key=lambda p: p.name.lower(),
    )


def _mtime(paths: list[Path]) -> str | None:
    if not paths:
        return None
    latest = max(p.stat().st_mtime for p in paths)
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()


def _file_step(
    step_id: str,
    label: str,
    base: Path,
    predicate,
    *,
    required: bool,
    pending_detail: str,
    ok_detail: str = "",
) -> Step:
    matches = _matching_files(base, predicate)
    if matches:
        status = StepStatus.OK
        detail = ok_detail
    else:
        status = StepStatus.WARN if not required else StepStatus.PENDING
        detail = pending_detail
    return Step(
        id=step_id,
        label=label,
        status=status,
        required=required,
        detail=detail,
        files=[p.name for p in matches],
        updated_at=_mtime(matches),
    )


def _classificacao_step(cliente_id: str, mes: str, xp_ok: bool) -> Step:
    """Verifica se ha ativos na posicao M0 ainda sem objetivo mapeado."""
    base = month_input_dir(cliente_id, mes)
    if not xp_ok:
        return Step(
            id="classificacao",
            label="Classificacao de ativos novos",
            status=StepStatus.PENDING,
            required=False,
            detail="Aguardando a posicao da XP para verificar ativos novos.",
        )

    raw = load_month_inputs(base)
    df_m0 = classify_positions(normalize_position(raw["m0"], cliente_id), RULES_FILE)
    map_file = client_dir(cliente_id) / "config" / "asset_objective_map.csv"
    map_df = (
        pd.read_csv(map_file)
        if map_file.exists()
        else pd.DataFrame(columns=["ativo", "objetivo_id", "peso"])
    )
    unmapped = find_unmapped_assets(df_m0, map_df)
    if not unmapped:
        return Step(
            id="classificacao",
            label="Classificacao de ativos novos",
            status=StepStatus.OK,
            required=False,
            detail="Todos os ativos estao mapeados a um objetivo.",
        )
    nomes = ", ".join(str(a.get("ativo", "?")) for a in unmapped[:5])
    if len(unmapped) > 5:
        nomes += f" (+{len(unmapped) - 5})"
    return Step(
        id="classificacao",
        label="Classificacao de ativos novos",
        status=StepStatus.WARN,
        required=False,
        detail=f"{len(unmapped)} ativo(s) sem objetivo: {nomes}",
        files=[str(a.get("ativo", "")) for a in unmapped],
    )


def compute_month_state(cliente_id: str, mes: str) -> MonthState:
    """Deriva o estado completo do mes a partir dos arquivos em disco."""
    base = month_input_dir(cliente_id, mes)
    prev_mes = month_previous(mes)
    prev_base = month_input_dir(cliente_id, prev_mes)

    xp_posicao = _file_step(
        "xp_posicao",
        "Posicao XP (carteira)",
        base,
        _is_xp_posicao,
        required=True,
        pending_detail="Rode a coleta da XP para baixar a posicao (m0).",
    )
    xp_extrato = _file_step(
        "xp_extrato",
        "Extrato XP",
        base,
        _is_extrato,
        required=True,
        pending_detail="Rode a coleta da XP para baixar o extrato.",
    )
    suno_fiis = _file_step(
        "suno_fiis",
        "Carteira recomendada de FIIs (Suno)",
        base,
        _is_fii_recommendation,
        required=False,
        pending_detail="Opcional: rode a coleta da Suno (FIIs) para a analise de recomendacoes.",
    )
    suno_acoes = _file_step(
        "suno_acoes",
        "Carteira recomendada de Acoes (Suno)",
        base,
        _is_stock_recommendation,
        required=False,
        pending_detail="Opcional: rode a coleta da Suno (Acoes) para a analise de recomendacoes.",
    )
    internacional = _file_step(
        "internacional",
        "Posicao internacional (XP International)",
        base,
        _is_internacional,
        required=False,
        pending_detail="Suba o extrato em PDF da XP International com a cotacao USD/BRL do dia.",
    )

    classificacao = _classificacao_step(cliente_id, mes, xp_posicao.status == StepStatus.OK)

    # MoM depende do snapshot m0 do mes anterior (ou m1 legado).
    mom_prev = _matching_files(prev_base, _is_m0) or _matching_files(prev_base, lambda n: "m1" in n)
    mom = Step(
        id="mom",
        label=f"Base para variacao MoM ({prev_mes})",
        status=StepStatus.OK if mom_prev else StepStatus.WARN,
        required=False,
        detail=(
            f"Comparando com a posicao de {prev_mes}."
            if mom_prev
            else f"Sem posicao m0 em inputs/{prev_mes}/: a secao MoM pode ficar vazia."
        ),
        files=[p.name for p in mom_prev],
        updated_at=_mtime(mom_prev),
    )

    steps = [
        xp_posicao,
        xp_extrato,
        suno_fiis,
        suno_acoes,
        internacional,
        classificacao,
        mom,
    ]
    return MonthState(cliente_id=cliente_id, mes=mes, steps=steps)
