"""
ETAPA 4 — ENTREGA AO MVP

Exporta as tabelas GOLD (CSV em data/gold/) e gera mvp/dados.js, que é lido pelo
painel do MVP (mvp/index.html): fila de reparo, especificação dos módulos, indicadores
por subprefeitura e status de validação do protótipo.
"""
from __future__ import annotations

import json

import pandas as pd

from pipeline import config
from pipeline.utils import agora_utc, conectar, contexto_execucao, log, registrar_execucao

TABELAS_GOLD = ["dim_subprefeitura", "dim_tempo", "dim_tipo_dano", "fato_ocorrencia", "fato_solicitacao_sp156",
                "mart_fila_reparo", "mart_especificacao_modulo", "mart_kpi_subprefeitura",
                "mart_validacao_prototipo", "feat_modelo_severidade"]


def _registros(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", force_ascii=False))


def exportar_gold(**context):
    ds, run_id = contexto_execucao(context)
    config.GOLD_EXPORT.mkdir(parents=True, exist_ok=True)
    total = 0
    with conectar() as con:
        for t in TABELAS_GOLD:
            df = pd.read_sql(f"SELECT * FROM {t}", con)
            df.to_csv(config.GOLD_EXPORT / f"{t}.csv", index=False, encoding="utf-8")
            total += len(df)
            log.info("exportado data/gold/%s.csv (%d linhas)", t, len(df))
        registrar_execucao(con, run_id, "publicacao.exportar_gold", "sucesso", total)


def publicar_mvp(**context):
    ds, run_id = contexto_execucao(context)
    with conectar() as con:
        q = lambda s, params=None: pd.read_sql(s, con, params=params)
        fila = q("""SELECT m.*, d.nome AS subprefeitura, e.codigo_modulo, e.pecas_impressas, e.massa_petg_g,
                           e.tempo_impressao_h, e.custo_estimado_rs, e.parametros_cad, e.comprimento_modulo_mm,
                           e.largura_modulo_mm, e.altura_estrutura_celular_mm
                    FROM mart_fila_reparo m
                    JOIN dim_subprefeitura d USING (cod_subprefeitura)
                    LEFT JOIN mart_especificacao_modulo e USING (id_relato)
                    WHERE m.acao_recomendada <> 'encerrada'
                    ORDER BY m.posicao_fila""")
        resumo = q("""SELECT COUNT(*) AS ocorrencias,
                        SUM(acao_recomendada <> 'encerrada') AS ativas,
                        SUM(elegivel_modulo) AS elegiveis,
                        SUM(acao_recomendada = 'vistoria_necessaria') AS vistoria,
                        SUM(acao_recomendada = 'encaminhar_subprefeitura') AS encaminhar,
                        ROUND(AVG(CASE WHEN acao_recomendada <> 'encerrada' THEN score_prioridade END), 1) AS score_medio
                      FROM mart_fila_reparo""").iloc[0].to_dict()
        custo = q("SELECT ROUND(SUM(custo_estimado_rs),2) c, ROUND(SUM(massa_petg_g)/1000,1) kg, "
                  "ROUND(SUM(tempo_impressao_h),0) h FROM mart_especificacao_modulo").iloc[0].to_dict()
        motivos = q("""SELECT motivo_inelegivel AS motivo, COUNT(*) AS qtd FROM mart_fila_reparo
                       WHERE motivo_inelegivel IS NOT NULL AND motivo_inelegivel <> 'ja_resolvida_sp156'
                       GROUP BY 1 ORDER BY 2 DESC""")
        dados = {
            "gerado_em": agora_utc(), "run_id": run_id, "data_referencia": ds,
            "resumo": {k: (None if pd.isna(v) else float(v)) for k, v in {**resumo, **custo}.items()},
            "fila": _registros(fila),
            "kpi_subprefeitura": _registros(q("SELECT * FROM mart_kpi_subprefeitura ORDER BY ocorrencias_ativas DESC")),
            "validacao": _registros(q("SELECT * FROM mart_validacao_prototipo ORDER BY versao_modulo")),
            "motivos": _registros(motivos),
            "qualidade": _registros(q("SELECT camada, verificacao, severidade, violacoes, status FROM dq_resultados "
                                      "WHERE run_id = :r", params={"r": run_id})),
        }
        config.MVP_DIR.mkdir(parents=True, exist_ok=True)
        (config.MVP_DIR / "dados.js").write_text(
            "// Gerado automaticamente pelo pipeline PisoFirme (tarefa publicacao.publicar_mvp). Não editar.\n"
            "window.PISOFIRME = " + json.dumps(dados, ensure_ascii=False) + ";\n", encoding="utf-8")
        registrar_execucao(con, run_id, "publicacao.publicar_mvp", "sucesso", len(fila))
    log.info("MVP atualizado: mvp/dados.js (%d itens na fila, %d elegíveis ao módulo)",
             len(fila), int(resumo["elegiveis"]))
