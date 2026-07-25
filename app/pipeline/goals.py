from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from core.classification import classify_positions
from ingest.loader import load_month_inputs
from ingest.normalizer import normalize_position
from pipeline.state import RULES_FILE, client_dir, month_input_dir


def objetivos_file(cliente_id: str) -> Path:
    return client_dir(cliente_id) / "objetivos.yaml"


def allocation_file(cliente_id: str) -> Path:
    return client_dir(cliente_id) / "config" / "asset_objective_map.csv"


def planned_moves_file(cliente_id: str, mes: str) -> Path:
    return client_dir(cliente_id) / "planos" / mes / "movimentos.md"


def load_objetivos(cliente_id: str) -> dict:
    path = objetivos_file(cliente_id)
    default = {"cliente": {"id": cliente_id, "nome": cliente_id.title()}, "objetivos": []}
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def save_objetivos(cliente_id: str, data: dict) -> None:
    path = objetivos_file(cliente_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_asset_map(cliente_id: str) -> pd.DataFrame:
    path = allocation_file(cliente_id)
    if not path.exists():
        return pd.DataFrame(columns=["ativo", "objetivo_id", "peso"])
    df = pd.read_csv(path, dtype={"ativo": str, "objetivo_id": str, "peso": float})
    for col in ["ativo", "objetivo_id", "peso"]:
        if col not in df.columns:
            df[col] = None
    return df[["ativo", "objetivo_id", "peso"]]


def save_asset_map(cliente_id: str, rows: list[dict]) -> Path:
    path = allocation_file(cliente_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows, columns=["ativo", "objetivo_id", "peso"])
    df["ativo"] = df["ativo"].astype(str).str.strip()
    df["objetivo_id"] = df["objetivo_id"].astype(str).str.strip()
    df["peso"] = pd.to_numeric(df["peso"], errors="coerce").fillna(1.0)
    df = df[(df["ativo"] != "") & (df["objetivo_id"] != "") & (df["objetivo_id"] != "nan")]
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def load_ativos_mes(cliente_id: str, mes: str) -> pd.DataFrame:
    base = month_input_dir(cliente_id, mes)
    empty = pd.DataFrame(columns=["ativo", "classe_macro", "valor_total"])
    if not base.exists():
        return empty

    raw = load_month_inputs(base)
    df_m0 = classify_positions(normalize_position(raw["m0"], cliente_id), RULES_FILE)
    if df_m0.empty:
        return empty

    return (
        df_m0.groupby(["ativo", "classe_macro"], dropna=False)["valor_total"]
        .sum()
        .reset_index()
        .sort_values("valor_total", ascending=False)
    )


def load_planned_moves(cliente_id: str, mes: str) -> str:
    path = planned_moves_file(cliente_id, mes)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_planned_moves(cliente_id: str, mes: str, content: str) -> Path:
    path = planned_moves_file(cliente_id, mes)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = content.strip()
    path.write_text(content + ("\n" if content else ""), encoding="utf-8")
    return path
