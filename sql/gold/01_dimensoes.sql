-- GOLD | Dimensões do modelo estrela
-- As tabelas fato referenciam as dimensões (FOREIGN KEY): no reprocessamento elas são
-- removidas primeiro e recriadas na tarefa gold.fatos.
DROP TABLE IF EXISTS fato_ocorrencia;
DROP TABLE IF EXISTS fato_solicitacao_sp156;

DROP TABLE IF EXISTS dim_subprefeitura;
CREATE TABLE dim_subprefeitura (
    cod_subprefeitura TEXT PRIMARY KEY,
    nome              TEXT NOT NULL,
    zona              TEXT NOT NULL,
    lat_centroide     REAL,
    lon_centroide     REAL,
    qtd_pois          INTEGER
);
INSERT INTO dim_subprefeitura
SELECT s.cod_subprefeitura, s.nome, s.zona, s.lat, s.lon,
       (SELECT COUNT(*) FROM silver_poi p WHERE p.cod_subprefeitura = s.cod_subprefeitura)
FROM silver_subprefeitura s;

DROP TABLE IF EXISTS dim_tipo_dano;
CREATE TABLE dim_tipo_dano (
    tipo_dano             TEXT PRIMARY KEY,
    descricao             TEXT,
    aceito_reparo_modular INTEGER
);
INSERT INTO dim_tipo_dano VALUES
 ('buraco',             'Cavidade localizada no revestimento',                     1),
 ('revestimento_solto', 'Perda/soltura localizada do revestimento',                1),
 ('desnivel',           'Degrau entre placas sem cavidade',                        0),
 ('raiz_arvore',        'Levantamento do piso por raiz (exige intervenção maior)', 0),
 ('tampa_servico',      'Dano junto a tampa de concessionária (manter acesso)',    0);

DROP TABLE IF EXISTS dim_tempo;
CREATE TABLE dim_tempo (
    data        TEXT PRIMARY KEY,
    ano         INTEGER,
    mes         INTEGER,
    ano_mes     TEXT,
    dia_semana  INTEGER,   -- 0 = domingo
    fim_semana  INTEGER
);
WITH RECURSIVE dias(d) AS (
    SELECT MIN(m) FROM (SELECT MIN(substr(dt_abertura,1,10)) m FROM silver_sp156
                        UNION ALL SELECT MIN(data_relato) FROM silver_relatos)
    UNION ALL
    SELECT date(d, '+1 day') FROM dias WHERE d < (SELECT MAX(m) FROM (SELECT MAX(substr(dt_abertura,1,10)) m FROM silver_sp156
                                                                   UNION ALL SELECT MAX(data_relato) FROM silver_relatos))
)
INSERT INTO dim_tempo
SELECT d, CAST(strftime('%Y', d) AS INT), CAST(strftime('%m', d) AS INT), strftime('%Y-%m', d),
       CAST(strftime('%w', d) AS INT), CASE WHEN strftime('%w', d) IN ('0','6') THEN 1 ELSE 0 END
FROM dias;
