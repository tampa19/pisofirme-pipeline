"""
Executor local do pipeline (sem Airflow) — útil para desenvolvimento e para a banca.

Roda EXATAMENTE as mesmas tarefas e dependências da DAG (pipeline/dag_spec.py),
em ordem topológica, com logs no mesmo formato do Airflow.

Uso:
    python run_local.py                 # data de referência = hoje
    python run_local.py --ds 2026-11-12
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timezone

from pipeline.dag_spec import TAREFAS, ordem_topologica
from pipeline.utils import log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", default=date.today().isoformat())
    args = ap.parse_args()
    run_id = f"local__{args.ds}T{datetime.now(timezone.utc).strftime('%H:%M:%S')}"
    ordem = ordem_topologica()
    log.info("DAG pisofirme_pipeline_calcadas | run_id=%s | %d tarefas", run_id, len(ordem))
    inicio = time.time()
    for i, task_id in enumerate(ordem, 1):
        funcao, deps = TAREFAS[task_id]
        log.info("──── [%02d/%d] INICIANDO %s  (depende de: %s)", i, len(ordem), task_id, ", ".join(deps) or "—")
        t0 = time.time()
        try:
            funcao(ds=args.ds, run_id=run_id)
        except Exception as e:  # noqa: BLE001
            log.error("TAREFA %s FALHOU: %s", task_id, e)
            log.error("Pipeline interrompido. Tarefas seguintes marcadas como upstream_failed.")
            sys.exit(1)
        log.info("──── [%02d/%d] SUCESSO   %s  (%.2fs)", i, len(ordem), task_id, time.time() - t0)
    log.info("DAG concluída com sucesso: %d/%d tarefas em %.1fs", len(ordem), len(ordem), time.time() - inicio)


if __name__ == "__main__":
    main()
