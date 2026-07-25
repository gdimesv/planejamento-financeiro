from __future__ import annotations

import csv
import subprocess
from dataclasses import dataclass
from pathlib import Path

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


def save_internacional(cliente_id: str, mes: str, rows: list[dict]) -> Path:
    """Grava a posicao internacional manual no formato consumido pelo loader.

    Espera linhas com as chaves 'classe', 'ativo' e 'valor'. Gera
    inputs/<mes>/posicao_m0_xp_int_<mes>.csv com o cabecalho esperado.
    """
    base = month_input_dir(cliente_id, mes)
    base.mkdir(parents=True, exist_ok=True)
    dest = base / f"posicao_m0_xp_int_{mes}.csv"

    cleaned = [
        {
            "Classe": str(row.get("classe", "")).strip(),
            "Ativo": str(row.get("ativo", "")).strip(),
            "Valor Atual (R$)": row.get("valor", ""),
        }
        for row in rows
        if str(row.get("ativo", "")).strip()
    ]

    with dest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Classe", "Ativo", "Valor Atual (R$)"])
        writer.writeheader()
        writer.writerows(cleaned)
    return dest
