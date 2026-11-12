"""Testes automatizados: grafo da DAG, regras de limpeza e execução ponta a ponta em pasta temporária."""
import shutil
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from pipeline import config
from pipeline.dag_spec import TAREFAS, ordem_topologica
from pipeline.silver import _mapear_subprefeitura
from pipeline.utils import chave_texto, coord_valida

ROOT = Path(__file__).resolve().parents[1]


def test_grafo_sem_ciclos_e_dependencias_existentes():
    ordem = ordem_topologica()
    assert len(ordem) == len(TAREFAS) == 17
    for t, (_, deps) in TAREFAS.items():
        assert all(d in TAREFAS for d in deps)
        assert all(ordem.index(d) < ordem.index(t) for d in deps)


@pytest.mark.parametrize("variante", ["M BOI MIRIM", " M'Boi Mirim ", "m'boi mirim", "M'Boi Mirim"])
def test_variacoes_de_nome_de_subprefeitura(variante):
    sub = pd.DataFrame({"cod_subprefeitura": ["SP11", "SP29"], "chave_nome": [chave_texto("M'Boi Mirim"), chave_texto("Sé")]})
    assert _mapear_subprefeitura(pd.Series([variante]), sub).iloc[0] == "SP11"


def test_nome_com_barra_e_sem_acento():
    sub = pd.DataFrame({"cod_subprefeitura": ["SP27"], "chave_nome": [chave_texto("Vila Maria/Vila Guilherme")]})
    assert _mapear_subprefeitura(pd.Series(["VILA MARIA / VILA GUILHERME"]), sub).iloc[0] == "SP27"


def test_coordenadas():
    assert coord_valida(-23.55, -46.63)
    assert not coord_valida(0, 0)
    assert not coord_valida(-22.9, -43.2)     # Rio de Janeiro
    assert not coord_valida(None, None)


@pytest.fixture
def ambiente_temporario(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "data" / "landing", tmp_path / "data" / "landing")
    monkeypatch.setattr(config, "LANDING", tmp_path / "data" / "landing")
    monkeypatch.setattr(config, "RAW", tmp_path / "data" / "raw")
    monkeypatch.setattr(config, "WAREHOUSE", tmp_path / "data" / "warehouse" / "teste.db")
    monkeypatch.setattr(config, "GOLD_EXPORT", tmp_path / "data" / "gold")
    monkeypatch.setattr(config, "MVP_DIR", tmp_path / "mvp")
    monkeypatch.setattr(config, "PROJECT_HOME", tmp_path)
    return tmp_path


def test_pipeline_ponta_a_ponta(ambiente_temporario):
    for t in ordem_topologica():
        TAREFAS[t][0](ds="2026-11-12", run_id="teste")
    con = sqlite3.connect(config.WAREHOUSE)
    q = lambda s: con.execute(s).fetchone()[0]
    assert q("SELECT COUNT(*) FROM dq_resultados WHERE status = 'FALHA'") == 0
    assert q("SELECT COUNT(*) FROM fato_solicitacao_sp156") == q("SELECT COUNT(DISTINCT protocolo) FROM bronze_sp156")
    assert q("SELECT MAX(profundidade_cm) FROM fato_ocorrencia") <= 30
    assert q("SELECT COUNT(*) FROM mart_fila_reparo WHERE elegivel_modulo = 1") > 0
    assert q("""SELECT COUNT(*) FROM mart_fila_reparo m JOIN fato_ocorrencia f USING(id_relato)
                WHERE m.elegivel_modulo = 1 AND (f.base_firme <> 1 OR f.tampa_proxima = 1)""") == 0
    assert q("SELECT COUNT(*) FROM mart_especificacao_modulo") == q("SELECT SUM(elegivel_modulo) FROM mart_fila_reparo")
    assert (ambiente_temporario / "mvp" / "dados.js").exists()


def test_reprocessamento_idempotente(ambiente_temporario):
    for _ in range(2):
        for t in ordem_topologica():
            TAREFAS[t][0](ds="2026-11-12", run_id="teste")
    con = sqlite3.connect(config.WAREHOUSE)
    n_bronze = con.execute("SELECT COUNT(*) FROM bronze_sp156").fetchone()[0]
    assert n_bronze == 3310   # mesmo _ds reprocessado não duplica
