from __future__ import annotations

import re
from typing import Dict, List

import pandas as pd


def _build_allocation_table(df_m0: pd.DataFrame, df_m1: pd.DataFrame, class_col: str) -> List[Dict[str, float]]:
    total_m0 = float(df_m0["valor_total"].sum()) if not df_m0.empty else 0.0

    class_m0 = (
        df_m0.groupby(class_col, dropna=False)["valor_total"].sum().rename("m0")
        if not df_m0.empty
        else pd.Series(dtype=float, name="m0")
    )
    class_m1 = (
        df_m1.groupby(class_col, dropna=False)["valor_total"].sum().rename("m1")
        if not df_m1.empty
        else pd.Series(dtype=float, name="m1")
    )
    class_joined = pd.concat([class_m0, class_m1], axis=1).fillna(0.0)

    rows: List[Dict[str, float]] = []
    for classe, row in class_joined.sort_values("m0", ascending=False).iterrows():
        m0 = float(row["m0"])
        m1 = float(row["m1"])
        variacao = m0 - m1
        variacao_pct = (variacao / m1 * 100.0) if m1 else 0.0
        representatividade = (m0 / total_m0 * 100.0) if total_m0 else 0.0
        rows.append(
            {
                "classe": str(classe),
                "subclasse": "-",
                "m0": m0,
                "m1": m1,
                "variacao": variacao,
                "variacao_pct": variacao_pct,
                "representatividade_pct": representatividade,
            }
        )

    if "subclasse" in df_m0.columns and class_col in df_m0.columns:
        fundos_m0 = df_m0[df_m0[class_col] == "Fundos"]
        fundos_m1 = df_m1[df_m1[class_col] == "Fundos"] if not df_m1.empty else pd.DataFrame()
        if not fundos_m0.empty:
            sub_m0 = fundos_m0.groupby("subclasse", dropna=False)["valor_total"].sum().rename("m0")
            sub_m1 = (
                fundos_m1.groupby("subclasse", dropna=False)["valor_total"].sum().rename("m1")
                if not fundos_m1.empty
                else pd.Series(dtype=float, name="m1")
            )
            sub_joined = pd.concat([sub_m0, sub_m1], axis=1).fillna(0.0)
            for subclasse, row in sub_joined.sort_values("m0", ascending=False).iterrows():
                m0 = float(row["m0"])
                m1 = float(row["m1"])
                variacao = m0 - m1
                variacao_pct = (variacao / m1 * 100.0) if m1 else 0.0
                representatividade = (m0 / total_m0 * 100.0) if total_m0 else 0.0
                rows.append(
                    {
                        "classe": "Fundos",
                        "subclasse": str(subclasse),
                        "m0": m0,
                        "m1": m1,
                        "variacao": variacao,
                        "variacao_pct": variacao_pct,
                        "representatividade_pct": representatividade,
                    }
                )

    return rows


def current_position(df_m0: pd.DataFrame, df_m1: pd.DataFrame | None = None) -> Dict[str, object]:
    class_col = "classe_macro" if "classe_macro" in df_m0.columns else "classe_ativo"
    total = float(df_m0["valor_total"].sum()) if not df_m0.empty else 0.0
    by_class = (
        df_m0.groupby(class_col, dropna=False)["valor_total"]
        .sum()
        .sort_values(ascending=False)
        .to_dict()
        if not df_m0.empty
        else {}
    )
    by_asset = (
        df_m0.groupby("ativo", dropna=False)["valor_total"]
        .sum()
        .sort_values(ascending=False)
        .to_dict()
        if not df_m0.empty
        else {}
    )
    caixa = float(by_class.get("Caixa", 0.0))
    investido = max(total - caixa, 0.0)
    by_fundos_subclasse = {}
    if not df_m0.empty and "subclasse" in df_m0.columns and class_col in df_m0.columns:
        fundos = df_m0[df_m0[class_col] == "Fundos"]
        if not fundos.empty:
            by_fundos_subclasse = (
                fundos.groupby("subclasse", dropna=False)["valor_total"]
                .sum()
                .sort_values(ascending=False)
                .to_dict()
            )
    if df_m1 is None:
        df_m1 = pd.DataFrame(columns=df_m0.columns)
    allocation_table = _build_allocation_table(df_m0, df_m1, class_col)

    return {
        "total": total,
        "investido": investido,
        "caixa": caixa,
        "por_classe": by_class,
        "fundos_por_subclasse": by_fundos_subclasse,
        "alocacao_tabela": allocation_table,
        "por_ativo": by_asset,
    }


def mom_variation(df_m0: pd.DataFrame, df_m1: pd.DataFrame) -> Dict[str, object]:
    if df_m0.empty and df_m1.empty:
        return {"variacao_total": 0.0, "variacao_percentual": 0.0, "por_ativo": {}}

    m0 = df_m0.groupby("ativo", dropna=False)["valor_total"].sum().rename("m0")
    m1 = df_m1.groupby("ativo", dropna=False)["valor_total"].sum().rename("m1")
    joined = pd.concat([m0, m1], axis=1).fillna(0.0)
    joined["variacao"] = joined["m0"] - joined["m1"]
    joined["variacao_pct"] = joined.apply(
        lambda row: (row["variacao"] / row["m1"] * 100.0) if row["m1"] != 0 else 0.0,
        axis=1,
    )

    total_m0 = float(joined["m0"].sum())
    total_m1 = float(joined["m1"].sum())
    total_var = total_m0 - total_m1
    total_var_pct = (total_var / total_m1 * 100.0) if total_m1 else 0.0

    per_asset: Dict[str, Dict[str, float]] = {}
    for asset, row in joined.sort_values("variacao", ascending=False).iterrows():
        per_asset[asset] = {
            "m0": float(row["m0"]),
            "m1": float(row["m1"]),
            "variacao": float(row["variacao"]),
            "variacao_pct": float(row["variacao_pct"]),
        }

    return {
        "variacao_total": float(total_var),
        "variacao_percentual": float(total_var_pct),
        "por_ativo": per_asset,
    }


def build_mom_table_rows(
    df_m0: pd.DataFrame,
    df_m1: pd.DataFrame,
    map_df: pd.DataFrame,
    objetivo_id_para_descricao: Dict[str, str],
) -> List[Dict[str, object]]:
    """Monta linhas da tabela MoM com classe e objetivo por ativo."""
    mom = mom_variation(df_m0, df_m1)
    class_col = "classe_macro" if df_m0 is not None and not df_m0.empty and "classe_macro" in df_m0.columns else "classe_ativo"

    # Mapa ativo -> classe exibida (Fundos inclui subclasse quando existir)
    def classe_para_ativo(ativo: str) -> str:
        if df_m0 is None or df_m0.empty:
            return "-"
        rows = df_m0[df_m0["ativo"].astype(str) == str(ativo)]
        if rows.empty:
            return "-"
        r = rows.loc[rows["valor_total"].idxmax()]
        cm = str(r.get(class_col, r.get("classe_ativo", "-")))
        if cm == "Fundos" and "subclasse" in rows.columns:
            sc = r.get("subclasse")
            if sc is not None and str(sc).strip() not in ("", "nan", "None"):
                return f"{cm} ({sc})"
        return cm

    # Mapa ativo -> texto de objetivo(s)
    obj_por_ativo: Dict[str, str] = {}
    if map_df is not None and not map_df.empty:
        mp = map_df.copy()
        mp["ativo"] = mp["ativo"].astype(str).str.strip()
        mp["objetivo_id"] = mp["objetivo_id"].astype(str).str.strip()

        def ids_para_label(ids: pd.Series) -> str:
            u = sorted({str(x).strip() for x in ids.dropna() if str(x).strip()})
            if not u:
                return "-"
            labels = [objetivo_id_para_descricao.get(i, i) for i in u]
            return ", ".join(labels)

        obj_por_ativo = mp.groupby("ativo", dropna=False)["objetivo_id"].apply(ids_para_label).to_dict()

    linhas: List[Dict[str, object]] = []
    por_ativo = mom.get("por_ativo", {})
    for ativo in sorted(por_ativo.keys(), key=lambda a: por_ativo[a]["variacao"], reverse=True):
        dados = por_ativo[ativo]
        oid_label = obj_por_ativo.get(str(ativo), "-")
        linhas.append(
            {
                "ativo": ativo,
                "classe": classe_para_ativo(str(ativo)),
                "objetivo": oid_label,
                "m0": float(dados["m0"]),
                "m1": float(dados["m1"]),
                "variacao": float(dados["variacao"]),
                "variacao_pct": float(dados["variacao_pct"]),
            }
        )
    return linhas


def _normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        text.lower()
        .replace("ç", "c")
        .replace("ã", "a")
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
    )


def _normalize_column_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _normalize_text(value)).strip("_")


def _extract_ticker(value: object) -> str:
    text = "" if value is None else str(value).upper().strip()
    match = re.search(r"\b[A-Z]{4}\d{2}\b", text)
    if match:
        return match.group(0)
    match = re.search(r"\b[A-Z]{4}\d{1,2}\b", text)
    if match:
        return match.group(0)
    cleaned = re.sub(r"[^A-Z0-9]+", "", text)
    return cleaned


def _extract_asset_from_description(description: object) -> str:
    text = "" if description is None else str(description).strip()
    patterns = [
        r"RENDIMENTOS DE CLIENTES\s+([A-Z0-9]+)",
        r"BTC\s+([A-Z0-9]+)",
        r"EVENTO\s+([A-Z0-9]+)",
        r"Pgto Juros\s+([^|]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return "-"


def classify_cashflows(df_extrato: pd.DataFrame) -> Dict[str, object]:
    """
    Classifica eventos do extrato em ganhos recorrentes (dividendos/proventos/juros)
    e perdas operacionais (taxas, impostos e debitos relacionados).
    """
    empty = {
        "total_ganhos": 0.0,
        "total_perdas": 0.0,
        "liquido": 0.0,
        "por_data": [],
        "eventos": [],
        "max_abs_diario": 0.0,
    }
    if df_extrato.empty or "resultado" not in df_extrato.columns:
        return empty

    income_keywords = (
        "rendimento",
        "rendimentos",
        "dividendo",
        "dividendos",
        "provento",
        "proventos",
        "juros",
        "jcp",
        "credito ref. taxa de remuneracao",
        "credito de reembolso de evento",
    )
    expense_keywords = (
        "taxa",
        "irrf",
        "imposto",
        "debito cblc",
        "emolumento",
        "corretagem",
        "custodia",
    )
    ignore_keywords = (
        "transferencia",
        "ted ",
        "compra",
        "venda",
        "aplicacao fundos",
        "resgate",
    )

    df = df_extrato.copy()
    if "data" not in df.columns:
        df["data"] = ""
    if "descricao" not in df.columns:
        df["descricao"] = ""
    df["resultado"] = pd.to_numeric(df["resultado"], errors="coerce").fillna(0.0)

    eventos: List[Dict[str, object]] = []
    for _, row in df.iterrows():
        valor = float(row["resultado"])
        desc = str(row.get("descricao", ""))
        desc_norm = _normalize_text(desc)
        if any(k in desc_norm for k in ignore_keywords):
            continue

        is_income = valor > 0 and any(k in desc_norm for k in income_keywords)
        is_expense = valor < 0 and any(k in desc_norm for k in expense_keywords)
        if not is_income and not is_expense:
            continue

        eventos.append(
            {
                "data": str(row.get("data", "")),
                "descricao": desc,
                "ativo": _extract_asset_from_description(desc),
                "tipo": "Ganho" if is_income else "Perda",
                "valor": valor,
            }
        )

    if not eventos:
        return empty

    eventos_df = pd.DataFrame(eventos)
    eventos_df["ganhos"] = eventos_df["valor"].where(eventos_df["valor"] > 0, 0.0)
    eventos_df["perdas"] = eventos_df["valor"].where(eventos_df["valor"] < 0, 0.0)
    por_data_df = (
        eventos_df.groupby("data", dropna=False)[["ganhos", "perdas"]]
        .sum()
        .reset_index()
        .sort_values("data")
    )
    por_data_df["liquido"] = por_data_df["ganhos"] + por_data_df["perdas"]

    por_data = [
        {
            "data": str(row["data"]),
            "ganhos": float(row["ganhos"]),
            "perdas": float(row["perdas"]),
            "liquido": float(row["liquido"]),
        }
        for _, row in por_data_df.iterrows()
    ]
    total_ganhos = float(eventos_df["ganhos"].sum())
    total_perdas = float(eventos_df["perdas"].sum())
    max_abs = max(
        [abs(float(row["ganhos"])) for row in por_data]
        + [abs(float(row["perdas"])) for row in por_data]
        + [1.0]
    )

    return {
        "total_ganhos": total_ganhos,
        "total_perdas": total_perdas,
        "liquido": total_ganhos + total_perdas,
        "por_data": por_data,
        "eventos": sorted(eventos, key=lambda e: (str(e["data"]), float(e["valor"])), reverse=True),
        "max_abs_diario": float(max_abs),
    }


def build_trade_rows(df_m0: pd.DataFrame, df_m1: pd.DataFrame) -> List[Dict[str, object]]:
    """Identifica compras e vendas por variacao de quantidade entre M1 e M0."""
    if df_m0.empty and df_m1.empty:
        return []

    m0 = (
        df_m0.groupby("ativo", dropna=False)
        .agg(
            quantidade_m0=("quantidade", "sum"),
            valor_m0=("valor_total", "sum"),
            classe=("classe_macro", "first"),
        )
        if not df_m0.empty
        else pd.DataFrame(columns=["quantidade_m0", "valor_m0", "classe"])
    )
    m1 = (
        df_m1.groupby("ativo", dropna=False)
        .agg(
            quantidade_m1=("quantidade", "sum"),
            valor_m1=("valor_total", "sum"),
            classe_m1=("classe_macro", "first"),
        )
        if not df_m1.empty
        else pd.DataFrame(columns=["quantidade_m1", "valor_m1", "classe_m1"])
    )
    joined = pd.concat([m0, m1], axis=1).fillna(
        {
            "quantidade_m0": 0.0,
            "valor_m0": 0.0,
            "quantidade_m1": 0.0,
            "valor_m1": 0.0,
            "classe": "-",
            "classe_m1": "-",
        }
    )

    rows: List[Dict[str, object]] = []
    for ativo, row in joined.iterrows():
        qtd_m0 = float(row.get("quantidade_m0", 0.0))
        qtd_m1 = float(row.get("quantidade_m1", 0.0))
        valor_m0 = float(row.get("valor_m0", 0.0))
        valor_m1 = float(row.get("valor_m1", 0.0))
        delta_qtd = qtd_m0 - qtd_m1
        delta_valor = valor_m0 - valor_m1

        uses_quantity = abs(qtd_m0) > 0 or abs(qtd_m1) > 0
        if uses_quantity:
            if abs(delta_qtd) < 1e-9:
                continue
            tipo = "Compra" if delta_qtd > 0 else "Venda"
            if qtd_m1 == 0 and qtd_m0 > 0:
                tipo = "Nova posicao"
            elif qtd_m0 == 0 and qtd_m1 > 0:
                tipo = "Venda total"
        else:
            if abs(delta_valor) < 0.01:
                continue
            tipo = "Aumento" if delta_valor > 0 else "Reducao"

        preco_medio_estimado = abs(delta_valor / delta_qtd) if abs(delta_qtd) > 1e-9 else 0.0
        rows.append(
            {
                "ativo": str(ativo),
                "classe": str(row.get("classe", "-") if row.get("classe", "-") != "-" else row.get("classe_m1", "-")),
                "tipo": tipo,
                "quantidade_m1": qtd_m1,
                "quantidade_m0": qtd_m0,
                "delta_quantidade": delta_qtd,
                "valor_m1": valor_m1,
                "valor_m0": valor_m0,
                "delta_valor": delta_valor,
                "preco_medio_estimado": preco_medio_estimado,
            }
        )

    return sorted(rows, key=lambda r: abs(float(r["delta_valor"])), reverse=True)


def normalize_fii_recommendations(df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "rank",
        "ativo",
        "ticker",
        "vies",
        "recomendado",
        "rank_num",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    normalized_columns = {_normalize_column_name(col): col for col in df.columns}

    def pick(*candidates: str) -> str | None:
        for candidate in candidates:
            normalized = _normalize_column_name(candidate)
            if normalized in normalized_columns:
                return normalized_columns[normalized]
        return None

    rank_col = pick("Rank", "Ranking", "Posicao", "Posição")
    ativo_col = pick("Ativo", "Ticker", "Codigo", "Código", "FII", "Fundo")
    vies_col = pick("Vies", "Viés", "Status", "Recomendacao", "Recomendação")

    if ativo_col is None:
        return pd.DataFrame(columns=columns)

    out = pd.DataFrame()
    out["rank"] = df[rank_col] if rank_col else ""
    out["ativo"] = df[ativo_col]
    out["ticker"] = out["ativo"].apply(_extract_ticker)
    out["vies"] = df[vies_col] if vies_col else ""
    out["rank_num"] = pd.to_numeric(out["rank"], errors="coerce")
    out["recomendado"] = out["rank"].apply(lambda value: str(value).strip() not in ("", "nan", "None"))
    out["vies"] = out["vies"].fillna("").astype(str).str.strip()
    out = out[out["ticker"].astype(str).str.strip() != ""]
    out = out.drop_duplicates(subset=["ticker"], keep="last")
    return out[columns]


def build_fii_recommendation_actions(df_m0: pd.DataFrame, recommendation_df: pd.DataFrame) -> Dict[str, object]:
    empty = {
        "disponivel": False,
        "acoes": [],
        "resumo": {"comprar": 0, "aumentar": 0, "aguardar": 0, "reduzir": 0, "encerrar": 0},
    }
    recs = normalize_fii_recommendations(recommendation_df)
    if recs.empty:
        return empty

    current = df_m0.copy()
    if current.empty:
        current = pd.DataFrame(columns=["ativo", "classe_macro", "quantidade", "valor_total"])
    class_col = "classe_macro" if "classe_macro" in current.columns else "classe_ativo"
    if class_col in current.columns:
        current = current[current[class_col].astype(str).str.upper().eq("FII")]
    else:
        current = current.iloc[0:0]

    current["ticker"] = current["ativo"].apply(_extract_ticker) if "ativo" in current.columns else ""
    current_by_ticker = (
        current.groupby("ticker", dropna=False)
        .agg(
            ativo_carteira=("ativo", "first"),
            quantidade=("quantidade", "sum"),
            valor_atual=("valor_total", "sum"),
        )
        .reset_index()
        if not current.empty
        else pd.DataFrame(columns=["ticker", "ativo_carteira", "quantidade", "valor_atual"])
    )

    joined = recs.merge(current_by_ticker, how="left", on="ticker")
    joined["quantidade"] = pd.to_numeric(joined["quantidade"], errors="coerce").fillna(0.0)
    joined["valor_atual"] = pd.to_numeric(joined["valor_atual"], errors="coerce").fillna(0.0)
    joined["em_carteira"] = joined["valor_atual"] > 0

    rows: List[Dict[str, object]] = []
    for _, row in joined.iterrows():
        recomendado = bool(row["recomendado"])
        em_carteira = bool(row["em_carteira"])
        vies_norm = _normalize_text(row.get("vies", ""))

        if not recomendado and em_carteira:
            acao = "Encerrar posicao"
            prioridade = 1
            motivo = "Rank vazio no arquivo de recomendacao; o ativo deixou de ser recomendado."
        elif not recomendado:
            acao = "Fora da carteira recomendada"
            prioridade = 5
            motivo = "Rank vazio no arquivo de recomendacao e ativo nao consta na carteira atual."
        elif "compr" in vies_norm and em_carteira:
            acao = "Aumentar posicao"
            prioridade = 2
            motivo = "Ativo segue recomendado com vies Comprar e ja esta na carteira."
        elif "compr" in vies_norm:
            acao = "Comprar"
            prioridade = 2
            motivo = "Ativo recomendado com vies Comprar e ainda nao esta na carteira."
        elif "aguard" in vies_norm and em_carteira:
            acao = "Reduzir / nao aumentar"
            prioridade = 3
            motivo = "Ativo segue no ranking, mas o vies atual e Aguardar."
        elif "aguard" in vies_norm:
            acao = "Aguardar"
            prioridade = 4
            motivo = "Ativo recomendado no ranking, mas com vies Aguardar."
        elif recomendado and em_carteira:
            acao = "Manter"
            prioridade = 4
            motivo = "Ativo esta no ranking, sem vies reconhecido como Comprar ou Aguardar."
        else:
            acao = "Monitorar"
            prioridade = 5
            motivo = "Ativo esta no ranking, sem vies reconhecido como Comprar ou Aguardar."

        rows.append(
            {
                "rank": "" if pd.isna(row.get("rank")) else row.get("rank"),
                "rank_num": float(row["rank_num"]) if not pd.isna(row["rank_num"]) else 9999.0,
                "ativo": str(row.get("ativo", "")),
                "ticker": str(row.get("ticker", "")),
                "vies": str(row.get("vies", "")),
                "em_carteira": em_carteira,
                "quantidade": float(row["quantidade"]),
                "valor_atual": float(row["valor_atual"]),
                "acao": acao,
                "prioridade": prioridade,
                "motivo": motivo,
            }
        )

    resumo = {
        "comprar": sum(1 for row in rows if row["acao"] == "Comprar"),
        "aumentar": sum(1 for row in rows if row["acao"] == "Aumentar posicao"),
        "aguardar": sum(1 for row in rows if row["acao"] in {"Aguardar", "Manter"}),
        "reduzir": sum(1 for row in rows if row["acao"] == "Reduzir / nao aumentar"),
        "encerrar": sum(1 for row in rows if row["acao"] == "Encerrar posicao"),
    }

    rows = sorted(rows, key=lambda row: (int(row["prioridade"]), float(row["rank_num"]), str(row["ticker"])))
    return {"disponivel": True, "acoes": rows, "resumo": resumo}


def summarize_trade_rows(rows: List[Dict[str, object]], top_n: int = 12) -> Dict[str, object]:
    buy_types = {"Compra", "Nova posicao", "Aumento"}
    sell_types = {"Venda", "Venda total", "Reducao"}

    compras = [row for row in rows if str(row.get("tipo")) in buy_types]
    vendas = [row for row in rows if str(row.get("tipo")) in sell_types]

    def summarize_side(items: List[Dict[str, object]]) -> Dict[str, object]:
        return {
            "quantidade": len(items),
            "valor_total": float(sum(abs(float(row.get("delta_valor", 0.0))) for row in items)),
            "principais": sorted(
                items,
                key=lambda row: abs(float(row.get("delta_valor", 0.0))),
                reverse=True,
            )[:top_n],
        }

    return {
        "compras": summarize_side(compras),
        "vendas": summarize_side(vendas),
        "total_movimentos": len(rows),
    }


def portfolio_return(df_extrato: pd.DataFrame, current_total: float) -> Dict[str, float]:
    if df_extrato.empty or current_total <= 0:
        return {"resultado_mes": 0.0, "rentabilidade_pct": 0.0}

    result_col = "resultado" if "resultado" in df_extrato.columns else None
    if not result_col:
        return {"resultado_mes": 0.0, "rentabilidade_pct": 0.0}

    result_value = float(df_extrato[result_col].sum())
    return_pct = (result_value / current_total) * 100.0 if current_total else 0.0
    return {"resultado_mes": result_value, "rentabilidade_pct": return_pct}


def estimate_passive_income(current_total: float, annual_withdrawal_rate: float = 0.04) -> float:
    monthly = (current_total * annual_withdrawal_rate) / 12.0
    return float(monthly)


def format_top_list(values: Dict[str, float], top_n: int = 5) -> List[Dict[str, float]]:
    items = sorted(values.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [{"nome": name, "valor": float(value)} for name, value in items]
