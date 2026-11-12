-- GOLD | Tabelas fato
-- int_relatos_contexto é criada antes, em Python (cálculo geoespacial de POIs e vizinhança).

DROP TABLE IF EXISTS fato_ocorrencia;
CREATE TABLE fato_ocorrencia (
    id_relato              TEXT PRIMARY KEY,
    data_relato            TEXT REFERENCES dim_tempo(data),
    cod_subprefeitura      TEXT REFERENCES dim_subprefeitura(cod_subprefeitura),
    tipo_dano              TEXT REFERENCES dim_tipo_dano(tipo_dano),
    protocolo_sp156        TEXT,
    status_sp156           TEXT,
    latitude               REAL,
    longitude              REAL,
    comprimento_cm         REAL,
    largura_cm             REAL,
    profundidade_cm        REAL,
    area_cm2               REAL,
    base_firme             INTEGER,
    tampa_proxima          INTEGER,
    confirmacoes           INTEGER,
    peso_poi_300m          INTEGER,
    dist_poi_proximo_m     REAL,
    tipo_poi_proximo       TEXT,
    relatos_vizinhos_50m   INTEGER,
    medida_completa        INTEGER,
    foto_url               TEXT
);
INSERT INTO fato_ocorrencia
SELECT r.id_relato, r.data_relato, r.cod_subprefeitura, r.tipo_dano, r.protocolo_sp156, s.status,
       r.latitude, r.longitude, r.comprimento_cm, r.largura_cm, r.profundidade_cm, r.area_cm2,
       r.base_firme, r.tampa_proxima, CAST(r.confirmacoes AS INT),
       c.peso_poi_300m, c.dist_poi_proximo_m, c.tipo_poi_proximo, c.relatos_vizinhos_50m,
       CASE WHEN r.comprimento_cm IS NOT NULL AND r.largura_cm IS NOT NULL AND r.profundidade_cm IS NOT NULL THEN 1 ELSE 0 END,
       r.foto_url
FROM silver_relatos r
JOIN int_relatos_contexto c ON c.id_relato = r.id_relato
LEFT JOIN silver_sp156 s ON s.protocolo = r.protocolo_sp156;

DROP TABLE IF EXISTS fato_solicitacao_sp156;
CREATE TABLE fato_solicitacao_sp156 (
    protocolo           TEXT PRIMARY KEY,
    data_abertura       TEXT REFERENCES dim_tempo(data),
    cod_subprefeitura   TEXT REFERENCES dim_subprefeitura(cod_subprefeitura),
    categoria_servico   TEXT,
    em_escopo_modular   INTEGER,
    status              TEXT,
    concluida           INTEGER,
    dias_ate_conclusao  INTEGER,
    possui_relato_app   INTEGER
);
INSERT INTO fato_solicitacao_sp156
SELECT s.protocolo, substr(s.dt_abertura, 1, 10), s.cod_subprefeitura, s.categoria_servico, s.em_escopo_modular,
       s.status, CASE WHEN s.status = 'FINALIZADA' THEN 1 ELSE 0 END, s.dias_ate_conclusao,
       CASE WHEN EXISTS (SELECT 1 FROM silver_relatos r WHERE r.protocolo_sp156 = s.protocolo) THEN 1 ELSE 0 END
FROM silver_sp156 s;
