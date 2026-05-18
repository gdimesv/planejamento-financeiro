from __future__ import annotations

from math import ceil
from typing import Any


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _tone(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def _classes_only(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row.get("subclasse", "-")) == "-"]


def _format_delta_label(value: float, pct: float) -> str:
    signal = "+" if value > 0 else ""
    return f"{signal}{pct:.2f}%"


def _build_allocation_chart(posicao: dict) -> list[dict]:
    rows = _classes_only(list(posicao.get("alocacao_tabela", [])))
    chart = []
    for row in rows:
        pct = max(_num(row.get("representatividade_pct")), 0.0)
        chart.append(
            {
                "classe": row.get("classe", "-"),
                "valor": _num(row.get("m0")),
                "percentual": pct,
                "width": min(max(pct, 1.0), 100.0),
            }
        )
    return chart


def _build_variation_chart(posicao: dict) -> list[dict]:
    rows = _classes_only(list(posicao.get("alocacao_tabela", [])))
    max_abs = max([abs(_num(row.get("variacao"))) for row in rows] + [1.0])
    chart = []
    for row in sorted(rows, key=lambda item: abs(_num(item.get("variacao"))), reverse=True):
        value = _num(row.get("variacao"))
        pct = _num(row.get("variacao_pct"))
        chart.append(
            {
                "classe": row.get("classe", "-"),
                "valor": value,
                "percentual": pct,
                "width": min(max(abs(value) / max_abs * 100.0, 2.0), 100.0),
                "tone": _tone(value),
                "delta_label": _format_delta_label(value, pct),
            }
        )
    return chart


def _build_goal_cards(objetivos: list[dict], sugestoes: list[dict]) -> list[dict]:
    sugestao_por_objetivo = {
        str(row.get("objetivo_id")): _num(row.get("aporte_sugerido"))
        for row in sugestoes
    }
    cards = []
    for goal in objetivos:
        goal_id = str(goal.get("id"))
        progress = _num(goal.get("progresso_pct"))
        gap = _num(goal.get("gap"))
        aporte = sugestao_por_objetivo.get(goal_id, 0.0)
        cards.append(
            {
                **goal,
                "progresso_visual": min(max(progress, 0.0), 100.0),
                "aporte_sugerido": aporte,
                "meses_estimados": ceil(gap / aporte) if gap > 0 and aporte > 0 else None,
                "status": "Concluido" if gap <= 0 else "Em andamento",
            }
        )
    return sorted(cards, key=lambda row: (_num(row.get("gap")) <= 0, -_num(row.get("aporte_sugerido"))))


def _build_action_plan(sugestoes: list[dict], objetivos: list[dict]) -> list[dict]:
    goal_by_id = {str(goal.get("id")): goal for goal in objetivos}
    actions = []
    for row in sugestoes:
        goal = goal_by_id.get(str(row.get("objetivo_id")), {})
        gap = _num(goal.get("gap"))
        aporte = _num(row.get("aporte_sugerido"))
        impact = (aporte / gap * 100.0) if gap > 0 else 0.0
        actions.append(
            {
                **row,
                "gap": gap,
                "impacto_gap_pct": impact,
                "motivo": "Maior gap ponderado pela prioridade do objetivo.",
            }
        )
    return actions


def _build_insights(payload: dict, allocation_chart: list[dict], action_plan: list[dict]) -> list[dict]:
    mom = payload.get("mom", {})
    rent = payload.get("rentabilidade", {})
    fluxos = payload.get("fluxos_extrato", {})
    variacao_total = _num(mom.get("variacao_total"))
    variacao_pct = _num(mom.get("variacao_percentual"))
    resultado_mes = _num(rent.get("resultado_mes"))
    liquido_fluxos = _num(fluxos.get("liquido"))

    variation_rows = _build_variation_chart(payload.get("posicao", {}))
    best = next((row for row in variation_rows if row["valor"] > 0), None)
    worst = next((row for row in sorted(variation_rows, key=lambda item: item["valor"]) if row["valor"] < 0), None)

    insights = [
        {
            "label": "Status do mês",
            "title": "Patrimônio aumentou" if variacao_total > 0 else "Patrimônio recuou" if variacao_total < 0 else "Patrimônio estável",
            "detail": f"Variação mensal de {_format_delta_label(variacao_total, variacao_pct)} sobre a base comparável.",
            "tone": _tone(variacao_total),
        },
        {
            "label": "Resultado",
            "title": "Resultado positivo" if resultado_mes > 0 else "Resultado negativo" if resultado_mes < 0 else "Resultado neutro",
            "detail": "Rentabilidade estimada calculada a partir do resultado do extrato e patrimônio atual.",
            "tone": _tone(resultado_mes),
        },
        {
            "label": "Fluxos",
            "title": "Proventos líquidos positivos" if liquido_fluxos > 0 else "Custos superaram proventos" if liquido_fluxos < 0 else "Sem fluxo líquido relevante",
            "detail": "Dividendos, proventos, taxas e impostos identificados no extrato do mês.",
            "tone": _tone(liquido_fluxos),
        },
    ]

    if best:
        insights.append(
            {
                "label": "Maior alta",
                "title": str(best["classe"]),
                "detail": f"{best['delta_label']} no mês.",
                "tone": "positive",
            }
        )
    if worst:
        insights.append(
            {
                "label": "Maior queda",
                "title": str(worst["classe"]),
                "detail": f"{worst['delta_label']} no mês.",
                "tone": "negative",
            }
        )
    if action_plan:
        first = action_plan[0]
        insights.append(
            {
                "label": "Próxima ação",
                "title": str(first.get("descricao", "Aporte sugerido")),
                "detail": "Principal destino sugerido para o aporte mensal.",
                "tone": "neutral",
            }
        )
    elif allocation_chart:
        insights.append(
            {
                "label": "Concentração",
                "title": str(allocation_chart[0]["classe"]),
                "detail": "Maior classe na alocação atual.",
                "tone": "neutral",
            }
        )

    return insights


def build_report_view_model(payload: dict) -> dict:
    posicao = payload.get("posicao", {})
    mom = payload.get("mom", {})
    rent = payload.get("rentabilidade", {})
    fluxos = payload.get("fluxos_extrato", {})
    objetivos = list(payload.get("objetivos", []))
    sugestoes = list(payload.get("sugestoes", []))

    allocation_chart = _build_allocation_chart(posicao)
    variation_chart = _build_variation_chart(posicao)
    goal_cards = _build_goal_cards(objetivos, sugestoes)
    action_plan = _build_action_plan(sugestoes, objetivos)

    kpis = [
        {
            "label": "Patrimônio total",
            "value": _num(posicao.get("total")),
            "kind": "currency",
            "tone": "neutral",
            "context": "Mês atual",
        },
        {
            "label": "Variação mensal",
            "value": _num(mom.get("variacao_total")),
            "kind": "currency",
            "tone": _tone(_num(mom.get("variacao_total"))),
            "context_value": _num(mom.get("variacao_percentual")),
            "context_kind": "percent",
        },
        {
            "label": "Rentabilidade estimada",
            "value": _num(rent.get("rentabilidade_pct")),
            "kind": "percent",
            "tone": _tone(_num(rent.get("rentabilidade_pct"))),
            "context": "Com base no extrato",
        },
        {
            "label": "Caixa disponível",
            "value": _num(posicao.get("caixa")),
            "kind": "currency",
            "tone": "neutral",
            "context": "Saldo para decisões",
        },
        {
            "label": "Proventos líquidos",
            "value": _num(fluxos.get("liquido")),
            "kind": "currency",
            "tone": _tone(_num(fluxos.get("liquido"))),
            "context": "Ganhos menos custos",
        },
        {
            "label": "Aporte sugerido",
            "value": sum(_num(row.get("aporte_sugerido")) for row in sugestoes),
            "kind": "currency",
            "tone": "neutral",
            "context": "Distribuído por objetivo",
        },
    ]

    return {
        "kpis": kpis,
        "insights": _build_insights(payload, allocation_chart, action_plan),
        "allocation_chart": allocation_chart,
        "variation_chart": variation_chart,
        "goal_cards": goal_cards,
        "action_plan": action_plan,
    }
