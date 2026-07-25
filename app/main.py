from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

from core.goals import (
    build_goal_allocation,
    evaluate_goals,
    find_unmapped_assets,
    suggest_monthly_investment,
)
from core.classification import classify_positions
from core.metrics import (
    build_fii_recommendation_actions,
    build_mom_table_rows,
    build_stock_recommendation_actions,
    build_trade_rows,
    classify_cashflows,
    current_position,
    mom_variation,
    portfolio_return,
    summarize_trade_rows,
)
from ingest.loader import load_month_inputs
from ingest.normalizer import normalize_extrato, normalize_position
from macros.macro_loader import load_macro_commentary
from reporting.html_report import render_report


def load_planned_moves(client_dir: Path, mes: str) -> str:
    path = client_dir / "planos" / mes / "movimentos.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def build_cashflow_history(client_dir: Path, mes_limite: str) -> dict:
    inputs_dir = client_dir / "inputs"
    if not inputs_dir.exists():
        return {"por_mes": [], "max_abs_mensal": 0.0}

    events_by_key = {}
    for month_dir in sorted(inputs_dir.iterdir(), key=lambda p: p.name):
        if not month_dir.is_dir() or month_dir.name == "_templates" or month_dir.name > mes_limite:
            continue
        raw = load_month_inputs(month_dir)
        flows = classify_cashflows(normalize_extrato(raw["extrato"]))
        for event in flows["eventos"]:
            event_month = str(event.get("data", ""))[:7]
            if not event_month or event_month > mes_limite:
                continue
            key = (
                str(event.get("data", "")),
                str(event.get("descricao", "")),
                round(float(event.get("valor", 0.0)), 2),
            )
            events_by_key[key] = event

    monthly: dict[str, dict] = {}
    for event in events_by_key.values():
        event_month = str(event.get("data", ""))[:7]
        if not event_month:
            continue
        row = monthly.setdefault(event_month, {"mes": event_month, "ganhos": 0.0, "perdas": 0.0, "liquido": 0.0})
        value = float(event.get("valor", 0.0))
        if value > 0:
            row["ganhos"] += value
        else:
            row["perdas"] += value
        row["liquido"] += value

    rows = [monthly[key] for key in sorted(monthly)]

    max_abs = max(
        [abs(float(row["ganhos"])) for row in rows]
        + [abs(float(row["perdas"])) for row in rows]
        + [1.0]
    )
    return {"por_mes": rows, "max_abs_mensal": float(max_abs)}


def run(cliente_id: str, mes: str, aporte_mensal: float) -> Path:
    root = Path(__file__).resolve().parents[1]
    client_dir = root / "clientes" / cliente_id
    input_dir = client_dir / "inputs" / mes
    output_file = client_dir / "outputs" / mes / "relatorio.html"
    objetivos_file = client_dir / "objetivos.yaml"
    macro_file = root / "data" / "macro" / f"{mes}.csv"
    map_file = client_dir / "config" / "asset_objective_map.csv"

    with objetivos_file.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    raw = load_month_inputs(input_dir)
    if raw["m1"].empty:
        print(
            "Aviso: nenhuma posicao M1 carregada (mes anterior ou legado m1). "
            "A secao MoM pode ficar vazia ou incompleta.",
            file=sys.stderr,
        )
    df_m0 = normalize_position(raw["m0"], cliente_id)
    df_m1 = normalize_position(raw["m1"], cliente_id)
    rules_file = root / "data" / "mapping" / "fundos_rules.yaml"
    df_m0 = classify_positions(df_m0, rules_file)
    df_m1 = classify_positions(df_m1, rules_file)
    df_extrato = normalize_extrato(raw["extrato"])

    pos = current_position(df_m0, df_m1)
    mom = mom_variation(df_m0, df_m1)
    map_df = pd.read_csv(map_file) if map_file.exists() else pd.DataFrame(columns=["ativo", "objetivo_id", "peso"])
    objetivo_id_para_descricao = {
        str(o.get("id")): str(o.get("descricao", o.get("id", "")))
        for o in config.get("objetivos", [])
        if o.get("id")
    }
    mom_linhas = build_mom_table_rows(df_m0, df_m1, map_df, objetivo_id_para_descricao)
    compras_vendas = build_trade_rows(df_m0, df_m1)
    resumo_compras_vendas = summarize_trade_rows(compras_vendas)
    recomendacoes_fii = build_fii_recommendation_actions(df_m0, raw.get("fii_recommendations", pd.DataFrame()))
    recomendacoes_acoes = build_stock_recommendation_actions(df_m0, raw.get("stock_recommendations", pd.DataFrame()))
    if "data" in df_extrato.columns:
        df_extrato_mes = df_extrato[df_extrato["data"].astype(str).str.startswith(mes)]
    else:
        df_extrato_mes = df_extrato
    rent = portfolio_return(df_extrato_mes, pos["total"])
    fluxos_extrato = classify_cashflows(df_extrato_mes)
    historico_fluxos = build_cashflow_history(client_dir, mes)
    movimentos_planejados = load_planned_moves(client_dir, mes)
    goal_alloc = build_goal_allocation(df_m0, map_df)
    goals = evaluate_goals(config.get("objetivos", []), pos["por_classe"], pos["total"], goal_alloc)
    sug = suggest_monthly_investment(goals, aporte_mensal)
    unmapped_assets = find_unmapped_assets(df_m0, map_df)
    macro = load_macro_commentary(macro_file)

    payload = {
        "cliente_nome": config.get("cliente", {}).get("nome", cliente_id),
        "mes": mes,
        "posicao": pos,
        "mom": mom,
        "mom_linhas": mom_linhas,
        "compras_vendas": resumo_compras_vendas,
        "recomendacoes_fii": recomendacoes_fii,
        "recomendacoes_acoes": recomendacoes_acoes,
        "objetivos": goals,
        "ativos_nao_mapeados": unmapped_assets,
        "rentabilidade": rent,
        "fluxos_extrato": fluxos_extrato,
        "historico_fluxos": historico_fluxos,
        "movimentos_planejados": movimentos_planejados,
        "sugestoes": sug,
        "macro": macro,
    }

    template_dir = root / "app" / "reporting" / "templates"
    render_report(template_dir, output_file, payload)
    return output_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Gerador de relatorio financeiro mensal.")
    parser.add_argument("--cliente", required=True, help="ID do cliente, ex: gabriel")
    parser.add_argument("--mes", required=True, help="Mes de referencia no formato YYYY-MM")
    parser.add_argument(
        "--aporte-mensal",
        type=float,
        default=5000.0,
        help="Valor mensal para sugestao de investimento",
    )
    args = parser.parse_args()

    out = run(args.cliente, args.mes, args.aporte_mensal)
    print(f"Relatorio gerado em: {out}")


if __name__ == "__main__":
    main()
