"""
ETAPA 3 — MODELAGEM (camada GOLD, padrão ELT: transformações em SQL dentro do warehouse)

 - dimensões (dim_subprefeitura, dim_tempo, dim_tipo_dano)
 - contexto geoespacial (Python): POIs num raio de 300 m e relatos vizinhos
 - fatos (fato_ocorrencia, fato_solicitacao_sp156)
 - marts que alimentam o MVP: fila de reparo priorizada, especificação paramétrica
   do módulo a imprimir, indicadores por subprefeitura, validação do protótipo
 - tabela de features para o modelo de IA de severidade
"""
from __future__ import annotations

import math

import pandas as pd

from pipeline import config
from pipeline.utils import conectar, contexto_execucao, haversine_m, log, registrar_execucao


def _executar_sql(con, arquivo: str, params: dict | None = None):
    sql = (config.SQL_DIR / "gold" / arquivo).read_text(encoding="utf-8")
    linhas = [l for l in sql.splitlines() if not l.strip().startswith("--")]
    comandos = [c.strip() for c in "\n".join(linhas).split(";") if c.strip()]
    for cmd in comandos:
        con.execute(cmd, params or {})
    log.info("executado sql/gold/%s (%d comandos)", arquivo, len(comandos))


def _params(ds: str) -> dict:
    e, w, c = config.ELEGIBILIDADE, config.PESOS_PRIORIDADE, config.CRITERIOS_ENSAIO
    return {"data_ref": ds, "prof_max": e["profundidade_max_cm"], "prof_min": e["profundidade_min_cm"],
            "comp_max": e["comprimento_max_cm"], "larg_max": e["largura_max_cm"],
            "w_sev": w["severidade"], "w_exp": w["exposicao"], "w_rec": w["recorrencia"], "w_esp": w["espera"],
            "c_nivel": c["nivel"][1], "c_def": c["deformacao_residual"][1], "c_desl": c["deslocamento"][1],
            "c_ads": c["aderencia_seco"][1], "c_adm": c["aderencia_molhado"][1]}


def construir_dimensoes(**context):
    ds, run_id = contexto_execucao(context)
    with conectar() as con:
        _executar_sql(con, "01_dimensoes.sql")
        n = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("dim_subprefeitura", "dim_tempo", "dim_tipo_dano")}
        registrar_execucao(con, run_id, "gold.dimensoes", "sucesso", sum(n.values()), str(n))
    log.info("dimensões: %s", n)


def _contexto_geo(con) -> pd.DataFrame:
    """Para cada relato: peso dos POIs em 300 m, POI mais próximo e nº de relatos vizinhos (50 m)."""
    rel = pd.read_sql("SELECT id_relato, latitude, longitude FROM silver_relatos", con)
    poi = pd.read_sql("SELECT tipo, latitude, longitude FROM silver_poi", con)
    pois = list(zip(poi["tipo"], poi["latitude"], poi["longitude"]))
    pts = list(zip(rel["id_relato"], rel["latitude"], rel["longitude"]))
    out = []
    for rid, la, lo in pts:
        peso, melhor = 0, (None, math.inf)
        for tipo, pla, plo in pois:
            if abs(pla - la) > 0.01 or abs(plo - lo) > 0.01:      # filtro rápido (~1 km)
                continue
            d = haversine_m(la, lo, pla, plo)
            if d <= config.RAIO_POI_M:
                peso += config.PESO_POI.get(tipo, 1)
            if d < melhor[1]:
                melhor = (tipo, d)
        viz = sum(1 for oid, ola, olo in pts if oid != rid and abs(ola - la) < 0.0006 and abs(olo - lo) < 0.0006
                  and haversine_m(la, lo, ola, olo) <= 50)
        out.append((rid, peso, None if melhor[0] is None else round(melhor[1], 1), melhor[0], viz))
    return pd.DataFrame(out, columns=["id_relato", "peso_poi_300m", "dist_poi_proximo_m", "tipo_poi_proximo",
                                      "relatos_vizinhos_50m"])


def construir_fatos(**context):
    ds, run_id = contexto_execucao(context)
    with conectar() as con:
        ctx = _contexto_geo(con)
        ctx.to_sql("int_relatos_contexto", con, if_exists="replace", index=False)
        log.info("contexto geoespacial calculado para %d relatos (POIs <= %d m)", len(ctx), config.RAIO_POI_M)
        _executar_sql(con, "02_fatos.sql")
        n1 = con.execute("SELECT COUNT(*) FROM fato_ocorrencia").fetchone()[0]
        n2 = con.execute("SELECT COUNT(*) FROM fato_solicitacao_sp156").fetchone()[0]
        registrar_execucao(con, run_id, "gold.fatos", "sucesso", n1 + n2)
    log.info("fato_ocorrencia=%d  fato_solicitacao_sp156=%d", n1, n2)


def _especificar_modulos(con) -> pd.DataFrame:
    """Gera os parâmetros CAD do módulo (placa + estrutura celular + borracha) para cada buraco elegível."""
    m = config.MODULO
    df = pd.read_sql("""SELECT id_relato, comprimento_cm, largura_cm, profundidade_cm
                        FROM mart_fila_reparo WHERE elegivel_modulo = 1""", con)
    linhas = []
    for r in df.itertuples():
        comp_mm = round(r.comprimento_cm * 10 - 2 * m["folga_borda_mm"])
        larg_mm = round(r.largura_cm * 10 - 2 * m["folga_borda_mm"])
        prof_mm = r.profundidade_cm * 10
        alt_celula = round(prof_mm - m["espessura_placa_mm"] - m["espessura_borracha_mm"], 1)
        mesa = m["mesa_impressora_mm"]
        nx, ny = math.ceil(comp_mm / mesa), math.ceil(larg_mm / mesa)
        area_cm2 = comp_mm * larg_mm / 100
        vol_cm3 = area_cm2 * (m["espessura_placa_mm"] / 10) * m["infill_placa"] + area_cm2 * (max(alt_celula, 0) / 10) * m["infill_celular"]
        massa_g = vol_cm3 * m["densidade_petg_g_cm3"]
        custo = massa_g / 1000 * m["custo_petg_por_kg"] + area_cm2 / 10000 * m["custo_borracha_por_m2"]
        linhas.append({
            "id_relato": r.id_relato,
            "codigo_modulo": f"PF-{r.id_relato[:8].upper()}",
            "comprimento_modulo_mm": comp_mm, "largura_modulo_mm": larg_mm,
            "altura_total_mm": round(prof_mm, 1),
            "espessura_placa_mm": m["espessura_placa_mm"],
            "altura_estrutura_celular_mm": max(alt_celula, 0.0),
            "espessura_borracha_mm": m["espessura_borracha_mm"],
            "pecas_impressas": nx * ny,
            "area_borracha_cm2": round(area_cm2, 1),
            "massa_petg_g": round(massa_g, 1),
            "tempo_impressao_h": round(massa_g / m["vazao_impressao_g_h"], 1),
            "custo_estimado_rs": round(custo, 2),
            "versao_referencia": "v0.3",
            "parametros_cad": (f"L={comp_mm};W={larg_mm};H_cel={max(alt_celula, 0.0)};T_placa={m['espessura_placa_mm']};"
                               f"T_borr={m['espessura_borracha_mm']};grid={nx}x{ny};celula=giroide"),
        })
    return pd.DataFrame(linhas)


def construir_marts(**context):
    ds, run_id = contexto_execucao(context)
    with conectar() as con:
        p = _params(ds)
        _executar_sql(con, "03_mart_fila_reparo.sql", p)
        esp = _especificar_modulos(con)
        esp.to_sql("mart_especificacao_modulo", con, if_exists="replace", index=False)
        log.info("mart_especificacao_modulo: %d módulos especificados", len(esp))
        _executar_sql(con, "04_marts_indicadores.sql", p)
        resumo = dict(con.execute("SELECT acao_recomendada, COUNT(*) FROM mart_fila_reparo GROUP BY 1").fetchall())
        registrar_execucao(con, run_id, "gold.marts", "sucesso", len(esp), str(resumo))
    log.info("fila de reparo por ação: %s", resumo)
