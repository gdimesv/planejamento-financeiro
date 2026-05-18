# Arquitetura do app local

## Direção

O app deve separar claramente tres responsabilidades:

1. Motor financeiro em Python
   - Leitura e normalizacao de arquivos.
   - Classificacao de ativos.
   - Calculos de patrimonio, variacao, rentabilidade, objetivos e sugestoes.

2. Backoffice local em Streamlit
   - Upload mensal.
   - Cadastro de objetivos.
   - Classificacao de ativos por objetivo.
   - Registro de movimentos planejados.
   - Geracao e preview do relatorio.

3. Relatorio HTML como produto final
   - Experiencia visual polida.
   - Resumo executivo.
   - Plano de acao.
   - Diagnostico visual da carteira.
   - Tabelas detalhadas para auditoria.

## Implementacao atual

- `app/core/`: regras e metricas financeiras.
- `app/ingest/`: carregamento e normalizacao de inputs.
- `app/ui.py`: backoffice local em Streamlit.
- `app/reporting/view_model.py`: prepara dados de apresentacao para o relatorio.
- `app/reporting/templates/report.html.j2`: estrutura HTML do relatorio final.
- `app/reporting/static/report.css`: design system do relatorio.
- `app/reporting/html_report.py`: renderiza HTML standalone, embutindo CSS e payload visual.

## Regra de evolucao

Novas metricas devem nascer no `core`.

Novas decisoes de apresentacao devem entrar em `reporting/view_model.py`.

Novos estilos e componentes visuais do relatorio devem entrar em `reporting/static/report.css` e no template.

O Streamlit deve continuar focado em operacao local, nao em ser a experiencia final de leitura.

