from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd


SECTION_CLASS_MAP = {
    "Ações": "Ações",
    "Posição de Fundos Imobiliários": "FII",
    "Fundos Imobiliários": "FII",
    "Fundos de Investimentos": "Fundos",
    "Tesouro Direto": "Tesouro Direto",
    "Renda Fixa": "Renda Fixa",
    "COE": "COE",
}

IGNORE_SECTION_TITLES = {
    "Dividendos, proventos e outras distribuições",
    "Proventos",
    "Custódia Remunerada",
}


def _parse_brl(value) -> float:
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace("R$", "").replace("%", "").strip()
    text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_number(value) -> float:
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_xp_position(path: Path, cliente_id: str) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None)
    records: List[dict] = []

    account = "Nao informada"
    date_ref = None
    current_class = "Outros"
    cash_added = False

    for _, row in raw.iterrows():
        c0 = row.iloc[0] if len(row) > 0 else None
        c1 = row.iloc[1] if len(row) > 1 else None
        c2 = row.iloc[2] if len(row) > 2 else None
        c5 = row.iloc[5] if len(row) > 5 else None
        c6 = row.iloc[6] if len(row) > 6 else None
        c7 = row.iloc[7] if len(row) > 7 else None

        if isinstance(c0, str) and "Conta:" in c0:
            account = c0
        elif isinstance(c5, str) and "Conta:" in c5:
            account = c5

        if isinstance(c0, str) and "Data da Posição Histórica:" in c0:
            part = c0.split("Data da Posição Histórica:")[-1].strip()
            try:
                date_ref = datetime.strptime(part, "%d/%m/%Y").date().isoformat()
            except ValueError:
                pass

        if isinstance(c0, str) and c0 in IGNORE_SECTION_TITLES:
            current_class = "Ignorar"
            continue

        if isinstance(c0, str) and c0 in SECTION_CLASS_MAP:
            current_class = SECTION_CLASS_MAP[c0]
            continue

        # Captura o saldo disponivel informado no cabecalho da XP.
        # A linha seguinte ao texto de patrimonio costuma trazer:
        # [patrimonio total, total investido, saldo disponivel, saldo projetado, ...]
        if not cash_added and isinstance(c0, str) and c0.strip().startswith("R$"):
            saldo_disponivel = _parse_brl(c2)
            if saldo_disponivel > 0:
                records.append(
                    {
                        "data_referencia": date_ref,
                        "ativo": "Saldo Disponivel XP",
                        "classe_ativo": "Caixa",
                        "quantidade": 1.0,
                        "preco_unitario": saldo_disponivel,
                        "valor_total": saldo_disponivel,
                        "instituicao": "XP",
                        "conta": account,
                        "cliente_id": cliente_id,
                    }
                )
                cash_added = True

        # Linhas de ativos costumam ter: nome/ticker na col A, valor em "R$" na col B e quantidade na col G/H.
        if not isinstance(c0, str):
            continue
        if c0 in SECTION_CLASS_MAP or c0.startswith(("R$", "%", "Conta:", "Gabriel Dimes")):
            continue
        if " | " in c0 or c0.startswith("Posição") or c0.startswith("Provisionado"):
            continue
        if current_class == "Ignorar":
            continue

        if not (isinstance(c1, str) and "R$" in c1):
            continue

        value_total = _parse_brl(c1)
        if value_total <= 0:
            continue

        quantity = _parse_number(c7) if not pd.isna(c7) else _parse_number(c6)
        price = _parse_brl(c6) if not pd.isna(c6) else 0.0
        if price == 0.0 and quantity > 0:
            price = value_total / quantity

        records.append(
            {
                "data_referencia": date_ref,
                "ativo": c0.strip(),
                "classe_ativo": current_class,
                "quantidade": quantity,
                "preco_unitario": price,
                "valor_total": value_total,
                "instituicao": "XP",
                "conta": account,
                "cliente_id": cliente_id,
            }
        )

    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "data_referencia",
                "ativo",
                "classe_ativo",
                "quantidade",
                "preco_unitario",
                "valor_total",
                "instituicao",
                "conta",
                "cliente_id",
            ]
        )
    return df


def parse_xp_extrato(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path, header=None)
    records: List[dict] = []
    in_table = False

    for _, row in raw.iterrows():
        row_values = row.tolist()
        cleaned = [v for v in row_values if not pd.isna(v)]
        if any(isinstance(v, str) and v.strip() == "Movimentação" for v in cleaned):
            in_table = True
            continue

        if not in_table:
            continue

        datetime_indexes = [i for i, v in enumerate(row_values) if isinstance(v, datetime)]
        if not datetime_indexes:
            continue

        # Layout XP costuma ter duas datas seguidas (movimentacao/liquidacao).
        first_date_idx = datetime_indexes[0]
        desc_idx = first_date_idx + 2

        desc = row_values[desc_idx] if desc_idx < len(row_values) else None
        value = None
        for idx in range(desc_idx + 1, len(row_values)):
            candidate = row_values[idx]
            if isinstance(candidate, (int, float)) and not pd.isna(candidate):
                value = candidate
                break
            if isinstance(candidate, str) and "R$" in candidate:
                value = candidate
                break

        if isinstance(row_values[first_date_idx], datetime) and isinstance(desc, str):
            records.append(
                {
                    "data": row_values[first_date_idx].date().isoformat(),
                    "descricao": desc.strip(),
                    "resultado": _parse_brl(value),
                }
            )

    return pd.DataFrame(records, columns=["data", "descricao", "resultado"])
