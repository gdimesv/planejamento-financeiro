# Arquitetura do app local

## Direção

O app separa claramente quatro responsabilidades:

1. Motor financeiro em Python
   - Leitura e normalizacao de arquivos.
   - Classificacao de ativos.
   - Calculos de patrimonio, variacao, rentabilidade, objetivos e sugestoes.

2. Orquestracao do pipeline mensal
   - Deriva o estado do mes (o que ja foi coletado/preenchido) direto do sistema de arquivos, sem persistir estado a parte.
   - Decide o que e obrigatorio (gate) antes de liberar o relatorio.
   - Dispara os scrapers (XP, Suno) como subprocessos e salva a posicao internacional manual.

3. Backoffice local em FastAPI + HTMX
   - Setup mensal: coleta automatica, posicao internacional, movimentos planejados, diagnostico e geracao do relatorio.
   - Cadastro de objetivos e classificacao de ativos por objetivo.
   - Servido localmente (`uvicorn`), sem build de frontend.

4. Relatorio HTML como produto final
   - Experiencia visual polida.
   - Resumo executivo.
   - Plano de acao.
   - Diagnostico visual da carteira.
   - Tabelas detalhadas para auditoria.

## Implementacao atual

- `app/core/`: regras e metricas financeiras.
- `app/ingest/`: carregamento e normalizacao de inputs.
- `app/pipeline/`: estado do mes (`state.py`), gate de liberacao do relatorio (`gate.py`), orquestracao de scrapers e objetivos/classificacao (`orchestrator.py`, `goals.py`).
- `app/server/`: app FastAPI (`app.py`), jobs em background dos scrapers (`jobs.py`), templates Jinja2/HTMX (`templates/`) e CSS (`static/`).
- `app/main.py`: CLI para gerar o relatorio em lote/debug, sem depender do servidor.
- `app/reporting/view_model.py`: prepara dados de apresentacao para o relatorio.
- `app/reporting/templates/report.html.j2`: estrutura HTML do relatorio final.
- `app/reporting/static/report.css`: design system do relatorio.
- `app/reporting/html_report.py`: renderiza HTML standalone, embutindo CSS e payload visual.

## Regra de evolucao

Novas metricas devem nascer no `core`.

Novas decisoes de apresentacao devem entrar em `reporting/view_model.py`.

Novos estilos e componentes visuais do relatorio devem entrar em `reporting/static/report.css` e no template.

O app FastAPI/HTMX deve continuar focado em operacao local, nao em ser a experiencia final de leitura.

