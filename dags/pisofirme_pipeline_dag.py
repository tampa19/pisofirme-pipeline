"""
DAG do Airflow — Pipeline de Dados do MVP PisoFirme SP (CitizenTech)

Fluxo:  verificar_fontes
          -> [ingestao: 5 fontes em paralelo]  (landing -> raw imutável -> bronze)
          -> qualidade.validar_bronze
          -> [silver: limpeza e padronização]
          -> [gold: dimensões -> fatos -> marts]  (ELT em SQL no warehouse)
          -> qualidade.validar_gold
          -> [publicacao: CSVs gold + dados do painel do MVP]

O grafo é definido uma única vez em pipeline/dag_spec.py.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.task_group import TaskGroup

# permite importar o pacote "pipeline" (raiz do projeto montada em /opt/airflow/project)
PROJETO = Path("/opt/airflow/project")
if PROJETO.exists() and str(PROJETO) not in sys.path:
    sys.path.insert(0, str(PROJETO))

from pipeline.dag_spec import TAREFAS  # noqa: E402

default_args = {
    "owner": "equipe-pisofirme",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "execution_timeout": timedelta(minutes=30),
}

with DAG(
    dag_id="pisofirme_pipeline_calcadas",
    description="Coleta, trata e modela dados de defeitos em calçadas para o MVP PisoFirme SP",
    start_date=pendulum.datetime(2026, 11, 1, tz="America/Sao_Paulo"),
    schedule="0 6 * * *",          # todo dia às 06h (antes das equipes de campo saírem)
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["citizentech", "calcadas", "elt", "mvp"],
    doc_md=__doc__,
) as dag:
    grupos: dict[str, TaskGroup] = {}
    operadores: dict[str, PythonOperator] = {}

    for task_id, (funcao, _) in TAREFAS.items():
        if "." in task_id:
            nome_grupo, nome_task = task_id.split(".", 1)
            if nome_grupo not in grupos:
                grupos[nome_grupo] = TaskGroup(group_id=nome_grupo, dag=dag)
            operadores[task_id] = PythonOperator(task_id=nome_task, python_callable=funcao,
                                                 task_group=grupos[nome_grupo], dag=dag)
        else:
            operadores[task_id] = PythonOperator(task_id=task_id, python_callable=funcao, dag=dag)

    for task_id, (_, dependencias) in TAREFAS.items():
        for dep in dependencias:
            operadores[dep] >> operadores[task_id]
