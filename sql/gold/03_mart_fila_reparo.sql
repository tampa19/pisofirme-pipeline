-- GOLD | Fila de reparo: elegibilidade ao módulo + score de prioridade (0-100)
-- Parâmetros (:nome) vêm de pipeline/config.py

DROP TABLE IF EXISTS mart_fila_reparo;
CREATE TABLE mart_fila_reparo AS
WITH base AS (
    SELECT f.*,
           CAST(julianday(:data_ref) - julianday(f.data_relato) AS INT) AS dias_em_aberto,
           CASE
             WHEN f.status_sp156 IN ('FINALIZADA', 'CANCELADA')       THEN 'ja_resolvida_sp156'
             WHEN f.medida_completa = 0                              THEN 'medidas_incompletas'
             WHEN f.tipo_dano NOT IN ('buraco', 'revestimento_solto') THEN 'tipo_fora_do_escopo'
             WHEN f.tampa_proxima = 1                                 THEN 'tampa_de_servico_proxima'
             WHEN f.base_firme IS NULL                                THEN 'base_nao_avaliada'
             WHEN f.base_firme = 0                                    THEN 'base_solta'
             WHEN f.profundidade_cm > :prof_max                       THEN 'cavidade_profunda'
             WHEN f.profundidade_cm < :prof_min                       THEN 'cavidade_rasa_demais'
             WHEN f.comprimento_cm > :comp_max OR f.largura_cm > :larg_max THEN 'dano_extenso'
             ELSE NULL
           END AS motivo_inelegivel
    FROM fato_ocorrencia f
),
scores AS (
    SELECT b.*,
        ROUND(MIN(100.0, 60.0 * MIN(COALESCE(profundidade_cm, 0) / :prof_max, 1.0)
                       + 40.0 * MIN(COALESCE(area_cm2, 0) / 4800.0, 1.0)), 1)            AS score_severidade,
        ROUND(MIN(100.0, peso_poi_300m * 8.0), 1)                                          AS score_exposicao,
        ROUND(MIN(100.0, (confirmacoes + 2 * relatos_vizinhos_50m) * 12.5), 1)             AS score_recorrencia,
        ROUND(MIN(100.0, dias_em_aberto * 100.0 / 180.0), 1)                               AS score_espera
    FROM base b
)
SELECT
    id_relato, cod_subprefeitura, tipo_dano, protocolo_sp156, data_relato, dias_em_aberto,
    latitude, longitude, comprimento_cm, largura_cm, profundidade_cm, area_cm2,
    peso_poi_300m, tipo_poi_proximo, dist_poi_proximo_m, confirmacoes, relatos_vizinhos_50m,
    score_severidade, score_exposicao, score_recorrencia, score_espera,
    ROUND(:w_sev * score_severidade + :w_exp * score_exposicao + :w_rec * score_recorrencia + :w_esp * score_espera, 1)
        AS score_prioridade,
    CASE WHEN motivo_inelegivel IS NULL THEN 1 ELSE 0 END AS elegivel_modulo,
    motivo_inelegivel,
    CASE
      WHEN motivo_inelegivel = 'ja_resolvida_sp156' THEN 'encerrada'
      WHEN motivo_inelegivel IS NULL                THEN 'reparo_modular'
      WHEN motivo_inelegivel IN ('medidas_incompletas', 'base_nao_avaliada') THEN 'vistoria_necessaria'
      ELSE 'encaminhar_subprefeitura'
    END AS acao_recomendada,
    foto_url
FROM scores;

-- ranking dentro da fila ativa (exclui encerradas)
DROP TABLE IF EXISTS _rank;
CREATE TABLE _rank AS
SELECT id_relato, ROW_NUMBER() OVER (ORDER BY score_prioridade DESC, dias_em_aberto DESC) AS posicao_fila
FROM mart_fila_reparo WHERE acao_recomendada <> 'encerrada';
ALTER TABLE mart_fila_reparo ADD COLUMN posicao_fila INTEGER;
UPDATE mart_fila_reparo SET posicao_fila = (SELECT posicao_fila FROM _rank r WHERE r.id_relato = mart_fila_reparo.id_relato);
DROP TABLE _rank;
