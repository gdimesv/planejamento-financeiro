from __future__ import annotations

from dataclasses import dataclass

from pipeline.state import MonthState, StepStatus


@dataclass
class GateResult:
    ready: bool
    blocking: list[str]
    warnings: list[str]


def evaluate_gate(state: MonthState) -> GateResult:
    """Decide se o relatorio pode ser gerado.

    Bloqueia apenas em etapas obrigatorias pendentes (posicao e extrato da XP).
    Etapas opcionais pendentes/atencao viram avisos, nao travam o relatorio.
    """
    blocking: list[str] = []
    warnings: list[str] = []

    for step in state.steps:
        if step.status == StepStatus.OK:
            continue
        message = f"{step.label}: {step.detail}" if step.detail else step.label
        if step.required and step.status == StepStatus.PENDING:
            blocking.append(message)
        else:
            warnings.append(message)

    return GateResult(ready=not blocking, blocking=blocking, warnings=warnings)
