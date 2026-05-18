from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from reporting.view_model import build_report_view_model


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
    reporting_dir = template_dir.parent
    css_file = reporting_dir / "static" / "report.css"
    template_payload = {
        **payload,
        "view": build_report_view_model(payload),
        "report_css": css_file.read_text(encoding="utf-8") if css_file.exists() else "",
    }
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["brl"] = _currency
    env.filters["pct"] = _percent
    template = env.get_template("report.html.j2")
    html = template.render(**template_payload)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")
