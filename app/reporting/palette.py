from __future__ import annotations

# Paleta categorica validada (ordem fixa, ver skill dataviz): 8 tons, checados
# para pares adjacentes em graficos de barras empilhadas (CVD + contraste) contra
# a superficie --surface-muted (#f7f6f3) usada nos graficos do relatorio.
CATEGORICAL_PALETTE = [
    "#2a78d6",  # 1 azul
    "#eb6834",  # 2 laranja
    "#1baf7a",  # 3 agua
    "#eda100",  # 4 amarelo
    "#e87ba4",  # 5 magenta
    "#008300",  # 6 verde
    "#4a3aa7",  # 7 violeta
    "#e34948",  # 8 vermelho
]

# Cinza neutro para o bucket de sobra ("Outros"), fora da paleta categorica
# (nao compete por identidade com nenhuma serie real).
OUTROS_COLOR = "#b9b7ae"

# "Por origem" usa sempre os 2 primeiros slots da ordem fixa.
BRASIL_COLOR = CATEGORICAL_PALETTE[0]
EXTERIOR_COLOR = CATEGORICAL_PALETTE[1]

# "Por ativo" usa até os 8 slots para os maiores ativos; o resto cai em OUTROS_COLOR.
TOP_N_ATIVOS = len(CATEGORICAL_PALETTE)
OUTROS_ATIVOS_LABEL = "Outros ativos"
