from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import yaml

# Unicas classes hoje originadas da posicao internacional (extrato XP International).
CLASSES_EXTERIOR = ("Ações no Exterior",)


def _load_rules(path: Path) -> dict:
    if not path.exists():
        return {"defaults": {"subclasse": "Fundo Outros", "confianca": "baixa"}, "rules": []}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"defaults": {}, "rules": []}


def classify_positions(df: pd.DataFrame, rules_path: Path) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    if "classe_macro" not in out.columns:
        out["classe_macro"] = out["classe_ativo"]
    if "subclasse" not in out.columns:
        out["subclasse"] = out["classe_macro"]
    if "classificacao_confianca" not in out.columns:
        out["classificacao_confianca"] = "alta"

    rules_cfg = _load_rules(rules_path)
    defaults = rules_cfg.get("defaults", {})
    rules = rules_cfg.get("rules", [])

    is_fundos = out["classe_macro"].astype(str).str.lower().eq("fundos")
    out.loc[is_fundos, "subclasse"] = defaults.get("subclasse", "Fundo Outros")
    out.loc[is_fundos, "classificacao_confianca"] = defaults.get("confianca", "baixa")

    for rule in rules:
        field = rule.get("field", "ativo")
        if field not in out.columns:
            continue
        raw = out[field].astype(str)
        match_type = rule.get("match_type", "contains")
        value = str(rule.get("value", ""))
        if not value:
            continue

        if match_type == "contains":
            mask = raw.str.contains(re.escape(value), case=False, na=False)
        elif match_type == "regex":
            mask = raw.str.contains(value, na=False, regex=True)
        else:
            continue

        mask = mask & is_fundos
        out.loc[mask, "subclasse"] = rule.get("subclasse", out.loc[mask, "subclasse"])
        out.loc[mask, "classificacao_confianca"] = rule.get(
            "confianca", out.loc[mask, "classificacao_confianca"]
        )

    return out
