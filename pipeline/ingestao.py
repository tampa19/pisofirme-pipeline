"""
ETAPA 1 — INGESTÃO (Extract + Load, padrão ELT)

Para cada fonte:
 1. verifica se o arquivo chegou na landing;
 2. copia para data/raw/<fonte>/dt=<ds>/ (cópia imutável + hash SHA-256 = rastreabilidade);
 3. carrega "como veio" na camada BRONZE do warehouse (tudo como TEXT), com colunas
    técnicas de linhagem (_run_id, _ds, _arquivo_origem, _hash_arquivo, _ingerido_em).
A carga é idempotente: reprocessar o mesmo dia substitui as linhas daquele _ds.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil

from pipeline import config
from pipeline.utils import agora_utc, conectar, contexto_execucao, log, registrar_execucao


class FonteAusenteError(RuntimeError):
    pass


def verificar_fontes(**context):
    """Sensor simples: falha se alguma fonte obrigatória não chegou na landing."""
    faltando = [n for n, (arq, _) in config.FONTES.items() if not (config.LANDING / arq).exists()]
    if faltando:
        raise FonteAusenteError(f"Fontes ausentes na landing: {faltando}")
    for nome, (arq, _) in config.FONTES.items():
        p = config.LANDING / arq
        log.info("fonte OK: %-17s %8.1f KB  (%s)", nome, p.stat().st_size / 1024, arq)
    return len(config.FONTES)


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 16), b""):
            h.update(bloco)
    return h.hexdigest()


def _achatar(d: dict, prefixo: str = "") -> dict:
    """Achata JSON aninhado: {'geo': {'lat': 1}} -> {'geo_lat': 1}."""
    out = {}
    for k, v in d.items():
        chave = f"{prefixo}{k}"
        if isinstance(v, dict):
            out.update(_achatar(v, chave + "_"))
        else:
            out[chave] = v
    return out


def _ler(path, formato) -> list[dict]:
    if formato.startswith("csv"):
        delim = ";" if formato == "csv;" else ","
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f, delimiter=delim))
    with open(path, encoding="utf-8") as f:
        return [_achatar(r) for r in json.load(f)]


def ingerir_fonte(fonte: str, **context) -> int:
    ds, run_id = contexto_execucao(context)
    arq, formato = config.FONTES[fonte]
    origem = config.LANDING / arq

    destino_dir = config.RAW / fonte / f"dt={ds}"
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / origem.name
    shutil.copy2(origem, destino)
    hash_arq = _sha256(destino)
    log.info("[%s] cópia imutável em %s (sha256=%s…)", fonte, destino.relative_to(config.PROJECT_HOME), hash_arq[:12])

    registros = _ler(destino, formato)
    colunas = sorted({c for r in registros for c in r})
    tecnicas = ["_run_id", "_ds", "_arquivo_origem", "_hash_arquivo", "_ingerido_em"]
    tabela = f"bronze_{fonte}"
    with conectar() as con:
        cols_sql = ", ".join(f'"{c}" TEXT' for c in colunas + tecnicas)
        con.execute(f'CREATE TABLE IF NOT EXISTS {tabela} ({cols_sql})')
        existentes = {r[1] for r in con.execute(f"PRAGMA table_info({tabela})")}
        for c in colunas:                     # evolução de schema: novas colunas são adicionadas
            if c not in existentes:
                con.execute(f'ALTER TABLE {tabela} ADD COLUMN "{c}" TEXT')
                log.warning("[%s] schema evoluiu: nova coluna '%s'", fonte, c)
        con.execute(f"DELETE FROM {tabela} WHERE _ds = ?", (ds,))
        ts = agora_utc()
        placeholders = ", ".join("?" for _ in colunas + tecnicas)
        nomes = ", ".join(f'"{c}"' for c in colunas + tecnicas)
        linhas = [[None if r.get(c) is None else str(r.get(c)) for c in colunas]
                  + [run_id, ds, str(destino.relative_to(config.PROJECT_HOME)), hash_arq, ts] for r in registros]
        con.executemany(f"INSERT INTO {tabela} ({nomes}) VALUES ({placeholders})", linhas)
        registrar_execucao(con, run_id, f"ingestao.{fonte}", "sucesso", len(linhas), hash_arq)
    log.info("[%s] %d registros carregados em %s (ds=%s)", fonte, len(linhas), tabela, ds)
    return len(linhas)
