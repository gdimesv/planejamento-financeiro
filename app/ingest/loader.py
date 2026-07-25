from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd

from adapters.xp import parse_xp_extrato, parse_xp_position


def month_previous(yyyy_mm: str) -> str:
    """Retorna o YYYY-MM do mes anterior (ex.: 2026-03 -> 2026-02)."""
    y, m = yyyy_mm.split("-")
    yi, mi = int(y), int(m)
    if mi == 1:
        return f"{yi - 1}-12"
    return f"{yi:04d}-{mi - 1:02d}"


def _read_any_table(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype=str, sep=None, engine="python")
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.DataFrame()


def _read_manual_international_position(path: Path) -> pd.DataFrame:
    """
    Le planilhas manuais de exterior.

    O caso recorrente e um arquivo .xlsx com varias abas, onde a posicao esta
    em uma aba chamada "Ativos Exterior" com as colunas do template manual.
    """
    expected = {"classe", "ativo", "valor atual (r$)"}
    if path.suffix.lower() == ".csv":
        df = _read_any_table(path)
        cols = {str(col).lower().strip() for col in df.columns}
        return df if expected.issubset(cols) else pd.DataFrame()

    if path.suffix.lower() not in {".xlsx", ".xls"}:
        return pd.DataFrame()

    try:
        xls = pd.ExcelFile(path)
    except Exception:
        return pd.DataFrame()

    preferred = [s for s in xls.sheet_names if "exterior" in s.lower() or "internacional" in s.lower()]
    sheet_names = preferred + [s for s in xls.sheet_names if s not in preferred]
    for sheet_name in sheet_names:
        df = pd.read_excel(path, sheet_name=sheet_name)
        cols = {str(col).lower().strip() for col in df.columns}
        if expected.issubset(cols):
            return df

    return pd.DataFrame()


def load_month_inputs(current_month_dir: Path) -> Dict[str, pd.DataFrame]:
    """
    Carrega extrato e posicao M0 da pasta do mes de referencia.

    A posicao M1 (mes anterior para MoM) NAO fica na pasta do mes atual:
    ela e obtida automaticamente da pasta do mes anterior, usando os mesmos
    tipos de arquivo de posicao (nomes com `m0`, ex.: snapshot que voce guardou
    naquele mes). Assim o cliente so envia arquivos do mes recorrente na pasta
    do mes atual.

    Compatibilidade: se nao houver nada utilizavel na pasta do mes anterior,
    tenta arquivos com `m1` no nome na pasta atual (fluxo antigo).
    """
    mes = current_month_dir.name
    cliente_id = current_month_dir.parents[1].name
    inputs_root = current_month_dir.parent
    prev_dir = inputs_root / month_previous(mes)

    files_current = list(current_month_dir.glob("*")) if current_month_dir.exists() else []
    def is_fii_recommendation(path: Path) -> bool:
        name = path.name.lower()
        return "fii" in name and ("recomend" in name or "carteira" in name)

    def is_stock_recommendation(path: Path) -> bool:
        name = path.name.lower()
        return "acoes" in name and ("recomend" in name or "carteira" in name)

    extratos = [p for p in files_current if p.is_file() and "extrato" in p.name.lower()]
    m0_files = [p for p in files_current if p.is_file() and "m0" in p.name.lower()]
    fii_recommendation_files = [p for p in files_current if p.is_file() and is_fii_recommendation(p)]
    stock_recommendation_files = [p for p in files_current if p.is_file() and is_stock_recommendation(p)]

    files_prev = list(prev_dir.glob("*")) if prev_dir.exists() else []
    # Snapshot do mes anterior = arquivos `m0` guardados na pasta do mes anterior
    m1_from_prev = [p for p in files_prev if p.is_file() and "m0" in p.name.lower()]
    if not m1_from_prev:
        # Pasta anterior com export nomeado como m1 (legado)
        m1_from_prev = [p for p in files_prev if p.is_file() and "m1" in p.name.lower()]

    m1_files = m1_from_prev
    if not m1_files:
        # Fluxo antigo: m1 na mesma pasta do mes de referencia
        m1_files = [p for p in files_current if p.is_file() and "m1" in p.name.lower()]

    def load_extrato(path: Path | None) -> pd.DataFrame:
        if not path:
            return pd.DataFrame()
        if "xp" in path.name.lower() and path.suffix.lower() in {".xlsx", ".xls"}:
            return parse_xp_extrato(path)
        return _read_any_table(path)

    def load_position(path: Path | None, cid: str) -> pd.DataFrame:
        if not path:
            return pd.DataFrame()
        lower_name = path.name.lower()
        if any(token in lower_name for token in ("_int", "internacional", "exterior", "usa")):
            manual = _read_manual_international_position(path)
            if not manual.empty:
                return manual
        if "xp" in path.name.lower() and path.suffix.lower() in {".xlsx", ".xls"}:
            return parse_xp_position(path, cid)
        return _read_any_table(path)

    def load_many(paths: list[Path], loader) -> pd.DataFrame:
        if not paths:
            return pd.DataFrame()
        frames = [loader(path) for path in sorted(paths, key=lambda p: p.name.lower())]
        frames = [df for df in frames if not df.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True, sort=False)

    return {
        "extrato": load_many(extratos, load_extrato),
        "m0": load_many(m0_files, lambda p: load_position(p, cliente_id)),
        "m1": load_many(m1_files, lambda p: load_position(p, cliente_id)),
        "fii_recommendations": load_many(fii_recommendation_files, _read_any_table),
        "stock_recommendations": load_many(stock_recommendation_files, _read_any_table),
    }
