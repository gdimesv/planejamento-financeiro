from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permite rodar como `python app/pipeline/cli.py` a partir da raiz do projeto,
# garantindo que os modulos do motor (core, ingest, ...) estejam no path.
APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from pipeline.gate import evaluate_gate
from pipeline.orchestrator import run_scraper
from pipeline.state import StepStatus, compute_month_state


_ICON = {StepStatus.OK: "[ok]  ", StepStatus.WARN: "[!]   ", StepStatus.PENDING: "[ ]   "}


def cmd_status(args: argparse.Namespace) -> int:
    state = compute_month_state(args.cliente, args.mes)
    gate = evaluate_gate(state)

    print(f"Pipeline de {args.cliente} / {args.mes}\n")
    for step in state.steps:
        req = "obrigatorio" if step.required else "opcional"
        print(f"{_ICON[step.status]}{step.label}  ({req})")
        if step.detail:
            print(f"        {step.detail}")
        if step.files:
            print(f"        arquivos: {', '.join(step.files)}")
    print()
    if gate.ready:
        print("Relatorio: LIBERADO")
    else:
        print("Relatorio: BLOQUEADO")
        for reason in gate.blocking:
            print(f"  - {reason}")
    if gate.warnings:
        print("Avisos:")
        for warning in gate.warnings:
            print(f"  - {warning}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    result = run_scraper(args.kind, args.cliente, args.mes)
    print(result.output)
    print(f"\nColeta {args.kind}: {'OK' if result.ok else 'FALHOU'} (returncode={result.returncode})")
    return 0 if result.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspecao e disparo do pipeline mensal.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Mostra o estado do mes e o gate do relatorio.")
    p_status.add_argument("--cliente", required=True)
    p_status.add_argument("--mes", required=True, help="YYYY-MM")
    p_status.set_defaults(func=cmd_status)

    p_run = sub.add_parser("run", help="Dispara um coletor (xp, suno_fiis, suno_acoes).")
    p_run.add_argument("kind", choices=["xp", "suno_fiis", "suno_acoes"])
    p_run.add_argument("--cliente", required=True)
    p_run.add_argument("--mes", required=True, help="YYYY-MM")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
