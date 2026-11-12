-- GOLD | Indicadores por subprefeitura, validação do protótipo e features para IA

DROP TABLE IF EXISTS mart_kpi_subprefeitura;
CREATE TABLE mart_kpi_subprefeitura AS
SELECT d.cod_subprefeitura, d.nome AS subprefeitura, d.zona,
       (SELECT COUNT(*) FROM fato_solicitacao_sp156 s WHERE s.cod_subprefeitura = d.cod_subprefeitura
                                                      AND s.em_escopo_modular = 1)                 AS solicitacoes_defeito_sp156,
       (SELECT ROUND(AVG(s.dias_ate_conclusao), 1) FROM fato_solicitacao_sp156 s
         WHERE s.cod_subprefeitura = d.cod_subprefeitura AND s.concluida = 1 AND s.em_escopo_modular = 1) AS tempo_medio_conclusao_dias,
       (SELECT ROUND(100.0 * SUM(s.concluida) / COUNT(*), 1) FROM fato_solicitacao_sp156 s
         WHERE s.cod_subprefeitura = d.cod_subprefeitura AND s.em_escopo_modular = 1)              AS pct_concluidas,
       (SELECT COUNT(*) FROM mart_fila_reparo m WHERE m.cod_subprefeitura = d.cod_subprefeitura
                                                AND m.acao_recomendada <> 'encerrada')            AS ocorrencias_ativas,
       (SELECT COUNT(*) FROM mart_fila_reparo m WHERE m.cod_subprefeitura = d.cod_subprefeitura
                                                AND m.elegivel_modulo = 1)                        AS elegiveis_modulo,
       (SELECT ROUND(AVG(m.score_prioridade), 1) FROM mart_fila_reparo m
         WHERE m.cod_subprefeitura = d.cod_subprefeitura AND m.acao_recomendada <> 'encerrada')   AS score_medio,
       (SELECT ROUND(SUM(e.custo_estimado_rs), 2) FROM mart_especificacao_modulo e
          JOIN mart_fila_reparo m ON m.id_relato = e.id_relato
         WHERE m.cod_subprefeitura = d.cod_subprefeitura)                                          AS custo_total_modulos_rs
FROM dim_subprefeitura d;

DROP TABLE IF EXISTS mart_validacao_prototipo;
CREATE TABLE mart_validacao_prototipo AS
SELECT versao_modulo, MAX(material) AS material, MAX(padrao_celula) AS padrao_celula,
       MAX(infill_pct) AS infill_pct, MAX(espessura_placa_mm) AS espessura_placa_mm,
       MAX(espessura_borracha_mm) AS espessura_borracha_mm,
       ROUND(AVG(CASE WHEN ensaio = 'nivel' THEN valor END), 2)               AS nivel_mm,
       ROUND(AVG(CASE WHEN ensaio = 'deformacao_residual' THEN valor END), 2) AS deformacao_residual_mm,
       ROUND(AVG(CASE WHEN ensaio = 'deslocamento' THEN valor END), 2)        AS deslocamento_mm,
       ROUND(AVG(CASE WHEN ensaio = 'aderencia_seco' THEN valor END), 1)      AS aderencia_seco_ptv,
       ROUND(AVG(CASE WHEN ensaio = 'aderencia_molhado' THEN valor END), 1)   AS aderencia_molhado_ptv,
       COUNT(DISTINCT corpo_prova) AS corpos_prova
FROM silver_ensaios GROUP BY versao_modulo;
ALTER TABLE mart_validacao_prototipo ADD COLUMN criterios_atendidos INTEGER;
ALTER TABLE mart_validacao_prototipo ADD COLUMN aprovado_bancada INTEGER;
UPDATE mart_validacao_prototipo SET criterios_atendidos =
      (nivel_mm <= :c_nivel) + (deformacao_residual_mm <= :c_def) + (deslocamento_mm <= :c_desl)
    + (aderencia_seco_ptv >= :c_ads) + (aderencia_molhado_ptv >= :c_adm);
UPDATE mart_validacao_prototipo SET aprovado_bancada = CASE WHEN criterios_atendidos = 5 THEN 1 ELSE 0 END;

-- Tabela de features pronta para o modelo de IA da equipe (classificação de severidade a partir da foto + contexto)
DROP TABLE IF EXISTS feat_modelo_severidade;
CREATE TABLE feat_modelo_severidade AS
SELECT f.id_relato, f.foto_url, f.tipo_dano, d.zona,
       f.comprimento_cm, f.largura_cm, f.profundidade_cm, f.area_cm2,
       f.base_firme, f.tampa_proxima, f.peso_poi_300m, f.relatos_vizinhos_50m, f.confirmacoes,
       m.score_severidade,
       CASE WHEN m.score_severidade >= 70 THEN 'alta' WHEN m.score_severidade >= 40 THEN 'media' ELSE 'baixa' END
           AS rotulo_severidade
FROM fato_ocorrencia f
JOIN mart_fila_reparo m ON m.id_relato = f.id_relato
JOIN dim_subprefeitura d ON d.cod_subprefeitura = f.cod_subprefeitura
WHERE f.medida_completa = 1;
