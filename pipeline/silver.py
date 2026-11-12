"""
ETAPA 2 — TRATAMENTO (camada SILVER)

Lê a BRONZE do dia (_ds mais recente), limpa, padroniza e tipa os dados:
 - deduplicação (protocolo SP156 / id do relato);
 - padronização de nomes de subprefeitura (variações de acento/caixa/digitação);
 - datas em formatos diferentes -> ISO 8601;
 - coordenadas fora de SP -> quarentena ou nulas;
 - correção de unidade (profundidade digitada em mm), valores negativos, booleanos "sim/nao";
 - números com vírgula decimal;
 - enriquecimento geográfico (subprefeitura do relato pelo centróide mais próximo).
Registros que não podem ser aproveitados vão para silver_quarentena com o motivo.
"""
from __future__ import annotations

import difflib
import json

import pandas as pd

from pipeline import config
from pipeline.utils import (chave_texto, conectar, contexto_execucao, coord_valida, haversine_m, log,
                            registrar_execucao)


def _bronze(con, fonte) -> pd.DataFrame:
    df = pd.read_sql(f"SELECT * FROM bronze_{fonte} WHERE _ds = (SELECT MAX(_ds) FROM bronze_{fonte})", con)
    return df.drop(columns=[c for c in df.columns if c.startswith("_") and c != "_run_id"])


def _quarentena(con, fonte, df: pd.DataFrame, chave: str, motivo: pd.Series, run_id: str):
    con.execute("""CREATE TABLE IF NOT EXISTS silver_quarentena (
        fonte TEXT, chave_registro TEXT, motivo TEXT, registro_json TEXT, run_id TEXT)""")
    con.execute("DELETE FROM silver_quarentena WHERE fonte = ?", (fonte,))
    if df.empty:
        return 0
    rows = [(fonte, str(r[chave]), motivo.loc[i], json.dumps(r.to_dict(), ensure_ascii=False, default=str), run_id)
            for i, r in df.iterrows()]
    con.executemany("INSERT INTO silver_quarentena VALUES (?,?,?,?,?)", rows)
    return len(rows)


def _salvar(con, df: pd.DataFrame, tabela: str, run_id: str):
    df = df.copy()
    df["_run_id"] = run_id
    df.to_sql(tabela, con, if_exists="replace", index=False)


def _float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False).replace({"None": None, "": None}),
                         errors="coerce")


# ---------------------------------------------------------------- dimensões de apoio
def tratar_subprefeituras_poi(**context):
    ds, run_id = contexto_execucao(context)
    with conectar() as con:
        sub = _bronze(con, "subprefeituras").rename(columns={"codigo": "cod_subprefeitura",
                                                             "lat_centroide": "lat", "lon_centroide": "lon"})
        sub["lat"], sub["lon"] = _float(sub["lat"]), _float(sub["lon"])
        sub["chave_nome"] = sub["nome"].map(chave_texto)
        sub = sub[["cod_subprefeitura", "nome", "zona", "lat", "lon", "chave_nome"]].drop_duplicates("cod_subprefeitura")
        _salvar(con, sub, "silver_subprefeitura", run_id)

        poi = _bronze(con, "pontos_interesse")
        poi["latitude"], poi["longitude"] = _float(poi["latitude"]), _float(poi["longitude"])
        ok = [coord_valida(a, b) for a, b in zip(poi["latitude"], poi["longitude"])]
        poi = poi[ok].drop_duplicates("id_poi")
        poi["cod_subprefeitura"] = _subpref_mais_proxima(poi["latitude"], poi["longitude"], sub)
        _salvar(con, poi[["id_poi", "tipo", "nome", "latitude", "longitude", "cod_subprefeitura"]], "silver_poi", run_id)
        registrar_execucao(con, run_id, "silver.subprefeituras_poi", "sucesso", len(sub) + len(poi))
    log.info("silver_subprefeitura=%d  silver_poi=%d", len(sub), len(poi))


def _subpref_mais_proxima(lats, lons, sub: pd.DataFrame) -> list:
    cent = list(zip(sub["cod_subprefeitura"], sub["lat"], sub["lon"]))
    out = []
    for la, lo in zip(lats, lons):
        if pd.isna(la) or pd.isna(lo):
            out.append(None)
            continue
        out.append(min(cent, key=lambda c: haversine_m(la, lo, c[1], c[2]))[0])
    return out


def _mapear_subprefeitura(nomes: pd.Series, sub: pd.DataFrame) -> pd.Series:
    mapa = dict(zip(sub["chave_nome"], sub["cod_subprefeitura"]))
    chaves = list(mapa)

    def resolve(n):
        k = chave_texto(n)
        if k in mapa:
            return mapa[k]
        prox = difflib.get_close_matches(k, chaves, n=1, cutoff=0.85)
        return mapa[prox[0]] if prox else None

    return nomes.map(resolve)


# ---------------------------------------------------------------- SP156
def tratar_sp156(**context):
    ds, run_id = contexto_execucao(context)
    with conectar() as con:
        sub = pd.read_sql("SELECT * FROM silver_subprefeitura", con)
        df = _bronze(con, "sp156")
        n0 = len(df)

        df["status"] = df["status"].str.strip().str.upper()
        ordem = {"ABERTA": 1, "EM ANDAMENTO": 2, "FINALIZADA": 3, "CANCELADA": 3}
        df["_ordem"] = df["status"].map(ordem).fillna(0)
        # dedup: mantém a versão mais avançada do protocolo
        df = df.sort_values(["protocolo", "_ordem"]).drop_duplicates("protocolo", keep="last")
        dups = n0 - len(df)

        iso = pd.to_datetime(df["data_abertura"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
        br = pd.to_datetime(df["data_abertura"], format="%d/%m/%Y %H:%M", errors="coerce")
        df["dt_abertura"] = iso.fillna(br)
        df["dt_conclusao"] = pd.to_datetime(df["data_conclusao"].replace("", None), errors="coerce")
        df["cod_subprefeitura"] = _mapear_subprefeitura(df["subprefeitura"], sub)

        df["latitude"], df["longitude"] = _float(df["latitude"]), _float(df["longitude"])
        df["coord_valida"] = [int(coord_valida(a, b)) for a, b in zip(df["latitude"], df["longitude"])]
        df.loc[df["coord_valida"] == 0, ["latitude", "longitude"]] = None

        s = df["servico"].str.lower()
        df["categoria_servico"] = "outros"
        df.loc[s.str.contains("buraco|danificada"), "categoria_servico"] = "defeito_pavimento"
        df.loc[s.str.contains("tampa"), "categoria_servico"] = "tampa_concessionaria"
        df.loc[s.str.contains("obstru"), "categoria_servico"] = "obstrucao"
        df.loc[s.str.contains("guia"), "categoria_servico"] = "acessibilidade_guia"
        df["em_escopo_modular"] = (df["categoria_servico"] == "defeito_pavimento").astype(int)

        df["dias_ate_conclusao"] = (df["dt_conclusao"] - df["dt_abertura"]).dt.days

        motivo = pd.Series(None, index=df.index, dtype=object)
        motivo[df["dt_abertura"].isna()] = "data_abertura_invalida"
        motivo[df["cod_subprefeitura"].isna()] = "subprefeitura_nao_identificada"
        ruins = motivo.notna()
        nq = _quarentena(con, "sp156", df[ruins], "protocolo", motivo, run_id)
        df = df[~ruins]

        for c in ("dt_abertura", "dt_conclusao"):
            df[c] = df[c].dt.strftime("%Y-%m-%d %H:%M:%S")
        cols = ["protocolo", "dt_abertura", "dt_conclusao", "cod_subprefeitura", "servico", "categoria_servico",
                "em_escopo_modular", "logradouro", "latitude", "longitude", "coord_valida", "status", "dias_ate_conclusao"]
        _salvar(con, df[cols], "silver_sp156", run_id)
        registrar_execucao(con, run_id, "silver.sp156", "sucesso", len(df),
                           f"duplicatas={dups}; quarentena={nq}; coord_invalidas={int((df['coord_valida'] == 0).sum())}")
    log.info("silver_sp156: %d -> %d linhas | duplicatas removidas=%d | quarentena=%d | coord. inválidas anuladas=%d",
             n0, len(df), dups, nq, int((df["coord_valida"] == 0).sum()))


# ---------------------------------------------------------------- relatos do app
def tratar_relatos(**context):
    ds, run_id = contexto_execucao(context)
    with conectar() as con:
        sub = pd.read_sql("SELECT * FROM silver_subprefeitura", con)
        df = _bronze(con, "relatos_app")
        n0 = len(df)
        df = df.drop_duplicates("id_relato")
        dups = n0 - len(df)

        df = df.rename(columns={"geo_lat": "latitude", "geo_lon": "longitude", "medidas_comprimento_cm": "comprimento_cm",
                                "medidas_largura_cm": "largura_cm", "medidas_profundidade_cm": "profundidade_cm"})
        for c in ("latitude", "longitude", "comprimento_cm", "largura_cm", "profundidade_cm", "confirmacoes"):
            df[c] = _float(df[c])
        df["criado_em"] = pd.to_datetime(df["criado_em"], errors="coerce", utc=True).dt.tz_convert("America/Sao_Paulo")
        df["tipo_dano"] = df["tipo_dano"].str.strip().str.lower()

        flags = pd.Series("", index=df.index)
        mm = df["profundidade_cm"] > 30            # ninguém relata buraco de >30 cm em calçada: foi digitado em mm
        df.loc[mm, "profundidade_cm"] = df.loc[mm, "profundidade_cm"] / 10
        flags[mm] += "profundidade_convertida_mm;"
        for c in ("comprimento_cm", "largura_cm", "profundidade_cm"):
            neg = df[c] <= 0
            df.loc[neg, c] = None
            flags[neg] += f"{c}_invalido;"
        incompleto = df[["comprimento_cm", "largura_cm", "profundidade_cm"]].isna().any(axis=1)
        flags[incompleto] += "medida_incompleta;"

        mapa_bool = {"sim": 1, "true": 1, "nao": 0, "false": 0}
        df["base_firme"] = df["base_firme"].astype(str).str.lower().map(mapa_bool)   # 'nao_sei'/None -> NULL
        df["tampa_proxima"] = df["tampa_proxima"].astype(str).str.lower().map(mapa_bool).fillna(0).astype(int)
        df["area_cm2"] = (df["comprimento_cm"] * df["largura_cm"]).round(1)
        df["flags_qualidade"] = flags.replace("", None)

        motivo = pd.Series(None, index=df.index, dtype=object)
        ok_coord = pd.Series([coord_valida(a, b) for a, b in zip(df["latitude"], df["longitude"])], index=df.index)
        motivo[~ok_coord] = "coordenada_fora_de_sp"
        motivo[df["criado_em"].isna()] = "data_invalida"
        ruins = motivo.notna()
        nq = _quarentena(con, "relatos_app", df[ruins], "id_relato", motivo, run_id)
        df = df[~ruins].copy()

        df["cod_subprefeitura"] = _subpref_mais_proxima(df["latitude"], df["longitude"], sub)
        df["data_relato"] = df["criado_em"].dt.strftime("%Y-%m-%d")
        df["criado_em"] = df["criado_em"].dt.strftime("%Y-%m-%d %H:%M:%S")
        df["protocolo_sp156"] = df["protocolo_sp156"].replace({"None": None})
        cols = ["id_relato", "criado_em", "data_relato", "protocolo_sp156", "latitude", "longitude", "cod_subprefeitura",
                "tipo_dano", "comprimento_cm", "largura_cm", "profundidade_cm", "area_cm2", "base_firme", "tampa_proxima",
                "confirmacoes", "foto_url", "usuario_hash", "flags_qualidade"]
        _salvar(con, df[cols], "silver_relatos", run_id)
        registrar_execucao(con, run_id, "silver.relatos", "sucesso", len(df),
                           f"duplicatas={dups}; quarentena={nq}; corrigidos_mm={int(mm.sum())}")
    log.info("silver_relatos: %d -> %d | duplicatas=%d | quarentena=%d | profundidade mm->cm=%d | medidas incompletas=%d",
             n0, len(df), dups, nq, int(mm.sum()), int(incompleto.sum()))


# ---------------------------------------------------------------- ensaios de bancada
def tratar_ensaios(**context):
    ds, run_id = contexto_execucao(context)
    with conectar() as con:
        df = _bronze(con, "ensaios_bancada")
        df = df.rename(columns={"material_estrutura": "material"})
        for c in ("infill_pct", "espessura_placa_mm", "espessura_borracha_mm", "carga_kgf", "valor"):
            df[c] = _float(df[c])          # trata vírgula decimal ("2,65")
        df["data_ensaio"] = pd.to_datetime(df["data_ensaio"], errors="coerce").dt.strftime("%Y-%m-%d")
        df = df.drop_duplicates(["corpo_prova", "ensaio"])
        cols = ["versao_modulo", "corpo_prova", "material", "padrao_celula", "infill_pct", "espessura_placa_mm",
                "espessura_borracha_mm", "ensaio", "carga_kgf", "valor", "unidade", "data_ensaio"]
        _salvar(con, df[cols], "silver_ensaios", run_id)
        registrar_execucao(con, run_id, "silver.ensaios", "sucesso", len(df))
    log.info("silver_ensaios: %d medições de %d corpos de prova", len(df), df["corpo_prova"].nunique())
