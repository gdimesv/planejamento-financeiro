from __future__ import annotations

from typing import Dict

import pandas as pd


EXPECTED_COLUMNS = [
    "data_referencia",
    "ativo",
    "classe_ativo",
    "classe_macro",
    "subclasse",
    "classificacao_confianca",
    "quantidade",
    "preco_unitario",
    "valor_total",
    "instituicao",
    "conta",
    "cliente_id",
]


def normalize_position(df: pd.DataFrame, cliente_id: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

    df = df.copy()
    normalized_columns = {col: str(col).lower().strip() for col in df.columns}

    def pick_all(*candidates: str) -> list[str]:
        wanted = {c.lower().strip() for c in candidates}
        return [col for col, norm in normalized_columns.items() if norm in wanted]

    def coalesce_columns(columns: list[str], default=None) -> pd.Series:
        if not columns:
            return pd.Series([default] * len(df), index=df.index)
        series = df[columns[0]]
        for col in columns[1:]:
            series = series.combine_first(df[col])
        return series

    def parse_number_series(series: pd.Series) -> pd.Series:
        def parse_value(value) -> float:
            if pd.isna(value):
                return 0.0
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value).strip().replace("R$", "").replace("%", "")
            text = text.replace(" ", "").replace('"', "")
            if "," in text:
                # Formato brasileiro com decimal em virgula.
                text = text.replace(".", "").replace(",", ".")
            else:
                # Caso comum em CSV manual: "5.361" significando 5361.
                parts = text.split(".")
                if len(parts) > 1 and all(part.isdigit() and len(part) == 3 for part in parts[1:]):
                    text = "".join(parts)
            try:
                return float(text)
            except ValueError:
                return 0.0

        return series.apply(parse_value)

    cols_ativo = pick_all("ativo", "asset", "papel")
    cols_classe = pick_all("classe_ativo", "classe", "tipo")
    cols_qtd = pick_all("quantidade", "qtd")
    cols_preco = pick_all("preco_unitario", "preco")
    cols_valor = pick_all("valor_total", "valor", "saldo", "valor atual (r$)")
    cols_data = pick_all("data_referencia", "data")
    cols_inst = pick_all("instituicao", "banco", "corretora")
    cols_conta = pick_all("conta")

    out = pd.DataFrame()
    out["data_referencia"] = coalesce_columns(cols_data, None)
    out["ativo"] = coalesce_columns(cols_ativo, "Desconhecido")
    out["classe_ativo"] = coalesce_columns(cols_classe, "Outros")
    out["classe_macro"] = out["classe_ativo"]
    out["subclasse"] = out["classe_ativo"]
    out["classificacao_confianca"] = "alta"
    out["quantidade"] = parse_number_series(coalesce_columns(cols_qtd, 0.0))
    out["preco_unitario"] = parse_number_series(coalesce_columns(cols_preco, 0.0))
    out["valor_total"] = parse_number_series(coalesce_columns(cols_valor, 0.0))
    out["instituicao"] = coalesce_columns(cols_inst, "Nao informado")
    out["conta"] = coalesce_columns(cols_conta, "Nao informada")
    out["cliente_id"] = cliente_id

    return out[EXPECTED_COLUMNS]


def normalize_extrato(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["data", "descricao", "resultado"])

    out = df.copy()
    mapper = {c.lower().strip(): c for c in out.columns}

    def parse_money(value) -> float:
        if pd.isna(value):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace("R$", "").replace("%", "").replace(" ", "")
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return 0.0

    if "data" not in mapper:
        for candidate in ("data movimentacao", "data movimentação", "movimentacao", "movimentação"):
            if candidate in mapper:
                out["data"] = out[mapper[candidate]]
                break

    if "descricao" not in mapper:
        for candidate in ("descrição", "historico", "histórico", "movimentacao", "movimentação"):
            if candidate in mapper:
                out["descricao"] = out[mapper[candidate]]
                break

    if "resultado" not in mapper:
        if "valor" in mapper:
            out["resultado"] = out[mapper["valor"]].apply(parse_money)
        else:
            out["resultado"] = 0.0
    else:
        out["resultado"] = out[mapper["resultado"]].apply(parse_money)

    if "data" not in out.columns:
        out["data"] = ""
    if "descricao" not in out.columns:
        out["descricao"] = ""

    return out
