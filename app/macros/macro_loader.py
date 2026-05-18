from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd


def load_macro_commentary(path: Path) -> List[dict]:
    if not path.exists():
        return []
    df = pd.read_csv(path)
    rows = []
    for _, row in df.iterrows():
        rows.append(
            {
                "indicador": str(row.get("indicador", "")),
                "valor": row.get("valor", ""),
                "comentario": str(row.get("comentario", "")),
            }
        )
    return rows
