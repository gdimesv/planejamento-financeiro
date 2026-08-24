from __future__ import annotations

import csv
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from adapters.xp_international import CLASSE_INTERNACIONAL, parse_statement
from pipeline.state import PROJECT_ROOT, month_input_dir


SCRAPERS: dict[str, Path] = {
    "xp": PROJECT_ROOT / "scripts" / "xp" / "run-xp.sh",
    "suno_fiis": PROJECT_ROOT / "scripts" / "suno-fiis" / "run-suno-fiis.sh",
    "suno_acoes": PROJECT_ROOT / "scripts" / "suno-acoes" / "run-suno-acoes.sh",
}


@dataclass
class ScraperResult:
    kind: str
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def scraper_command(kind: str, cliente_id: str, mes: str) -> list[str]:
    if kind not in SCRAPERS:
        raise ValueError(f"Coletor desconhecido: {kind!r}. Opcoes: {sorted(SCRAPERS)}")
    script = SCRAPERS[kind]
    return [str(script), "--cliente", cliente_id, "--mes", mes]


def run_scraper(kind: str, cliente_id: str, mes: str) -> ScraperResult:
    """Dispara um coletor (abre o browser para login manual) e aguarda o fim.

    Os scrapers da XP/Suno abrem um Chromium em modo nao-headless; o usuario faz
    o login na janela e o download acontece sozinho. Esta funcao bloqueia ate o
    processo terminar, capturando o log combinado.
    """
    cmd = scraper_command(kind, cliente_id, mes)
    proc = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    return ScraperResult(kind=kind, returncode=proc.returncode, output=proc.stdout + proc.stderr)


def save_internacional_from_pdf(cliente_id: str, mes: str, pdf_bytes: bytes, usd_brl_rate: float) -> dict:
    """Processa o extrato PDF da XP International e grava os arquivos do mes.

    Gera tres arquivos em inputs/<mes>/:
    - xp_int_original_<mes>.pdf: o PDF original, para auditoria/reprocessamento
      (nome sem "extrato"/"m0" de proposito, para nao ser confundido pelo
      loader com o extrato ou a posicao da XP Brasil).
    - posicao_m0_xp_int_<mes>.csv: posicoes convertidas para BRL, no formato
      ja consumido pelo loader (Classe,Ativo,Valor Atual (R$)).
    - dividendos_xp_int_<mes>.csv: dividendos pagos no mes, em USD e BRL.

    Retorna um resumo com as contagens extraidas, para exibir na UI.
    """
    base = month_input_dir(cliente_id, mes)
    base.mkdir(parents=True, exist_ok=True)

    pdf_path = base / f"xp_int_original_{mes}.pdf"
    pdf_path.write_bytes(pdf_bytes)

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        parsed = parse_statement(Path(tmp.name))

    posicao_path = base / f"posicao_m0_xp_int_{mes}.csv"
    with posicao_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Classe", "Ativo", "Valor Atual (R$)"])
        writer.writeheader()
        for pos in parsed["positions"]:
            writer.writerow(
                {
                    "Classe": CLASSE_INTERNACIONAL,
                    "Ativo": pos["ativo"],
                    "Valor Atual (R$)": f"{pos['valor_usd'] * usd_brl_rate:.2f}",
                }
            )

    dividendos_path = base / f"dividendos_xp_int_{mes}.csv"
    with dividendos_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["data", "ativo", "simbolo", "descricao", "valor_usd", "valor_brl", "cotacao_usd_brl"],
        )
        writer.writeheader()
        for div in parsed["dividends"]:
            writer.writerow(
                {
                    "data": div["data"],
                    "ativo": div["ativo"],
                    "simbolo": div["simbolo"],
                    "descricao": div["descricao"],
                    "valor_usd": f"{div['valor_usd']:.2f}",
                    "valor_brl": f"{div['valor_usd'] * usd_brl_rate:.2f}",
                    "cotacao_usd_brl": f"{usd_brl_rate:.4f}",
                }
            )

    return {
        "posicoes": len(parsed["positions"]),
        "dividendos": len(parsed["dividends"]),
    }
