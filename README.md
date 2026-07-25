# Planejamento Financeiro Local (V0)

App de planejamento financeiro que me ajuda a organizar minhas financas.

Aplicativo local em Python para gerar um relatorio mensal por cliente, com base em objetivos e arquivos de extrato/posicao.

## Como rodar

1. Crie e ative um ambiente virtual Python.
2. Instale dependencias:

```bash
pip install -r requirements.txt
```

3. Execute:

```bash
python app/main.py --cliente gabriel --mes 2026-03 --aporte-mensal 8000
```

Saida esperada:

- `clientes/gabriel/outputs/2026-03/relatorio.html`

## Interface de onboarding (objetivos e classificacao)

Para preencher de forma amigavel:

```bash
streamlit run app/ui.py
```

Na interface voce consegue:

- subir os arquivos do mes (extrato e posicoes m0; o MoM vem do mes anterior automaticamente)
- cadastrar/editar objetivos por cliente
- mapear ativos novos para objetivos (com peso)
- gerar e visualizar o relatorio na propria tela
- salvar configuracoes em arquivo para reutilizar mensalmente

Arquivos gerados:

- `clientes/<cliente>/objetivos.yaml`
- `clientes/<cliente>/config/asset_objective_map.csv`

## Carteira recomendada de FIIs (Suno)

O script em `scripts/suno-fiis/` automatiza a coleta da carteira recomendada de FIIs da Suno (login manual, sessao fica salva em `scripts/suno-fiis/.suno-session/`).

Requisitos (uma vez): `cd scripts/suno-fiis && npm install && npx playwright install chromium`.

Uso mensal:

```bash
./scripts/suno-fiis/run-suno-fiis.sh --cliente gabriel --mes 2026-07
```

Abre um Chromium; faca login na Suno se pedido e deixe a pagina `carteiras/fiis` aberta. O CSV e salvo automaticamente em `clientes/<cliente>/inputs/<mes>/fii_recomendados_<mes>.csv`.

## Carteira recomendada de Ações / Dividendos (Suno)

O script em `scripts/suno-acoes/` automatiza a coleta da carteira recomendada de Dividendos (ações) da Suno (login manual, sessao propria salva em `scripts/suno-acoes/.suno-session/`, separada da sessao do scraper de FIIs).

Requisitos (uma vez): `cd scripts/suno-acoes && npm install` (reaproveita o Chromium ja instalado pelo Playwright do `suno-fiis`; se ainda nao tiver nenhum, rode tambem `npx playwright install chromium`).

Uso mensal:

```bash
./scripts/suno-acoes/run-suno-acoes.sh --cliente gabriel --mes 2026-07
```

Abre um Chromium; faca login na Suno se pedido e deixe a pagina `carteiras/dividendos` aberta. O CSV e salvo automaticamente em `clientes/<cliente>/inputs/<mes>/acoes_recomendadas_<mes>.csv`. O relatorio compara esse arquivo com a posicao atual de Ações e gera a aba "Carteira recomendada de Ações (Dividendos)" com as mesmas sugestoes (comprar, aumentar, reduzir/nao aumentar, aguardar ou encerrar) usadas para FIIs.

## Formato dos inputs

Em **`clientes/<cliente>/inputs/<YYYY-MM>/`** voce guarda **so o mes de referencia** (recorrente):

- `extrato_*.csv|xlsx` — extrato do mes
- `posicao_m0_*.csv|xlsx` — posicao de fechamento **desse** mes (XP, etc.)
- `carteira_*fii*recomend*.csv|xlsx` ou `*fii*carteira*.csv|xlsx` — carteira recomendada de FIIs do mes
- `acoes_recomendadas_*.csv|xlsx` (nome com `acoes` + `recomend` ou `carteira`) — carteira recomendada de Ações/Dividendos do mes
- Opcional: CSV internacional com `m0` no nome, mesmo mes

### Carteira recomendada de FIIs

O arquivo de FIIs deve ter ao menos:

- `Rank` — quando vazio, o ativo deixou de ser recomendado; se estiver na carteira atual, o relatorio sugere encerrar a posicao
- `Ativo`/`Ticker`/`Codigo` — ticker do FII
- `Vies` — `Comprar` ou `Aguardar`

O relatorio compara esse arquivo com a posicao atual de FIIs e gera sugestoes de comprar, aumentar, reduzir/nao aumentar, aguardar ou encerrar.

### Carteira recomendada de Ações

O arquivo de Ações (gerado por `scripts/suno-acoes/`) segue o mesmo formato do de FIIs:

- `Rank` — quando vazio, o ativo deixou de ser recomendado; se estiver na carteira atual, o relatorio sugere encerrar a posicao
- `Ativo`/`Ticker`/`Codigo` — ticker da ação
- `Vies` — `Comprar` ou `Aguardar`

O relatorio compara esse arquivo com a posicao atual de Ações (`classe_ativo`/`classe_macro` = "Ações") e gera a mesma logica de sugestoes usada para FIIs.

**Variacao MoM (M1):** nao e necessario colocar arquivos `m1` na pasta do mes atual. O sistema busca automaticamente a posicao do mes anterior na pasta **`inputs/<mes-anterior>/`**, usando os arquivos de posicao (`m0`) que voce ja salvou naquele mes.

Exemplo: relatorio de **2026-04** usa M0 de `.../inputs/2026-04/` e M1 a partir de `.../inputs/2026-03/` (snapshots `m0` de marco).

**Legado:** se ainda existir `posicao_m1_*` **na pasta do mes atual**, ele ainda e aceito quando nao houver base no mes anterior.

Multiplos arquivos `m0` no mesmo mes sao somados (ex.: XP Brasil + internacional).

### Carteira internacional manual (CSV simples)

Para incluir ativos internacionais, use um CSV com:

- `Classe`
- `Ativo`
- `Valor Atual (R$)`

Exemplo:

```csv
Classe,Ativo,Valor Atual (R$)
Ações no Exterior,Apple,19962
Ações no Exterior,Google,25483
```

Convencao recomendada de nomes:

- `posicao_m0_xp_int_<YYYY-MM>.csv` (um mes por pasta; o MoM usa o arquivo `m0` do mes anterior)

Templates prontos:

- `clientes/gabriel/inputs/_templates/posicao_m0_internacional_template.csv`

## Estrutura

- `app/ingest`: leitura e normalizacao dos arquivos
- `app/core`: calculos de posicao, MoM, objetivos, sugestao de aporte
- `app/reporting`: geracao do HTML
- `clientes/`: dados por cliente (objetivos, inputs, outputs)
