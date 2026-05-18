from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape


def _format_pt_br_number(value: float | int | str) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "0,00"
    formatted = f"{num:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _currency(value: float | int | str) -> str:
    return f"R$ {_format_pt_br_number(value)}"


def _percent(value: float | int | str) -> str:
    return f"{_format_pt_br_number(value)}%"


def render_report(template_dir: Path, output_file: Path, payload: dict) -> None:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["brl"] = _currency
    env.filters["pct"] = _percent
    template = env.get_template("report.html.j2")
    html = template.render(**payload)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")
