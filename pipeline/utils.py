"""Funções utilitárias: conexão com o warehouse, logging, normalização de texto e geo."""
from __future__ import annotations

import logging
import math
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone

from pipeline import config

log = logging.getLogger("pisofirme")
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[%(asctime)s] {%(name)s} %(levelname)s - %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


@contextmanager
def conectar():
    config.WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.WAREHOUSE)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def contexto_execucao(context: dict) -> tuple[str, str]:
    """Extrai ds (data lógica) e run_id do contexto do Airflow (ou do runner local)."""
    ds = context.get("ds") or datetime.now().strftime("%Y-%m-%d")
    run_id = context.get("run_id") or f"manual__{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    return ds, run_id


def agora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sem_acento(txt: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn")


def chave_texto(txt) -> str:
    """Chave canônica para comparar nomes: sem acento, maiúscula, só letras."""
    if txt is None:
        return ""
    t = sem_acento(str(txt)).upper()
    return "".join(c for c in t if c.isalnum())


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def coord_valida(lat, lon) -> bool:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    b = config.BBOX_SP
    return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]


def registrar_execucao(con, run_id: str, task_id: str, status: str, linhas: int | None = None, detalhe: str = ""):
    """Trilha de auditoria (linhagem simples) de cada tarefa do pipeline."""
    con.execute("""CREATE TABLE IF NOT EXISTS meta_execucoes (
        run_id TEXT, task_id TEXT, status TEXT, linhas INTEGER, detalhe TEXT, registrado_em TEXT)""")
    con.execute("INSERT INTO meta_execucoes VALUES (?,?,?,?,?,?)",
                (run_id, task_id, status, linhas, detalhe, agora_utc()))
