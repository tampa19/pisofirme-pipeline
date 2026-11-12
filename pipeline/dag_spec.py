"""
Definição ÚNICA do grafo de tarefas do pipeline.

É usada tanto pela DAG do Airflow (dags/pisofirme_pipeline_dag.py) quanto pelo
executor local (run_local.py), garantindo que os dois rodem exatamente o mesmo fluxo.
O prefixo antes do ponto vira o TaskGroup no Airflow.
"""
from functools import partial

from pipeline import gold, ingestao, publicacao, qualidade, silver

FONTES = ["sp156", "relatos_app", "pontos_interesse", "subprefeituras", "ensaios_bancada"]

# task_id -> (função, [dependências])
TAREFAS = {
    "verificar_fontes": (ingestao.verificar_fontes, []),
    **{f"ingestao.{f}": (partial(ingestao.ingerir_fonte, f), ["verificar_fontes"]) for f in FONTES},
    "qualidade.validar_bronze": (qualidade.validar_bronze, [f"ingestao.{f}" for f in FONTES]),
    "silver.subprefeituras_poi": (silver.tratar_subprefeituras_poi, ["qualidade.validar_bronze"]),
    "silver.sp156": (silver.tratar_sp156, ["silver.subprefeituras_poi"]),
    "silver.relatos": (silver.tratar_relatos, ["silver.subprefeituras_poi"]),
    "silver.ensaios": (silver.tratar_ensaios, ["qualidade.validar_bronze"]),
    "gold.dimensoes": (gold.construir_dimensoes, ["silver.sp156", "silver.relatos"]),
    "gold.fatos": (gold.construir_fatos, ["gold.dimensoes"]),
    "gold.marts": (gold.construir_marts, ["gold.fatos", "silver.ensaios"]),
    "qualidade.validar_gold": (qualidade.validar_gold, ["gold.marts"]),
    "publicacao.exportar_gold": (publicacao.exportar_gold, ["qualidade.validar_gold"]),
    "publicacao.publicar_mvp": (publicacao.publicar_mvp, ["qualidade.validar_gold"]),
}


def ordem_topologica() -> list[str]:
    feitos, ordem = set(), []
    pendentes = dict(TAREFAS)
    while pendentes:
        prontos = [t for t, (_, deps) in pendentes.items() if all(d in feitos for d in deps)]
        if not prontos:
            raise ValueError("Ciclo detectado no grafo de tarefas")
        for t in prontos:
            ordem.append(t)
            feitos.add(t)
            pendentes.pop(t)
    return ordem
