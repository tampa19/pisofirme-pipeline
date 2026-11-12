# Dicionário de dados — camada GOLD

Tabelas entregues pelo pipeline em `data/warehouse/pisofirme.db` e exportadas em `data/gold/*.csv`.

## `dim_subprefeitura`

Dimensão geográfica: as 32 subprefeituras de São Paulo.  
**Grão:** 1 linha por subprefeitura · **Chave:** `cod_subprefeitura` · **Linhas (última execução):** 32

| Coluna | Tipo | Descrição | Domínio / regra |
|---|---|---|---|
| `cod_subprefeitura` | TEXT | Código da subprefeitura (SP01…SP32) | PK |
| `nome` | TEXT | Nome oficial padronizado | não nulo |
| `zona` | TEXT | Região da cidade | Centro/Norte/Sul/Leste/Oeste |
| `lat_centroide` | REAL | Latitude aproximada do centro da subprefeitura | graus decimais |
| `lon_centroide` | REAL | Longitude aproximada do centro da subprefeitura | graus decimais |
| `qtd_pois` | INTEGER | Quantidade de pontos de interesse mapeados na região | ≥ 0 |

## `dim_tempo`

Dimensão calendário gerada do primeiro ao último dia com dados.  
**Grão:** 1 linha por dia · **Chave:** `data` · **Linhas (última execução):** 302

| Coluna | Tipo | Descrição | Domínio / regra |
|---|---|---|---|
| `data` | TEXT | Data no formato ISO | PK, AAAA-MM-DD |
| `ano` | INTEGER | Ano |  |
| `mes` | INTEGER | Mês (1-12) |  |
| `ano_mes` | TEXT | Ano e mês para agregações | AAAA-MM |
| `dia_semana` | INTEGER | Dia da semana | 0 = domingo … 6 = sábado |
| `fim_semana` | INTEGER | Indica sábado/domingo | 0/1 |

## `dim_tipo_dano`

Catálogo de tipos de dano e se cabem no reparo modular (escopo do projeto).  
**Grão:** 1 linha por tipo de dano · **Chave:** `tipo_dano` · **Linhas (última execução):** 5

| Coluna | Tipo | Descrição | Domínio / regra |
|---|---|---|---|
| `tipo_dano` | TEXT | Código do tipo de dano | PK |
| `descricao` | TEXT | Descrição do dano |  |
| `aceito_reparo_modular` | INTEGER | Tipo aceito pelo módulo impresso | 0/1 |

## `fato_ocorrencia`

Fato principal: cada defeito relatado pelo cidadão no app, com medidas e contexto urbano.  
**Grão:** 1 linha por relato (ocorrência) · **Chave:** `id_relato` · **Linhas (última execução):** 1390

| Coluna | Tipo | Descrição | Domínio / regra |
|---|---|---|---|
| `id_relato` | TEXT | Identificador único do relato (UUID) | PK |
| `data_relato` | TEXT | Data do relato | FK → dim_tempo |
| `cod_subprefeitura` | TEXT | Subprefeitura (centróide mais próximo) | FK → dim_subprefeitura |
| `tipo_dano` | TEXT | Tipo de dano informado | FK → dim_tipo_dano |
| `protocolo_sp156` | TEXT | Protocolo SP156 vinculado, se houver | nulo = sem protocolo |
| `status_sp156` | TEXT | Status atual do protocolo vinculado | ABERTA/EM ANDAMENTO/FINALIZADA/CANCELADA |
| `latitude` | REAL | Latitude do defeito | dentro dos limites de SP |
| `longitude` | REAL | Longitude do defeito | dentro dos limites de SP |
| `comprimento_cm` | REAL | Comprimento do defeito | > 0, cm |
| `largura_cm` | REAL | Largura do defeito | > 0, cm |
| `profundidade_cm` | REAL | Profundidade (valores em mm corrigidos) | > 0 e ≤ 30, cm |
| `area_cm2` | REAL | comprimento × largura | cm² |
| `base_firme` | INTEGER | Fundo da cavidade está firme | 1/0, nulo = não avaliado |
| `tampa_proxima` | INTEGER | Há tampa de concessionária junto ao dano | 0/1 |
| `confirmacoes` | INTEGER | Outros cidadãos que confirmaram o relato | ≥ 0 |
| `peso_poi_300m` | INTEGER | Soma de pesos dos POIs num raio de 300 m | hospital/metrô=3; UBS/escola/terminal=2 |
| `dist_poi_proximo_m` | REAL | Distância ao POI mais próximo (até ~1 km) | metros |
| `tipo_poi_proximo` | TEXT | Tipo do POI mais próximo |  |
| `relatos_vizinhos_50m` | INTEGER | Outros relatos a até 50 m (recorrência) | ≥ 0 |
| `medida_completa` | INTEGER | As 3 medidas estão presentes e válidas | 0/1 |
| `foto_url` | TEXT | URL da foto enviada |  |

## `fato_solicitacao_sp156`

Fato de atendimento: solicitações do SP156 sobre calçadas (deduplicadas).  
**Grão:** 1 linha por protocolo · **Chave:** `protocolo` · **Linhas (última execução):** 3200

| Coluna | Tipo | Descrição | Domínio / regra |
|---|---|---|---|
| `protocolo` | TEXT | Número do protocolo SP156 | PK |
| `data_abertura` | TEXT | Data de abertura (formatos BR/ISO unificados) | FK → dim_tempo |
| `cod_subprefeitura` | TEXT | Subprefeitura padronizada | FK → dim_subprefeitura |
| `categoria_servico` | TEXT | Categoria derivada do serviço | defeito_pavimento, tampa_concessionaria, obstrucao, acessibilidade_guia |
| `em_escopo_modular` | INTEGER | Serviço é defeito de pavimento | 0/1 |
| `status` | TEXT | Status padronizado (maiúsculas) |  |
| `concluida` | INTEGER | Status = FINALIZADA | 0/1 |
| `dias_ate_conclusao` | INTEGER | Dias entre abertura e conclusão | ≥ 0, nulo se aberta |
| `possui_relato_app` | INTEGER | Existe relato com medidas no app | 0/1 |

## `mart_fila_reparo`

Mart do produto: elegibilidade ao módulo, score de prioridade e ação recomendada para cada ocorrência.  
**Grão:** 1 linha por ocorrência · **Chave:** `id_relato` · **Linhas (última execução):** 1390

| Coluna | Tipo | Descrição | Domínio / regra |
|---|---|---|---|
| `id_relato` | TEXT | Ocorrência | PK, FK → fato_ocorrencia |
| `cod_subprefeitura / tipo_dano / protocolo_sp156 / data_relato` | TEXT | Atributos herdados do fato |  |
| `dias_em_aberto` | INTEGER | Dias desde o relato até a data de referência da execução | ≥ 0 |
| `latitude / longitude` | REAL | Localização |  |
| `comprimento_cm / largura_cm / profundidade_cm / area_cm2` | REAL | Medidas do defeito |  |
| `peso_poi_300m / tipo_poi_proximo / dist_poi_proximo_m` | — | Contexto de exposição de pedestres |  |
| `confirmacoes / relatos_vizinhos_50m` | INTEGER | Sinais de recorrência |  |
| `score_severidade` | REAL | 60% profundidade (até 6 cm) + 40% área (até 4.800 cm²) | 0-100 |
| `score_exposicao` | REAL | peso_poi_300m × 8 | 0-100 |
| `score_recorrencia` | REAL | (confirmações + 2 × vizinhos) × 12,5 | 0-100 |
| `score_espera` | REAL | dias_em_aberto / 180 × 100 | 0-100 |
| `score_prioridade` | REAL | 0,40·sev + 0,30·exp + 0,15·rec + 0,15·espera | 0-100 |
| `elegivel_modulo` | INTEGER | Atende todas as regras de escopo do reparo modular | 0/1 |
| `motivo_inelegivel` | TEXT | Primeira regra violada | ex.: base_solta, cavidade_profunda |
| `acao_recomendada` | TEXT | Encaminhamento | reparo_modular, vistoria_necessaria, encaminhar_subprefeitura, encerrada |
| `foto_url` | TEXT | Foto do relato |  |
| `posicao_fila` | INTEGER | Posição na fila ativa (maior score primeiro) | nulo se encerrada |

## `mart_especificacao_modulo`

Mart de fabricação: parâmetros CAD e estimativas do módulo para cada buraco elegível.  
**Grão:** 1 linha por ocorrência elegível · **Chave:** `id_relato` · **Linhas (última execução):** 182

| Coluna | Tipo | Descrição | Domínio / regra |
|---|---|---|---|
| `id_relato` | TEXT | Ocorrência elegível | PK, FK → mart_fila_reparo |
| `codigo_modulo` | TEXT | Código do módulo para rastrear a peça | PF-XXXXXXXX |
| `comprimento_modulo_mm` | INTEGER | Comprimento da peça (medida − 2 × folga de 3 mm) | mm |
| `largura_modulo_mm` | INTEGER | Largura da peça (medida − 2 × folga de 3 mm) | mm |
| `altura_total_mm` | REAL | Altura total = profundidade do buraco | mm |
| `espessura_placa_mm` | INTEGER | Placa superior impressa | 8 mm (v0.3) |
| `altura_estrutura_celular_mm` | REAL | Altura do preenchimento celular giroide | ≥ 0 mm |
| `espessura_borracha_mm` | INTEGER | Cobertura de borracha natural (laser) | 3 mm |
| `pecas_impressas` | INTEGER | Peças necessárias para a mesa de 250 × 250 mm | ≥ 1 |
| `area_borracha_cm2` | REAL | Área de borracha a cortar | cm² |
| `massa_petg_g` | REAL | Estimativa de filamento PETG | g |
| `tempo_impressao_h` | REAL | Estimativa de tempo de impressão (30 g/h) | h |
| `custo_estimado_rs` | REAL | PETG (R$ 120/kg) + borracha (R$ 180/m²) | R$, referência |
| `versao_referencia` | TEXT | Versão do protótipo usada no cálculo | v0.3 |
| `parametros_cad` | TEXT | String de parâmetros para o modelo paramétrico | L;W;H_cel;T_placa;T_borr;grid |

## `mart_kpi_subprefeitura`

Mart de gestão: indicadores por subprefeitura para o painel e para a prefeitura.  
**Grão:** 1 linha por subprefeitura · **Chave:** `cod_subprefeitura` · **Linhas (última execução):** 32

| Coluna | Tipo | Descrição | Domínio / regra |
|---|---|---|---|
| `cod_subprefeitura / subprefeitura / zona` | TEXT | Identificação | PK = cod_subprefeitura |
| `solicitacoes_defeito_sp156` | INTEGER | Protocolos SP156 de defeito de pavimento | ≥ 0 |
| `tempo_medio_conclusao_dias` | REAL | Média de dias até conclusão (finalizadas) | dias |
| `pct_concluidas` | REAL | % de protocolos de defeito finalizados | 0-100 |
| `ocorrencias_ativas` | INTEGER | Ocorrências do app ainda não resolvidas | ≥ 0 |
| `elegiveis_modulo` | INTEGER | Ocorrências elegíveis ao reparo modular | ≥ 0 |
| `score_medio` | REAL | Score médio de prioridade das ativas | 0-100 |
| `custo_total_modulos_rs` | REAL | Custo estimado dos módulos da região | R$ |

## `mart_validacao_prototipo`

Mart de P&D: resultados médios dos ensaios de bancada por versão do módulo e aprovação.  
**Grão:** 1 linha por versão do módulo · **Chave:** `versao_modulo` · **Linhas (última execução):** 4

| Coluna | Tipo | Descrição | Domínio / regra |
|---|---|---|---|
| `versao_modulo` | TEXT | Versão do protótipo | PK, v0.1…v0.4 |
| `material / padrao_celula / infill_pct` | — | Configuração da estrutura impressa |  |
| `espessura_placa_mm / espessura_borracha_mm` | REAL | Espessuras da placa e da borracha | mm |
| `nivel_mm` | REAL | Diferença de altura módulo × piso | critério ≤ 5 mm (NBR 9050) |
| `deformacao_residual_mm` | REAL | Afundamento residual após carga de 80 kgf | critério ≤ 2 mm |
| `deslocamento_mm` | REAL | Deslocamento lateral sob carga | critério ≤ 3 mm |
| `aderencia_seco_ptv / aderencia_molhado_ptv` | REAL | Aderência no ensaio de pêndulo | critério ≥ 36 PTV |
| `corpos_prova` | INTEGER | Nº de corpos de prova ensaiados |  |
| `criterios_atendidos` | INTEGER | Critérios atendidos | 0-5 |
| `aprovado_bancada` | INTEGER | Atende os 5 critérios | 0/1 |

## `feat_modelo_severidade`

Tabela de features para o modelo de IA da equipe (classificar severidade a partir da foto + contexto).  
**Grão:** 1 linha por ocorrência com medidas completas · **Chave:** `id_relato` · **Linhas (última execução):** 1349

| Coluna | Tipo | Descrição | Domínio / regra |
|---|---|---|---|
| `id_relato / foto_url` | TEXT | Identificação e imagem de entrada do modelo | PK = id_relato |
| `tipo_dano / zona` | TEXT | Variáveis categóricas |  |
| `comprimento_cm … confirmacoes` | — | Variáveis numéricas (medidas, base, tampa, POIs, recorrência) |  |
| `score_severidade` | REAL | Score numérico de severidade | 0-100 |
| `rotulo_severidade` | TEXT | Rótulo-alvo para treino | baixa (<40), media (40-69), alta (≥70) |
