"""
Testes de QUALIDADE DE DADOS (data quality gates).

Cada verificação é uma consulta SQL que retorna a quantidade de registros que VIOLAM a regra.
Resultados vão para a tabela dq_resultados. Se alguma verificação 'critica' falhar,
a tarefa levanta exceção e o Airflow interrompe o pipeline (o MVP não recebe dado ruim).
"""
from __future__ import annotations

from pipeline import config
from pipeline.utils import agora_utc, conectar, contexto_execucao, log


class QualidadeDadosError(RuntimeError):
    pass


COLUNAS_OBRIGATORIAS = {
    "sp156": ["protocolo", "data_abertura", "subprefeitura", "servico", "status"],
    "relatos_app": ["id_relato", "criado_em", "geo_lat", "geo_lon", "tipo_dano", "medidas_profundidade_cm"],
    "pontos_interesse": ["id_poi", "tipo", "latitude", "longitude"],
    "subprefeituras": ["codigo", "nome", "zona"],
    "ensaios_bancada": ["versao_modulo", "corpo_prova", "ensaio", "valor"],
}

CHECKS_GOLD = [
    # (nome, severidade, SQL que conta violações)
    ("fato_ocorrencia.pk_unica", "critica",
     "SELECT COUNT(*) - COUNT(DISTINCT id_relato) FROM fato_ocorrencia"),
    ("fato_ocorrencia.fk_subprefeitura", "critica",
     "SELECT COUNT(*) FROM fato_ocorrencia f LEFT JOIN dim_subprefeitura d USING(cod_subprefeitura) WHERE d.cod_subprefeitura IS NULL"),
    ("fato_ocorrencia.fk_tipo_dano", "critica",
     "SELECT COUNT(*) FROM fato_ocorrencia f LEFT JOIN dim_tipo_dano d USING(tipo_dano) WHERE d.tipo_dano IS NULL"),
    ("fato_ocorrencia.fk_tempo", "critica",
     "SELECT COUNT(*) FROM fato_ocorrencia f LEFT JOIN dim_tempo d ON d.data = f.data_relato WHERE d.data IS NULL"),
    ("fato_ocorrencia.coordenadas_em_sp", "critica",
     f"SELECT COUNT(*) FROM fato_ocorrencia WHERE latitude NOT BETWEEN {config.BBOX_SP['lat_min']} AND {config.BBOX_SP['lat_max']}"
     f" OR longitude NOT BETWEEN {config.BBOX_SP['lon_min']} AND {config.BBOX_SP['lon_max']}"),
    ("fato_ocorrencia.medidas_positivas", "critica",
     "SELECT COUNT(*) FROM fato_ocorrencia WHERE comprimento_cm <= 0 OR largura_cm <= 0 OR profundidade_cm <= 0"),
    ("fato_ocorrencia.profundidade_plausivel_<=30cm", "critica",
     "SELECT COUNT(*) FROM fato_ocorrencia WHERE profundidade_cm > 30"),
    ("fato_solicitacao_sp156.pk_unica", "critica",
     "SELECT COUNT(*) - COUNT(DISTINCT protocolo) FROM fato_solicitacao_sp156"),
    ("fato_solicitacao_sp156.conclusao_apos_abertura", "critica",
     "SELECT COUNT(*) FROM fato_solicitacao_sp156 WHERE dias_ate_conclusao < 0"),
    ("mart_fila_reparo.score_entre_0_e_100", "critica",
     "SELECT COUNT(*) FROM mart_fila_reparo WHERE score_prioridade < 0 OR score_prioridade > 100"),
    ("mart_fila_reparo.elegiveis_respeitam_escopo", "critica",
     f"SELECT COUNT(*) FROM mart_fila_reparo WHERE elegivel_modulo = 1 AND (profundidade_cm > {config.ELEGIBILIDADE['profundidade_max_cm']}"
     " OR tipo_dano NOT IN ('buraco','revestimento_solto'))"),
    ("mart_especificacao_modulo.altura_celula_nao_negativa", "critica",
     "SELECT COUNT(*) FROM mart_especificacao_modulo WHERE altura_estrutura_celular_mm < 0"),
    ("mart_especificacao_modulo.um_por_elegivel", "critica",
     "SELECT ABS((SELECT COUNT(*) FROM mart_especificacao_modulo) - (SELECT COUNT(*) FROM mart_fila_reparo WHERE elegivel_modulo = 1))"),
    ("mart_kpi_subprefeitura.todas_32_subprefeituras", "critica",
     "SELECT ABS(32 - COUNT(*)) FROM mart_kpi_subprefeitura"),
    ("silver_quarentena.taxa_rejeicao_<=10pct", "alerta",
     "SELECT CASE WHEN 100.0 * (SELECT COUNT(*) FROM silver_quarentena) / "
     "((SELECT COUNT(*) FROM silver_sp156) + (SELECT COUNT(*) FROM silver_relatos)) > 10 THEN 1 ELSE 0 END"),
    ("fato_ocorrencia.medidas_completas_>=90pct", "alerta",
     "SELECT CASE WHEN AVG(medida_completa) < 0.9 THEN 1 ELSE 0 END FROM fato_ocorrencia"),
]


def _gravar(con, run_id, camada, resultados):
    con.execute("""CREATE TABLE IF NOT EXISTS dq_resultados (
        run_id TEXT, camada TEXT, verificacao TEXT, severidade TEXT, violacoes INTEGER, status TEXT, verificado_em TEXT)""")
    ts = agora_utc()
    con.executemany("INSERT INTO dq_resultados VALUES (?,?,?,?,?,?,?)",
                    [(run_id, camada, n, s, v, "OK" if v == 0 else ("FALHA" if s == "critica" else "ALERTA"), ts)
                     for n, s, v in resultados])


def _avaliar(resultados, camada):
    for nome, sev, v in resultados:
        nivel = "OK    " if v == 0 else ("FALHA " if sev == "critica" else "ALERTA")
        log.info("[DQ %s] %s %-55s violações=%d", camada, nivel, nome, v)
    falhas = [n for n, s, v in resultados if s == "critica" and v > 0]
    if falhas:
        raise QualidadeDadosError(f"{len(falhas)} verificação(ões) crítica(s) falharam: {falhas}")
    log.info("[DQ %s] %d verificações executadas, 0 falhas críticas", camada, len(resultados))


def validar_bronze(**context):
    ds, run_id = contexto_execucao(context)
    resultados = []
    with conectar() as con:
        for fonte, cols in COLUNAS_OBRIGATORIAS.items():
            tab = f"bronze_{fonte}"
            n = con.execute(f"SELECT COUNT(*) FROM {tab} WHERE _ds = ?", (ds,)).fetchone()[0]
            resultados.append((f"{tab}.possui_linhas_no_dia", "critica", 0 if n > 0 else 1))
            existentes = {r[1] for r in con.execute(f"PRAGMA table_info({tab})")}
            resultados.append((f"{tab}.colunas_obrigatorias", "critica", len(set(cols) - existentes)))
            pk = cols[0]
            nulos = con.execute(f'SELECT COUNT(*) FROM {tab} WHERE _ds = ? AND ("{pk}" IS NULL OR "{pk}" = "")', (ds,)).fetchone()[0]
            resultados.append((f"{tab}.{pk}_nao_nulo", "critica", nulos))
        _gravar(con, run_id, "bronze", resultados)
    _avaliar(resultados, "bronze")


def validar_gold(**context):
    ds, run_id = contexto_execucao(context)
    with conectar() as con:
        resultados = [(n, s, int(con.execute(q).fetchone()[0] or 0)) for n, s, q in CHECKS_GOLD]
        _gravar(con, run_id, "gold", resultados)
    _avaliar(resultados, "gold")
