from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

from core.goals import build_goal_allocation, evaluate_goals, find_unmapped_assets
from core.classification import CLASSES_EXTERIOR, classify_positions
from core.metrics import (
    build_fii_recommendation_actions,
    build_mom_table_rows,
    build_stock_recommendation_actions,
    build_trade_rows,
    classify_cashflows,
    classify_dividends_usd,
    classify_external_flows,
    current_position,
    mom_variation,
    portfolio_return,
    summarize_trade_rows,
)
from ingest.loader import load_month_inputs
from ingest.normalizer import normalize_extrato, normalize_position
from reporting.html_report import render_report
from reporting.palette import (
    BRASIL_COLOR,
    CATEGORICAL_PALETTE,
    EXTERIOR_COLOR,
    OUTROS_ATIVOS_LABEL,
    OUTROS_COLOR,
    TOP_N_ATIVOS,
)

OUTROS_ATIVO_LABEL = "Outros / não identificado"


def _iter_month_dirs(client_dir: Path, mes_limite: str):
    inputs_dir = client_dir / "inputs"
    if not inputs_dir.exists():
        return
    for month_dir in sorted(inputs_dir.iterdir(), key=lambda p: p.name):
        if not month_dir.is_dir() or month_dir.name == "_templates" or month_dir.name > mes_limite:
            continue
        yield month_dir


def _br_income_events(client_dir: Path, mes_limite: str) -> list[dict]:
    """Eventos de ganho/perda do extrato BR (dividendos, proventos, juros, JCP,
    taxas e impostos), revarrendo todos os meses e deduplicando por
    (data, descricao, valor) — os extratos da XP cobrem ~90 dias e se
    sobrepoem entre pastas de mes consecutivas."""
    events_by_key: dict[tuple, dict] = {}
    for month_dir in _iter_month_dirs(client_dir, mes_limite):
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
    return list(events_by_key.values())


def _usd_dividend_events(client_dir: Path, mes_limite: str) -> list[dict]:
    """Eventos de dividendo em USD da XP International, revarrendo todos os
    meses. Cada PDF cobre exatamente um mes civil sem sobreposicao, entao nao
    precisa de dedupe (diferente do extrato BR)."""
    events: list[dict] = []
    for month_dir in _iter_month_dirs(client_dir, mes_limite):
        raw = load_month_inputs(month_dir)
        div = classify_dividends_usd(raw.get("dividendos_usd", pd.DataFrame()))
        events.extend(div["eventos"])
    return events


def _split_segments(delta_brasil: float, delta_exterior: float) -> tuple[list[dict], list[dict]]:
    """Separa as variacoes de Brasil/Exterior em segmentos positivos e negativos
    (magnitude sempre >= 0) para o grafico de barras empilhadas bidirecional,
    mantendo a ordem fixa Brasil -> Exterior dentro de cada lado."""
    positives, negatives = [], []
    for key, color, delta in (("Brasil", BRASIL_COLOR, delta_brasil), ("Exterior", EXTERIOR_COLOR, delta_exterior)):
        if delta > 0:
            positives.append({"key": key, "valor": delta, "color": color})
        elif delta < 0:
            negatives.append({"key": key, "valor": abs(delta), "color": color})
    return positives, negatives


def build_patrimonio_history(client_dir: Path, mes_limite: str, cliente_id: str, rules_file: Path) -> dict:
    """Evolucao do patrimonio total mes a mes, revarrendo inputs/<mes>/ (mesmo
    padrao usado para o historico de dividendos) e somando a posicao M0 de
    cada mes. Tambem quebra a variacao de cada mes por origem (Brasil vs
    Exterior) para o grafico de barras empilhadas."""
    totals: dict[str, float] = {}
    exterior_totals: dict[str, float] = {}
    for month_dir in _iter_month_dirs(client_dir, mes_limite):
        raw = load_month_inputs(month_dir)
        df_m0_mes = normalize_position(raw["m0"], cliente_id)
        df_m0_mes = classify_positions(df_m0_mes, rules_file)
        if df_m0_mes.empty:
            continue
        class_col = "classe_macro" if "classe_macro" in df_m0_mes.columns else "classe_ativo"
        totals[month_dir.name] = float(df_m0_mes["valor_total"].sum())
        exterior_totals[month_dir.name] = float(
            df_m0_mes.loc[df_m0_mes[class_col].isin(CLASSES_EXTERIOR), "valor_total"].sum()
        )

    por_mes = [{"mes": mes, "total": totals[mes]} for mes in sorted(totals)]
    variacao_por_mes = []
    for i in range(1, len(por_mes)):
        mes = por_mes[i]["mes"]
        mes_anterior = por_mes[i - 1]["mes"]
        exterior_atual = exterior_totals.get(mes, 0.0)
        exterior_anterior = exterior_totals.get(mes_anterior, 0.0)
        delta_exterior = exterior_atual - exterior_anterior
        delta_total = por_mes[i]["total"] - por_mes[i - 1]["total"]
        delta_brasil = delta_total - delta_exterior
        positive_segments, negative_segments = _split_segments(delta_brasil, delta_exterior)
        variacao_por_mes.append(
            {
                "mes": mes,
                "variacao": delta_total,
                "positive_segments": positive_segments,
                "negative_segments": negative_segments,
            }
        )
    max_abs = max([abs(float(row["variacao"])) for row in variacao_por_mes] + [1.0])

    net_exterior = (
        exterior_totals.get(por_mes[-1]["mes"], 0.0) - exterior_totals.get(por_mes[0]["mes"], 0.0) if por_mes else 0.0
    )
    net_total = (por_mes[-1]["total"] - por_mes[0]["total"]) if por_mes else 0.0
    net_brasil = net_total - net_exterior

    return {
        "por_mes": por_mes,
        "variacao_por_mes": variacao_por_mes,
        "max_abs_mensal": float(max_abs),
        "patrimonio_inicial": por_mes[0]["total"] if por_mes else 0.0,
        "patrimonio_final": por_mes[-1]["total"] if por_mes else 0.0,
        "legend": [
            {"key": "Brasil", "color": BRASIL_COLOR, "valor": net_brasil},
            {"key": "Exterior", "color": EXTERIOR_COLOR, "valor": net_exterior},
        ],
    }


def build_dividend_summary(client_dir: Path, mes: str, fluxos_extrato_mes: dict, dividendos_usd_mes: dict) -> dict:
    """Consolida dividendos/proventos do Brasil (extrato XP) e do Exterior (XP
    International) numa unica visao, convertendo USD->BRL pela cotacao que o
    proprio usuario informou em cada mes (valor_brl ja gravado por evento).
    Os agregados "por carteira"/"por ativo" e o grafico mensal cobrem todo o
    historico disponivel; a tabela de eventos fica restrita ao mes do relatorio.
    """
    br_eventos = [e for e in _br_income_events(client_dir, mes) if float(e.get("valor", 0.0)) > 0]
    usd_eventos = _usd_dividend_events(client_dir, mes)

    def _ativo_de(evento: dict, default_label: str) -> str:
        ativo = str(evento.get("ativo") or "-")
        return default_label if ativo == "-" else ativo

    # Ranking cumulativo por ativo (para decidir quais entram nos 8 slots de cor
    # da paleta categorica; o resto cai no bucket cinza "Outros ativos").
    por_ativo_totais: dict[str, float] = {}
    for e in br_eventos:
        ativo = _ativo_de(e, OUTROS_ATIVO_LABEL)
        por_ativo_totais[ativo] = por_ativo_totais.get(ativo, 0.0) + float(e["valor"])
    for e in usd_eventos:
        ativo = _ativo_de(e, OUTROS_ATIVO_LABEL)
        por_ativo_totais[ativo] = por_ativo_totais.get(ativo, 0.0) + float(e.get("valor_brl", 0.0))

    ranked_ativos = sorted(por_ativo_totais, key=lambda k: por_ativo_totais[k], reverse=True)
    top_ativos = ranked_ativos[:TOP_N_ATIVOS]
    ativo_color = {ativo: CATEGORICAL_PALETTE[i] for i, ativo in enumerate(top_ativos)}

    def _bucket_ativo(ativo: str) -> str:
        return ativo if ativo in ativo_color else OUTROS_ATIVOS_LABEL

    def _cor_ativo(bucket: str) -> str:
        return ativo_color.get(bucket, OUTROS_COLOR)

    # Historico mensal: total simples ("sem agrupamento"), por origem (Brasil/
    # Exterior) e por ativo (bucketado nos 8 slots de cor + "Outros ativos"),
    # todos empilhados a partir da mesma escala (max_abs_mensal).
    mensal: dict[str, float] = {}
    mensal_origem: dict[str, dict[str, float]] = {}
    mensal_ativo: dict[str, dict[str, float]] = {}
    for eventos, origem, valor_key in ((br_eventos, "Brasil", "valor"), (usd_eventos, "Exterior", "valor_brl")):
        for e in eventos:
            m = str(e.get("data", ""))[:7]
            if not m:
                continue
            valor = float(e.get(valor_key, 0.0))
            mensal[m] = mensal.get(m, 0.0) + valor
            origem_mes = mensal_origem.setdefault(m, {"Brasil": 0.0, "Exterior": 0.0})
            origem_mes[origem] += valor
            bucket = _bucket_ativo(_ativo_de(e, OUTROS_ATIVO_LABEL))
            ativo_mes = mensal_ativo.setdefault(m, {})
            ativo_mes[bucket] = ativo_mes.get(bucket, 0.0) + valor

    historico_mensal = [{"mes": m, "total_brl": mensal[m]} for m in sorted(mensal)]
    max_abs_mensal = max([abs(v) for v in mensal.values()] + [1.0])

    historico_mensal_origem = []
    for m in sorted(mensal_origem):
        valores = mensal_origem[m]
        segments = [
            {"key": k, "valor": valores[k], "color": BRASIL_COLOR if k == "Brasil" else EXTERIOR_COLOR}
            for k in ("Brasil", "Exterior")
            if valores.get(k, 0.0) > 0
        ]
        historico_mensal_origem.append(
            {"mes": m, "total_brl": mensal[m], "positive_segments": segments, "negative_segments": []}
        )

    historico_mensal_ativo = []
    for m in sorted(mensal_ativo):
        valores = mensal_ativo[m]
        ordered_keys = [a for a in top_ativos if valores.get(a, 0.0) > 0]
        if valores.get(OUTROS_ATIVOS_LABEL, 0.0) > 0:
            ordered_keys.append(OUTROS_ATIVOS_LABEL)
        segments = [{"key": k, "valor": valores[k], "color": _cor_ativo(k)} for k in ordered_keys]
        historico_mensal_ativo.append(
            {"mes": m, "total_brl": mensal[m], "positive_segments": segments, "negative_segments": []}
        )

    total_brasil = sum(float(e["valor"]) for e in br_eventos)
    total_exterior = sum(float(e.get("valor_brl", 0.0)) for e in usd_eventos)
    por_carteira = [
        {"carteira": "Brasil", "valor": total_brasil, "color": BRASIL_COLOR},
        {"carteira": "Exterior", "valor": total_exterior, "color": EXTERIOR_COLOR},
    ]

    por_ativo_bucketed: dict[str, float] = {}
    for ativo, valor in por_ativo_totais.items():
        bucket = _bucket_ativo(ativo)
        por_ativo_bucketed[bucket] = por_ativo_bucketed.get(bucket, 0.0) + valor
    por_ativo = sorted(
        [{"ativo": k, "valor": v, "color": _cor_ativo(k)} for k, v in por_ativo_bucketed.items()],
        key=lambda r: r["valor"],
        reverse=True,
    )

    eventos_mes = []
    for e in fluxos_extrato_mes.get("eventos", []):
        if e.get("tipo") != "Ganho":
            continue
        eventos_mes.append(
            {
                "data": e.get("data", ""),
                "ativo": e.get("ativo", "-"),
                "descricao": e.get("descricao", ""),
                "origem": "Brasil",
                "valor_brl": float(e.get("valor", 0.0)),
            }
        )
    for e in dividendos_usd_mes.get("eventos", []):
        eventos_mes.append(
            {
                "data": e.get("data", ""),
                "ativo": e.get("ativo", "-"),
                "descricao": e.get("descricao", ""),
                "origem": "Exterior",
                "valor_brl": float(e.get("valor_brl", 0.0)),
            }
        )
    eventos_mes.sort(key=lambda e: str(e["data"]), reverse=True)

    return {
        "mes_total_brl": sum(e["valor_brl"] for e in eventos_mes),
        "acumulado_brl": total_brasil + total_exterior,
        "historico_mensal": historico_mensal,
        "historico_mensal_origem": historico_mensal_origem,
        "historico_mensal_ativo": historico_mensal_ativo,
        "max_abs_mensal": float(max_abs_mensal),
        "por_carteira": por_carteira,
        "por_ativo": por_ativo,
        "eventos_mes": eventos_mes,
    }


def run(cliente_id: str, mes: str, aporte_mensal: float) -> Path:
    root = Path(__file__).resolve().parents[1]
    client_dir = root / "clientes" / cliente_id
    input_dir = client_dir / "inputs" / mes
    output_file = client_dir / "outputs" / mes / "relatorio.html"
    objetivos_file = client_dir / "objetivos.yaml"
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
    recomendacoes_fii = build_fii_recommendation_actions(
        df_m0, raw.get("fii_recommendations", pd.DataFrame()), raw.get("fii_recommendation_files_found", False)
    )
    recomendacoes_acoes = build_stock_recommendation_actions(
        df_m0, raw.get("stock_recommendations", pd.DataFrame()), raw.get("stock_recommendation_files_found", False)
    )
    if "data" in df_extrato.columns:
        df_extrato_mes = df_extrato[df_extrato["data"].astype(str).str.startswith(mes)]
    else:
        df_extrato_mes = df_extrato
    fluxos_extrato = classify_cashflows(df_extrato_mes)
    fluxos_externos = classify_external_flows(df_extrato_mes)
    base_total_m1 = pos["total"] - mom["variacao_total"]
    rent = portfolio_return(mom["variacao_total"], fluxos_externos["aporte_liquido_externo"], base_total_m1)
    historico_patrimonio = build_patrimonio_history(client_dir, mes, cliente_id, rules_file)
    dividendos_usd_mes = classify_dividends_usd(raw.get("dividendos_usd", pd.DataFrame()))
    dividendos = build_dividend_summary(client_dir, mes, fluxos_extrato, dividendos_usd_mes)
    goal_alloc = build_goal_allocation(df_m0, map_df)
    goals = evaluate_goals(config.get("objetivos", []), pos["por_classe"], pos["total"], goal_alloc)
    unmapped_assets = find_unmapped_assets(df_m0, map_df)

    payload = {
        "cliente_id": cliente_id,
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
        "fluxos_externos": fluxos_externos,
        "historico_patrimonio": historico_patrimonio,
        "dividendos": dividendos,
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
        help="Aporte mensal do mes (informativo, registrado no setup)",
    )
    args = parser.parse_args()

    out = run(args.cliente, args.mes, args.aporte_mensal)
    print(f"Relatorio gerado em: {out}")


if __name__ == "__main__":
    main()
