from __future__ import annotations

from typing import Dict, List

import pandas as pd


def build_goal_allocation(df_positions: pd.DataFrame, mapping_df: pd.DataFrame) -> Dict[str, float]:
    if df_positions.empty or mapping_df.empty:
        return {}

    positions = (
        df_positions.groupby("ativo", dropna=False)["valor_total"]
        .sum()
        .reset_index()
        .rename(columns={"valor_total": "valor_ativo"})
    )
    mp = mapping_df.copy()
    mp["ativo"] = mp["ativo"].astype(str)
    mp["objetivo_id"] = mp["objetivo_id"].astype(str)
    mp["peso"] = pd.to_numeric(mp.get("peso", 1.0), errors="coerce").fillna(1.0)

    joined = positions.merge(mp, how="left", on="ativo")
    joined = joined.dropna(subset=["objetivo_id"])
    if joined.empty:
        return {}

    joined["valor_alocado"] = joined["valor_ativo"] * joined["peso"]
    return (
        joined.groupby("objetivo_id", dropna=False)["valor_alocado"]
        .sum()
        .astype(float)
        .to_dict()
    )


def find_unmapped_assets(df_positions: pd.DataFrame, mapping_df: pd.DataFrame) -> List[dict]:
    if df_positions.empty:
        return []

    positions = (
        df_positions.groupby(["ativo", "classe_macro"], dropna=False)["valor_total"]
        .sum()
        .reset_index()
        .rename(columns={"valor_total": "valor_ativo"})
    )
    mapped_assets = set(mapping_df["ativo"].astype(str).tolist()) if not mapping_df.empty else set()
    unmapped = positions[~positions["ativo"].astype(str).isin(mapped_assets)].copy()
    if unmapped.empty:
        return []
    unmapped = unmapped.sort_values("valor_ativo", ascending=False)
    return unmapped.to_dict(orient="records")


def evaluate_goals(
    goals: List[dict],
    position_by_class: Dict[str, float],
    total_equity: float,
    goal_allocations: Dict[str, float] | None = None,
) -> List[dict]:
    cash_value = float(position_by_class.get("Caixa", 0.0))
    fixed_income_value = float(position_by_class.get("Renda Fixa", 0.0)) + float(
        position_by_class.get("Tesouro Direto", 0.0)
    )
    passive_income_estimate = (total_equity * 0.04) / 12.0

    evaluated = []
    for goal in goals:
        goal_type = goal.get("tipo")
        target = float(goal.get("valor_alvo", 0.0))
        desc = goal.get("descricao", goal.get("id", "objetivo_sem_nome"))

        if goal_allocations and goal.get("id") in goal_allocations:
            current = float(goal_allocations[goal.get("id")])
        elif goal_type == "valor_alvo":
            current = cash_value if "caixa" in desc.lower() else fixed_income_value
        elif goal_type == "renda_passiva_mensal":
            current = passive_income_estimate
        elif goal_type == "valor_presente":
            current = total_equity
        else:
            current = 0.0

        progress = (current / target * 100.0) if target else 0.0
        gap = max(target - current, 0.0)

        evaluated.append(
            {
                "id": goal.get("id"),
                "descricao": desc,
                "tipo": goal_type,
                "prioridade": goal.get("prioridade", "media"),
                "valor_alvo": target,
                "valor_atual_estimado": float(current),
                "progresso_pct": float(progress),
                "gap": float(gap),
            }
        )

    return evaluated
