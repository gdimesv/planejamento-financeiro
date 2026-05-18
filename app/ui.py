from __future__ import annotations

from pathlib import Path
from typing import List

import pandas as pd
import streamlit as st
import yaml
import streamlit.components.v1 as components

from core.classification import classify_positions
from ingest.loader import load_month_inputs, month_previous
from ingest.normalizer import normalize_position
from main import run as run_report


ROOT = Path(__file__).resolve().parents[1]
CLIENTES_DIR = ROOT / "clientes"


def list_clientes() -> List[str]:
    if not CLIENTES_DIR.exists():
        return []
    return sorted([p.name for p in CLIENTES_DIR.iterdir() if p.is_dir()])


def objetivos_file(cliente_id: str) -> Path:
    return CLIENTES_DIR / cliente_id / "objetivos.yaml"


def allocation_file(cliente_id: str) -> Path:
    return CLIENTES_DIR / cliente_id / "config" / "asset_objective_map.csv"


def planned_moves_file(cliente_id: str, mes: str) -> Path:
    return CLIENTES_DIR / cliente_id / "planos" / mes / "movimentos.md"


def load_planned_moves(cliente_id: str, mes: str) -> str:
    path = planned_moves_file(cliente_id, mes)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def save_planned_moves(cliente_id: str, mes: str, content: str) -> Path:
    path = planned_moves_file(cliente_id, mes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + ("\n" if content.strip() else ""), encoding="utf-8")
    return path


def load_objetivos(cliente_id: str) -> dict:
    path = objetivos_file(cliente_id)
    if not path.exists():
        return {"cliente": {"id": cliente_id, "nome": cliente_id.title()}, "objetivos": []}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"cliente": {"id": cliente_id, "nome": cliente_id.title()}, "objetivos": []}


def save_objetivos(cliente_id: str, data: dict) -> None:
    path = objetivos_file(cliente_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def load_asset_map(cliente_id: str) -> pd.DataFrame:
    path = allocation_file(cliente_id)
    if not path.exists():
        return pd.DataFrame(columns=["ativo", "objetivo_id", "peso"])
    df = pd.read_csv(path, dtype={"ativo": str, "objetivo_id": str, "peso": float})
    for col in ["ativo", "objetivo_id", "peso"]:
        if col not in df.columns:
            df[col] = None
    return df[["ativo", "objetivo_id", "peso"]]


def save_asset_map(cliente_id: str, df: pd.DataFrame) -> None:
    path = allocation_file(cliente_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    out = out.dropna(subset=["ativo", "objetivo_id"])
    out["ativo"] = out["ativo"].astype(str).str.strip()
    out["objetivo_id"] = out["objetivo_id"].astype(str).str.strip()
    out["peso"] = pd.to_numeric(out["peso"], errors="coerce").fillna(1.0)
    out = out[(out["ativo"] != "") & (out["objetivo_id"] != "")]
    out.to_csv(path, index=False, encoding="utf-8")


def load_ativos_mes(cliente_id: str, mes: str) -> pd.DataFrame:
    base = CLIENTES_DIR / cliente_id / "inputs" / mes
    if not base.exists():
        return pd.DataFrame(columns=["ativo", "classe_macro", "valor_total"])

    raw = load_month_inputs(base)
    df_m0 = normalize_position(raw["m0"], cliente_id)
    rules_file = ROOT / "data" / "mapping" / "fundos_rules.yaml"
    df_m0 = classify_positions(df_m0, rules_file)

    if df_m0.empty:
        return pd.DataFrame(columns=["ativo", "classe_macro", "valor_total"])

    resumo = (
        df_m0.groupby(["ativo", "classe_macro"], dropna=False)["valor_total"]
        .sum()
        .reset_index()
        .sort_values("valor_total", ascending=False)
    )
    return resumo


def list_meses(cliente_id: str) -> List[str]:
    meses_dir = CLIENTES_DIR / cliente_id / "inputs"
    if not meses_dir.exists():
        return []
    return sorted([p.name for p in meses_dir.iterdir() if p.is_dir() and p.name != "_templates"], reverse=True)


def month_input_dir(cliente_id: str, mes: str) -> Path:
    return CLIENTES_DIR / cliente_id / "inputs" / mes


def validate_month_files(cliente_id: str, mes: str) -> dict:
    """
    Minimo na pasta do mes atual: extrato + posicao (m0).
    MoM usa automaticamente a pasta do mes anterior (arquivos m0 daquele mes).
    """
    base = month_input_dir(cliente_id, mes)
    prev_mes = month_previous(mes)
    prev = month_input_dir(cliente_id, prev_mes)

    if not base.exists():
        return {
            "found": [],
            "missing_groups": ["extrato", "m0"],
            "prev_mes": prev_mes,
            "mom_ok": False,
            "mom_hint": "",
            "has_fii_recommendation": False,
        }

    files = [p.name for p in base.glob("*") if p.is_file()]
    prev_files = [p.name for p in prev.glob("*") if p.is_file()] if prev.exists() else []

    has_extrato = any("extrato" in n.lower() for n in files)
    has_m0 = any("m0" in n.lower() for n in files)
    has_fii_recommendation = any(
        "fii" in n.lower() and ("recomend" in n.lower() or "carteira" in n.lower())
        for n in files
    )
    missing = []
    if not has_extrato:
        missing.append("extrato")
    if not has_m0:
        missing.append("m0")

    # MoM: mes anterior com snapshot (m0) ou legado m1 na pasta atual
    mom_from_prev = prev.exists() and any(
        "m0" in n.lower() or "m1" in n.lower() for n in prev_files
    )
    mom_legacy_current = any("m1" in n.lower() for n in files)
    mom_ok = mom_from_prev or mom_legacy_current

    hint = ""
    if not mom_ok:
        hint = (
            f"Nenhuma base para MoM: crie a pasta {prev_mes} com os arquivos de posicao "
            f"(m0) daquele mes, ou use arquivos m1 na pasta {mes} (modo legado)."
        )
    elif mom_legacy_current and not mom_from_prev:
        hint = "MoM usando arquivos m1 na pasta atual (legado). O ideal e ter apenas m0 em cada mes e a pasta do mes anterior."

    return {
        "found": files,
        "missing_groups": missing,
        "prev_mes": prev_mes,
        "mom_ok": mom_ok,
        "mom_hint": hint,
        "has_fii_recommendation": has_fii_recommendation,
    }


def upload_tab(cliente_id: str) -> None:
    st.subheader("Upload mensal de arquivos")
    meses = list_meses(cliente_id)
    default_mes = meses[0] if meses else "2026-04"
    mes = st.text_input("Mes de referencia (YYYY-MM)", value=default_mes)
    target_dir = month_input_dir(cliente_id, mes)
    target_dir.mkdir(parents=True, exist_ok=True)

    uploads = st.file_uploader(
        "Arquivos do mes atual: extrato, posicoes (m0) e carteira recomendada de FIIs. O MoM usa sozinho a pasta do mes anterior.",
        accept_multiple_files=True,
        type=["csv", "xlsx", "xls"],
    )
    if st.button("Salvar uploads no mes selecionado", type="primary"):
        if not uploads:
            st.warning("Nenhum arquivo selecionado.")
        else:
            saved = []
            for up in uploads:
                out = target_dir / up.name
                out.write_bytes(up.getbuffer())
                saved.append(up.name)
            st.success(f"{len(saved)} arquivo(s) salvo(s) em {target_dir}.")

    check = validate_month_files(cliente_id, mes)
    st.markdown("**Arquivos encontrados:**")
    if check["found"]:
        st.write(sorted(check["found"]))
    else:
        st.info("Sem arquivos ainda para este mes.")

    prev_mes = check.get("prev_mes", "")
    st.caption(
        f"Para variacao MoM, o sistema le a posicao do mes anterior em `inputs/{prev_mes}/` "
        f"(arquivos com **m0** guardados naquele mes). Nao e necessario enviar m1 na pasta atual."
    )
    if check["missing_groups"]:
        st.warning(f"Pendencias na pasta do mes: {', '.join(check['missing_groups'])}")
    else:
        st.success("Arquivos minimos OK na pasta do mes: extrato e m0.")
    if check.get("has_fii_recommendation"):
        st.success("Carteira recomendada de FIIs encontrada para este mes.")
    else:
        st.info("Carteira recomendada de FIIs nao encontrada. O relatorio sera gerado sem essa analise.")
    if not check.get("mom_ok", True):
        st.warning(check.get("mom_hint") or "MoM pode ficar incompleto.")
    elif check.get("mom_hint"):
        st.info(check["mom_hint"])


def objetivos_tab(cliente_id: str) -> None:
    st.subheader("Objetivos por cliente")
    data = load_objetivos(cliente_id)

    col_a, col_b = st.columns(2)
    nome = col_a.text_input("Nome do cliente", value=data.get("cliente", {}).get("nome", cliente_id.title()))
    aporte_default = col_b.number_input("Aporte mensal padrao (opcional)", min_value=0.0, value=float(data.get("aporte_mensal_padrao", 0.0)))

    objetivos = data.get("objetivos", [])
    objetivos_df = pd.DataFrame(objetivos)
    if objetivos_df.empty:
        objetivos_df = pd.DataFrame(
            [
                {
                    "id": "caixa_120k",
                    "descricao": "120K Caixa",
                    "tipo": "valor_alvo",
                    "valor_alvo": 120000.0,
                    "prazo_meses": None,
                    "prioridade": "alta",
                }
            ]
        )

    edited = st.data_editor(
        objetivos_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "id": st.column_config.TextColumn("ID"),
            "descricao": st.column_config.TextColumn("Descricao"),
            "tipo": st.column_config.SelectboxColumn("Tipo", options=["valor_alvo", "renda_passiva_mensal", "valor_presente"]),
            "valor_alvo": st.column_config.NumberColumn("Valor alvo", min_value=0.0, step=1000.0),
            "prazo_meses": st.column_config.NumberColumn("Prazo (meses)", min_value=0, step=1),
            "prioridade": st.column_config.SelectboxColumn("Prioridade", options=["alta", "media", "baixa"]),
        },
        key=f"objetivos_editor_{cliente_id}",
    )

    if st.button("Salvar objetivos", type="primary"):
        payload = {
            "cliente": {"id": cliente_id, "nome": nome},
            "aporte_mensal_padrao": float(aporte_default),
            "objetivos": edited.replace({pd.NA: None}).to_dict(orient="records"),
        }
        save_objetivos(cliente_id, payload)
        st.success("Objetivos salvos com sucesso.")


def classificacao_tab(cliente_id: str) -> None:
    st.subheader("Classificacao de ativos por objetivo")
    meses = list_meses(cliente_id)
    mes = st.selectbox("Mes de referencia (para listar ativos)", options=meses, index=0 if meses else None)

    objetivos = load_objetivos(cliente_id).get("objetivos", [])
    objetivo_ids = [o.get("id", "") for o in objetivos if o.get("id")]
    if not objetivo_ids:
        st.warning("Cadastre objetivos antes de mapear ativos.")
        return

    ativos_df = load_ativos_mes(cliente_id, mes) if mes else pd.DataFrame(columns=["ativo", "classe_macro", "valor_total"])
    mapa_df = load_asset_map(cliente_id)

    if not ativos_df.empty:
        merged = ativos_df.merge(mapa_df, how="left", on="ativo")
    else:
        merged = mapa_df.copy()
        if "classe_macro" not in merged.columns:
            merged["classe_macro"] = ""
        if "valor_total" not in merged.columns:
            merged["valor_total"] = 0.0

    if "peso" not in merged.columns:
        merged["peso"] = 1.0
    merged["peso"] = pd.to_numeric(merged["peso"], errors="coerce").fillna(1.0)
    mostrar_somente_novos = st.checkbox("Mostrar apenas ativos novos sem mapeamento", value=True)
    if mostrar_somente_novos:
        merged = merged[merged["objetivo_id"].isna() | (merged["objetivo_id"].astype(str).str.strip() == "")]

    edited = st.data_editor(
        merged[["ativo", "classe_macro", "valor_total", "objetivo_id", "peso"]],
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "ativo": st.column_config.TextColumn("Ativo", disabled=True),
            "classe_macro": st.column_config.TextColumn("Classe", disabled=True),
            "valor_total": st.column_config.NumberColumn("Valor M0", disabled=True, format="%.2f"),
            "objetivo_id": st.column_config.SelectboxColumn("Objetivo", options=objetivo_ids),
            "peso": st.column_config.NumberColumn("Peso", min_value=0.0, max_value=1.0, step=0.1),
        },
        key=f"mapa_editor_{cliente_id}",
    )

    st.caption("Peso permite dividir um ativo entre objetivos (ex.: 0.7 / 0.3).")
    if st.button("Salvar classificacao de ativos", type="primary"):
        edited_map = edited[["ativo", "objetivo_id", "peso"]].copy()
        if mostrar_somente_novos and not mapa_df.empty:
            edited_assets = set(edited_map["ativo"].astype(str))
            existing = mapa_df[~mapa_df["ativo"].astype(str).isin(edited_assets)]
            edited_map = pd.concat([existing, edited_map], ignore_index=True, sort=False)
        save_asset_map(cliente_id, edited_map)
        st.success("Classificacao salva com sucesso.")


def relatorio_tab(cliente_id: str) -> None:
    st.subheader("Geracao e visualizacao do relatorio")
    meses = list_meses(cliente_id)
    if not meses:
        st.warning("Nenhum mes encontrado. Faca upload dos arquivos primeiro.")
        return
    mes = st.selectbox("Mes do relatorio", options=meses, index=0)
    objetivos_cfg = load_objetivos(cliente_id)
    aporte_default = float(objetivos_cfg.get("aporte_mensal_padrao", 0.0) or 0.0)
    aporte = st.number_input("Aporte mensal para simulacao", min_value=0.0, value=aporte_default, step=500.0)
    movimentos_planejados = st.text_area(
        "Movimentos planejados para o mes",
        value=load_planned_moves(cliente_id, mes),
        height=180,
        placeholder="Vender X acoes de PETR4\nComprar X acoes de ITSA4",
        key=f"movimentos_planejados_{cliente_id}_{mes}",
    )
    if st.button("Salvar movimentos planejados"):
        path = save_planned_moves(cliente_id, mes, movimentos_planejados)
        st.success(f"Movimentos salvos em: {path}")

    check = validate_month_files(cliente_id, mes)
    if check["missing_groups"]:
        st.error(f"Faltam arquivos para gerar relatorio: {', '.join(check['missing_groups'])}")
        return
    if not check.get("mom_ok", True):
        st.warning(
            f"MoM sem base no mes anterior (`inputs/{check.get('prev_mes', '')}/`). "
            "O relatorio sera gerado, mas a secao de variacao MoM pode ficar vazia ou incompleta."
        )

    if st.button("Gerar relatorio agora", type="primary"):
        out = run_report(cliente_id, mes, aporte)
        st.success(f"Relatorio gerado em: {out}")

    html_path = CLIENTES_DIR / cliente_id / "outputs" / mes / "relatorio.html"
    if html_path.exists():
        st.markdown("**Preview do relatorio**")
        html = html_path.read_text(encoding="utf-8")
        components.html(html, height=900, scrolling=True)
        st.download_button(
            "Baixar relatorio HTML",
            data=html.encode("utf-8"),
            file_name=f"relatorio_{cliente_id}_{mes}.html",
            mime="text/html",
        )


def main() -> None:
    st.set_page_config(page_title="Planejamento Financeiro", layout="wide")
    st.title("Planejamento Financeiro")

    clientes = list_clientes()
    if not clientes:
        st.error("Nenhum cliente encontrado em 'clientes/'.")
        return

    with st.sidebar:
        cliente_id = st.selectbox("Cliente", options=clientes)
    tab1, tab2, tab3, tab4 = st.tabs(
        ["Upload mensal", "Objetivos", "Classificação de ativos", "Relatório"]
    )
    with tab1:
        upload_tab(cliente_id)
    with tab2:
        objetivos_tab(cliente_id)
    with tab3:
        classificacao_tab(cliente_id)
    with tab4:
        relatorio_tab(cliente_id)


if __name__ == "__main__":
    main()
