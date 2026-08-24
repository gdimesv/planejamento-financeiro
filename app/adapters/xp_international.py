from __future__ import annotations

import re
from pathlib import Path
from typing import List

import pdfplumber


# Mapa curado para preservar os nomes ja usados em asset_objective_map.csv
# (continuidade do MoM e da classificacao de objetivos ao trocar do CSV manual
# para o PDF automatico). Simbolos fora deste mapa usam o proprio ticker como
# nome, mesma convencao ja usada para MCHI/WELL/PLD/EQIX/JPM/KWEB/KO/PG.
SYMBOL_TO_NOME = {
    "AAPL": "Apple",
    "GOOG": "Google",
    "GOOGL": "Google",
    "MELI": "Meli",
    "BRK.B": "Berkshire",
    "SPOT": "Spotify",
    "NVDA": "Nvidia",
    "AUR": "Aurora",
    "ABNB": "Airbnb",
    "MRAHZ": "Fundo Morgan",
    "MSFT": "Microsoft",
    "META": "Meta",
}

CLASSE_INTERNACIONAL = "Ações no Exterior"

_TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
_NUM_RE = r"-?[\d,]+\.\d+"

# Linha de posicao: "<descricao [simbolo]> <qtd> <emprestimo> <preco> <valor_mercado>
# <valor_mercado_anterior> <%variacao> <%do_total>"
_POSITION_LINE_RE = re.compile(
    rf"^(?P<prefix>.+?)\s+(?P<qtd>{_NUM_RE})\s+(?P<loan>\d+)\s+(?P<preco>{_NUM_RE})\s+"
    rf"(?P<valor>{_NUM_RE})\s+(?P<valor_prev>{_NUM_RE})\s+(?P<pct_change>{_NUM_RE})\s+"
    rf"(?P<pct_total>{_NUM_RE})$"
)

# Linha de nao-negociacao: "<data> <tipo> <descricao [simbolo]> <qtd> <valor> <taxa>"
_NON_TRADING_LINE_RE = re.compile(
    rf"^(?P<data>\d{{4}}-\d{{2}}-\d{{2}})\s+(?P<tipo>\S+)\s+(?P<prefix>.+?)\s+"
    rf"(?P<qtd>{_NUM_RE})\s+(?P<valor>{_NUM_RE})\s+(?P<taxa>{_NUM_RE})$"
)


def _parse_money(text: str) -> float:
    return float(text.replace(",", ""))


def _split_symbol(prefix: str) -> tuple[str, str]:
    """Separa 'DESCRICAO ... SIMBOLO' -> (descricao, simbolo). Sem simbolo (ex.: bonds), retorna ''."""
    words = prefix.strip().split()
    if words and _TICKER_RE.match(words[-1]):
        return " ".join(words[:-1]), words[-1]
    return prefix.strip(), ""


def _nome_ativo(descricao: str, simbolo: str) -> str:
    if simbolo:
        return SYMBOL_TO_NOME.get(simbolo, simbolo)
    if "TREASURY" in descricao.upper():
        return "Tesouro USA"
    return descricao.strip() or "Desconhecido"


def _extract_section(all_lines: List[str], start_markers: tuple[str, ...], end_markers: tuple[str, ...]) -> List[str]:
    """Concatena linhas entre a primeira ocorrencia de um start_marker e o end_marker seguinte."""
    lines: List[str] = []
    in_section = False
    for line in all_lines:
        stripped = line.strip()
        if not in_section and any(stripped.startswith(m) for m in start_markers):
            in_section = True
            continue
        if in_section and any(stripped.startswith(m) for m in end_markers):
            in_section = False
            continue
        if in_section:
            lines.append(stripped)
    return lines


def parse_positions(pdf: "pdfplumber.PDF") -> List[dict]:
    all_lines: List[str] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        all_lines.extend(text.split("\n"))

    section_lines = _extract_section(
        all_lines,
        start_markers=("Description Symbol Quantity",),
        end_markers=("Total ", "Total\t"),
    )
    # A linha de cabecalho de continuacao ("CUSIP Loan Market Value Portfolio")
    # e as proprias linhas de "Total" ja saem fora da secao; o resto sao linhas
    # de posicao (casam a regex) ou linhas de CUSIP/continuacao de descricao
    # (nao casam e sao ignoradas).
    positions: List[dict] = []
    for line in section_lines:
        match = _POSITION_LINE_RE.match(line)
        if not match:
            continue
        descricao, simbolo = _split_symbol(match.group("prefix"))
        valor_usd = _parse_money(match.group("valor"))
        if valor_usd <= 0:
            continue
        positions.append(
            {
                "ativo": _nome_ativo(descricao, simbolo),
                "simbolo": simbolo,
                "valor_usd": valor_usd,
            }
        )
    return positions


def parse_dividends(pdf: "pdfplumber.PDF") -> List[dict]:
    all_lines: List[str] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        all_lines.extend(text.split("\n"))

    section_lines = _extract_section(
        all_lines,
        start_markers=("NON-TRADING ACTIVITY",),
        end_markers=("Investment objectives", "Disclosures"),
    )

    dividends: List[dict] = []
    for line in section_lines:
        match = _NON_TRADING_LINE_RE.match(line)
        if not match or match.group("tipo") != "CASH_DIVIDEND":
            continue
        descricao, simbolo = _split_symbol(match.group("prefix"))
        valor_usd = _parse_money(match.group("valor"))
        dividends.append(
            {
                "data": match.group("data"),
                "ativo": _nome_ativo(descricao, simbolo),
                "simbolo": simbolo,
                "descricao": descricao.strip(),
                "valor_usd": valor_usd,
            }
        )
    return dividends


def parse_statement(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        return {
            "positions": parse_positions(pdf),
            "dividends": parse_dividends(pdf),
        }
