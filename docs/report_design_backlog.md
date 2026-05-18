# Backlog de design do relatorio

## Objetivo

Evoluir o relatorio de um HTML analitico baseado em tabelas para uma experiencia de produto financeiro orientada a decisao.

## Melhorias priorizadas

1. Criar um resumo executivo no topo
   - Patrimonio total.
   - Variacao no mes.
   - Rentabilidade estimada.
   - Caixa disponivel.
   - Dividendos/proventos liquidos.
   - Aporte sugerido.

2. Adicionar leitura de status e narrativa do mes
   - Explicar rapidamente se o mes foi positivo ou negativo.
   - Destacar maior contribuicao positiva.
   - Destacar maior queda.
   - Destacar principal acao recomendada.

3. Melhorar a hierarquia das secoes
   - Resumo: KPIs e insights.
   - Decisao: sugestao de investimento, movimentos planejados e FIIs.
   - Diagnostico: posicao, MoM, compras/vendas e fluxos.
   - Detalhe: tabelas completas e macro.

4. Mover sugestao de investimento para uma area de decisao
   - Mostrar objetivo, valor sugerido, prioridade, motivo e impacto no gap.
   - Dar mais peso visual para o plano de acao do mes.

5. Trocar parte das tabelas por visualizacoes
   - Grafico de alocacao por classe.
   - Barras de variacao MoM por classe.
   - Barras de progresso por objetivo.
   - Possivel waterfall de variacao patrimonial.

6. Redesenhar objetivos
   - Transformar a tabela de objetivos em cards ou linhas com barra de progresso.
   - Exibir valor atual, alvo, gap, progresso e aporte sugerido.
   - Se possivel, estimar tempo ate atingir o objetivo.

7. Refinar tabelas detalhadas
   - Alinhar valores numericos a direita.
   - Reduzir bordas pesadas entre celulas.
   - Usar scroll horizontal controlado em telas pequenas.
   - Manter DataTables apenas nas secoes de detalhe.

8. Melhorar responsividade
   - KPIs em grid responsivo.
   - Tabelas largas com overflow controlado.
   - Tipos e espacamentos ajustados para preview dentro do Streamlit.

9. Refinar linguagem e acabamento
   - Corrigir acentos e termos em portugues natural.
   - Padronizar titulos, labels e microcopy.
   - Evitar instrucoes visiveis excessivas quando a interface ja for clara.

10. Melhorar estetica geral
    - Usar `system-ui` ou fonte similar a Inter.
    - Usar fundo neutro e container com largura maxima.
    - Aplicar numeros com `font-variant-numeric: tabular-nums`.
    - Usar cores semaforicas discretas.
    - Diferenciar visualmente secoes de resumo, decisao e detalhe.

## Direcao de produto

O relatorio deve responder nesta ordem:

1. Como estou?
2. O que mudou?
3. Por que mudou?
4. O que devo fazer agora?
5. Onde posso investigar os detalhes?

