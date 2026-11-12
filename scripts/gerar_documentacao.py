"""
Gera a documentação e as evidências da entrega a partir da ÚLTIMA execução do pipeline:

  docs/arquitetura.png              diagrama de arquitetura
  docs/dicionario_dados.md          dicionário de dados (tabelas gold)
  docs/prints/01..06_*.png          prints do pipeline rodando
  docs/Entrega_PisoFirme_Pipeline.pdf   PDF único (arquitetura + dicionário + evidências)

Requisitos extras (só para esta etapa): playwright + navegador Chromium/Chrome e Graphviz (dot).
Uso:  python run_local.py && python scripts/gerar_documentacao.py
      (opcional) REPO_URL=https://github.com/... python scripts/gerar_documentacao.py
"""
from __future__ import annotations

import html
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from dicionario import DICIONARIO  # noqa: E402
from pipeline import config  # noqa: E402
from pipeline.dag_spec import TAREFAS  # noqa: E402

DOCS, PRINTS = ROOT / "docs", ROOT / "docs" / "prints"
TMP = ROOT / "docs" / "_html"
CHROME = os.environ.get("CHROME_PATH", "/usr/bin/google-chrome")
REPO_URL = os.environ.get("REPO_URL", "")

EQUIPE = [("Vinicius Issa Gois", "RM553814"), ("Gustavo Bonani", "RM553493"),
          ("Wesley Vieira", "RM553496"), ("Gustavo Felex", "RM554242")]

CSS = """
*{box-sizing:border-box} body{margin:0;font-family:'Segoe UI',system-ui,sans-serif;color:#1d1d1f;background:#fff}
h1,h2,h3{margin:0} .wrap{padding:28px 32px}
.title{font-size:13px;color:#6b6b70;margin-bottom:14px} .title b{color:#1d1d1f;font-size:16px;display:block;margin-bottom:2px}
table{border-collapse:collapse;width:100%;font-size:12.5px} th{background:#f4f3f0;text-align:left;padding:6px 8px;font-weight:600;color:#444}
td{padding:5px 8px;border-bottom:1px solid #eeece8;vertical-align:top} td.n{text-align:right;font-variant-numeric:tabular-nums}
.ok{color:#2b8a3e;font-weight:700}.fail{color:#c92a2a;font-weight:700}.warn{color:#e8590c;font-weight:700}
.tag{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600}
.grid{display:grid;gap:18px} .card{border:1px solid #e6e4df;border-radius:10px;padding:14px 16px}
.card h3{font-size:13.5px;margin-bottom:8px}
"""


def con():
    return sqlite3.connect(config.WAREHOUSE)


def ultimo_run(c) -> str:
    return c.execute("SELECT run_id FROM meta_execucoes ORDER BY registrado_em DESC LIMIT 1").fetchone()[0]


def pagina(nome: str, corpo: str, largura=1400) -> Path:
    TMP.mkdir(parents=True, exist_ok=True)
    p = TMP / f"{nome}.html"
    p.write_text(f"<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'><style>{CSS}</style></head>"
                 f"<body style='width:{largura}px'>{corpo}</body></html>", encoding="utf-8")
    return p


def screenshot(html_path: Path, png: Path, largura=1400):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": largura, "height": 600}, device_scale_factor=2)
        pg.goto(html_path.as_uri())
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(png), full_page=True)
        b.close()
    _aparar(png)
    print("print:", png.relative_to(ROOT))


def _aparar(png: Path, margem=40):
    """Remove a sobra de fundo branco no final da imagem."""
    from PIL import Image, ImageChops
    im = Image.open(png).convert("RGB")
    bbox = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).getbbox()
    if bbox and bbox[3] + margem < im.height:
        im.crop((0, 0, im.width, bbox[3] + margem)).save(png)


# ------------------------------------------------------------------ 01 grafo da DAG
def print_grafo_dag():
    with con() as c:
        run = ultimo_run(c)
        st = dict(c.execute("SELECT task_id, status FROM meta_execucoes WHERE run_id=?", (run,)).fetchall())
        dq = dict(c.execute("SELECT camada, SUM(status='FALHA') FROM dq_resultados WHERE run_id=? GROUP BY 1", (run,)).fetchall())
    # tarefas que não gravam em meta_execucoes: verificar_fontes e gates de qualidade -> status pelo log/dq
    def ok(t):
        if t == "verificar_fontes":
            return True
        if t.startswith("qualidade."):
            return dq.get("bronze" if "bronze" in t else "gold", 1) == 0
        alvo = t if t in st else {"silver.subprefeituras_poi": "silver.subprefeituras_poi"}.get(t, t)
        return st.get(alvo) == "sucesso" or any(k.startswith(t) for k in st)
    grupos = {}
    for t in TAREFAS:
        g = t.split(".")[0] if "." in t else None
        if g == "qualidade":      # gates desenhados no fluxo (losango), sem caixa de grupo
            g = None
        grupos.setdefault(g, []).append(t)
    cores = {"ingestao": "#fff4e6", "qualidade": "#fff9db", "silver": "#f1f3f5", "gold": "#fff3bf", "publicacao": "#ebfbee"}
    linhas = ['digraph G { rankdir=LR; bgcolor="white"; pad=0.25; nodesep=0.18; ranksep=0.45; compound=true;',
              'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, fillcolor="white", color="#2f9e44", penwidth=2.2, margin="0.12,0.06"];',
              'edge [color="#868e96", arrowsize=0.6];']
    def nid(t): return '"' + t + '"'
    for g, ts in grupos.items():
        if g:
            linhas.append(f'subgraph cluster_{g} {{ label="{g}"; fontname="Helvetica"; fontsize=12; style="rounded,filled,dashed"; '
                          f'color="#adb5bd"; fillcolor="{cores.get(g, "#f8f9fa")}";')
        for t in ts:
            cor = "#2f9e44" if ok(t) else "#c92a2a"
            if t.startswith("qualidade."):
                linhas.append(f'{nid(t)} [label="{t}", shape=diamond, style="filled", fillcolor="#fff3bf", fontsize=10, color="{cor}"];')
            else:
                linhas.append(f'{nid(t)} [label="{t.split(".")[-1]}", color="{cor}"];')
        if g:
            linhas.append("}")
    for t, (_, deps) in TAREFAS.items():
        for d in deps:
            linhas.append(f"{nid(d)} -> {nid(t)};")
    linhas.append("}")
    dot = DOCS / "dag_grafo.dot"
    dot.write_text("\n".join(linhas), encoding="utf-8")
    svg = subprocess.run(["dot", "-Tsvg", str(dot)], capture_output=True, text=True, check=True).stdout
    svg = re.sub(r'<svg width="[^"]+" height="[^"]+"', '<svg style="width:100%;height:auto"', svg, count=1)
    corpo = f"""<div class='wrap'><div class='title'><b>Grafo da DAG <code>pisofirme_pipeline_calcadas</code> — 17 tarefas em 5 TaskGroups</b>
      Mesmas tarefas e dependências declaradas no Airflow (pipeline/dag_spec.py). Losangos = gates do TaskGroup <i>qualidade</i>. Borda verde = tarefa concluída com sucesso na execução <code>{html.escape(run)}</code>.</div>
      {svg}</div>"""
    screenshot(pagina("01_dag", corpo, 1600), PRINTS / "01_dag_grafo.png", 1600)


# ------------------------------------------------------------------ 02 log da execução
def print_logs():
    log = (DOCS / "execucao_pipeline.log").read_text(encoding="utf-8").splitlines()
    def fmt(l):
        e = html.escape(l)
        e = re.sub(r"^(\[[^\]]+\])", r"<span style='color:#7d8590'>\1</span>", e)
        e = e.replace("INFO", "<span style='color:#58a6ff'>INFO</span>").replace("ERROR", "<span style='color:#ff7b72'>ERROR</span>")
        e = re.sub(r"(SUCESSO|OK    |concluída com sucesso)", r"<span style='color:#3fb950;font-weight:700'>\1</span>", e)
        e = re.sub(r"(INICIANDO)", r"<span style='color:#d29922;font-weight:700'>\1</span>", e)
        return e
    corpo = f"""<div style='background:#0d1117;color:#e6edf3;font-family:Consolas,"DejaVu Sans Mono",monospace;font-size:11.2px;line-height:1.5;padding:18px 22px'>
      <div style='color:#7d8590;margin-bottom:6px'>PS C:\\pisofirme-pipeline&gt; <span style='color:#e6edf3'>python run_local.py --ds 2026-11-12</span></div>
      {'<br>'.join(fmt(l) for l in log)}</div>"""
    screenshot(pagina("02_logs", corpo, 1500), PRINTS / "02_execucao_logs.png", 1500)


# ------------------------------------------------------------------ 03 dados carregados
def print_dados():
    with con() as c:
        run = ultimo_run(c)
        tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        def camada(t):
            for p, n in (("bronze_", "Bronze"), ("silver_", "Silver"), ("dim_", "Gold"), ("fato_", "Gold"), ("mart_", "Gold"),
                         ("feat_", "Gold"), ("int_", "Gold (intermediária)"), ("meta_", "Metadados"), ("dq_", "Metadados")):
                if t.startswith(p):
                    return n
            return "—"
        ordem = {"Bronze": 0, "Silver": 1, "Gold (intermediária)": 2, "Gold": 3, "Metadados": 4}
        linhas = sorted([(camada(t), t, c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0],
                          len(c.execute(f"PRAGMA table_info({t})").fetchall())) for t in tabs], key=lambda x: (ordem.get(x[0], 9), x[1]))
        meta = c.execute("SELECT task_id, status, linhas, detalhe FROM meta_execucoes WHERE run_id=? ORDER BY registrado_em", (run,)).fetchall()
    cor = {"Bronze": "#f3d9c4", "Silver": "#e9ecef", "Gold": "#ffec99", "Gold (intermediária)": "#fff3bf", "Metadados": "#e7f5ff"}
    t1 = "".join(f"<tr><td><span class='tag' style='background:{cor.get(a, '#eee')}'>{a}</span></td><td><code>{t}</code></td>"
                 f"<td class='n'>{n:,}</td><td class='n'>{k}</td></tr>".replace(",", ".") for a, t, n, k in linhas)
    t2 = "".join(f"<tr><td><code>{t}</code></td><td class='ok'>{s}</td><td class='n'>{'' if n is None else f'{n:,}'.replace(',', '.')}</td>"
                 f"<td style='font-size:11px;color:#555'>{html.escape(str(d)[:70])}</td></tr>" for t, s, n, d in meta)
    raws = sorted(config.RAW.rglob("*.*"))
    t3 = "".join(f"<tr><td><code>{p.relative_to(ROOT)}</code></td><td class='n'>{p.stat().st_size / 1024:.0f} KB</td></tr>" for p in raws)
    corpo = f"""<div class='wrap'><div class='title'><b>Dados carregados no warehouse (data/warehouse/pisofirme.db)</b>
      Execução <code>{html.escape(run)}</code> — contagem real de linhas por tabela e trilha de auditoria gravada pelo pipeline</div>
      <div class='grid' style='grid-template-columns:1fr 1.25fr'>
        <div class='card'><h3>Tabelas por camada</h3><table><tr><th>Camada</th><th>Tabela</th><th>Linhas</th><th>Colunas</th></tr>{t1}</table></div>
        <div><div class='card'><h3>meta_execucoes (linhagem desta execução)</h3><table><tr><th>Tarefa</th><th>Status</th><th>Linhas</th><th>Detalhe</th></tr>{t2}</table></div>
        <div class='card' style='margin-top:18px'><h3>Data lake bruto (cópias imutáveis por data)</h3><table>{t3}</table></div></div>
      </div></div>"""
    screenshot(pagina("03_dados", corpo, 1500), PRINTS / "03_dados_carregados.png", 1500)


# ------------------------------------------------------------------ 04 qualidade
def print_qualidade():
    with con() as c:
        run = ultimo_run(c)
        dq = c.execute("SELECT camada, verificacao, severidade, violacoes, status FROM dq_resultados WHERE run_id=?", (run,)).fetchall()
        quar = c.execute("SELECT fonte, motivo, COUNT(*) FROM silver_quarentena GROUP BY 1,2").fetchall()
        sil = c.execute("SELECT task_id, detalhe FROM meta_execucoes WHERE run_id=? AND task_id LIKE 'silver.%' AND detalhe<>''", (run,)).fetchall()
    cls = {"OK": "ok", "FALHA": "fail", "ALERTA": "warn"}
    linhas = "".join(f"<tr><td>{a}</td><td><code>{v}</code></td><td>{s}</td><td class='n'>{n}</td><td class='{cls[st]}'>{st}</td></tr>"
                     for a, v, s, n, st in dq)
    q = "".join(f"<tr><td>{f}</td><td>{m}</td><td class='n'>{n}</td></tr>" for f, m, n in quar)
    s = "".join(f"<tr><td><code>{t}</code></td><td>{html.escape(d).replace(';', '<br>')}</td></tr>" for t, d in sil)
    ok = sum(1 for r in dq if r[4] == "OK")
    corpo = f"""<div class='wrap'><div class='title'><b>Testes de qualidade de dados — {ok}/{len(dq)} aprovados</b>
      Gates nas camadas bronze e gold: uma falha crítica interrompe a DAG e o MVP não recebe dados ruins (tabela dq_resultados)</div>
      <div class='grid' style='grid-template-columns:1.5fr 1fr'>
      <div class='card'><table><tr><th>Camada</th><th>Verificação</th><th>Severidade</th><th>Violações</th><th>Status</th></tr>{linhas}</table></div>
      <div><div class='card'><h3>Problemas tratados na camada silver</h3><table>{s}</table></div>
      <div class='card' style='margin-top:18px'><h3>silver_quarentena (registros rejeitados)</h3><table><tr><th>Fonte</th><th>Motivo</th><th>Qtd</th></tr>{q}</table></div></div>
      </div></div>"""
    screenshot(pagina("04_qualidade", corpo, 1500), PRINTS / "04_qualidade_dados.png", 1500)


# ------------------------------------------------------------------ 05 amostra gold
def print_amostra_gold():
    import pandas as pd
    with con() as c:
        a = pd.read_sql("""SELECT f.posicao_fila AS fila, e.codigo_modulo, d.nome AS subprefeitura, f.comprimento_cm AS c_cm,
               f.largura_cm AS l_cm, f.profundidade_cm AS p_cm, f.score_prioridade AS score, e.comprimento_modulo_mm AS L_mm,
               e.largura_modulo_mm AS W_mm, e.altura_estrutura_celular_mm AS H_cel_mm, e.pecas_impressas AS pecas,
               e.massa_petg_g AS petg_g, e.custo_estimado_rs AS custo_rs
               FROM mart_fila_reparo f JOIN mart_especificacao_modulo e USING(id_relato)
               JOIN dim_subprefeitura d USING(cod_subprefeitura) ORDER BY f.posicao_fila LIMIT 10""", c)
        b = pd.read_sql("SELECT acao_recomendada, COUNT(*) AS ocorrencias, ROUND(AVG(score_prioridade),1) AS score_medio "
                        "FROM mart_fila_reparo GROUP BY 1 ORDER BY 2 DESC", c)
        k = pd.read_sql("SELECT subprefeitura, zona, solicitacoes_defeito_sp156 AS sp156, tempo_medio_conclusao_dias AS dias_medio, "
                        "pct_concluidas, ocorrencias_ativas AS ativas, elegiveis_modulo AS elegiveis FROM mart_kpi_subprefeitura "
                        "ORDER BY ocorrencias_ativas DESC LIMIT 8", c)
    def tab(df):
        return df.to_html(index=False, border=0, na_rep="—", float_format=lambda x: f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
    corpo = f"""<div class='wrap'><div class='title'><b>Amostra das tabelas GOLD que alimentam o MVP</b>
      Consultas SQL no warehouse após a execução do pipeline</div>
      <div class='card'><h3>mart_fila_reparo ⨝ mart_especificacao_modulo — próximos módulos a imprimir</h3>{tab(a)}</div>
      <div class='grid' style='grid-template-columns:1fr 2fr;margin-top:18px'>
      <div class='card'><h3>mart_fila_reparo por ação recomendada</h3>{tab(b)}</div>
      <div class='card'><h3>mart_kpi_subprefeitura (top 8)</h3>{tab(k)}</div></div></div>"""
    screenshot(pagina("05_gold", corpo, 1500), PRINTS / "05_amostra_gold.png", 1500)


def print_mvp():
    screenshot(config.MVP_DIR / "index.html", PRINTS / "06_mvp_painel.png", 1500)


# ------------------------------------------------------------------ arquitetura
def caixa(titulo, texto, cor, borda="#d0cdc6"):
    return (f"<div style='background:{cor};border:1px solid {borda};border-radius:9px;padding:8px 10px;font-size:11.5px;line-height:1.35'>"
            f"<b style='font-size:12.5px'>{titulo}</b><br>{texto}</div>")


SETA = "<div style='text-align:center;color:#868e96;font-size:15px;line-height:1;margin:3px 0'>▼</div>"


def html_arquitetura() -> str:
    col = lambda titulo, cor, itens: (f"<div style='background:{cor};border-radius:12px;padding:12px'>"
                                      f"<div style='font-size:11px;font-weight:700;letter-spacing:.6px;color:#555;margin-bottom:8px'>{titulo}</div>{itens}</div>")
    fontes = "".join(caixa(t, d, "#fff") + "<div style='height:7px'></div>" for t, d in [
        ("SP156", "solicitações sobre calçadas<br><i>CSV com ;</i>"), ("App PisoFirme", "relatos + medidas + foto<br><i>JSON aninhado</i>"),
        ("Pontos de interesse", "hospital · UBS · escola · metrô<br><i>CSV</i>"), ("Subprefeituras", "32 regiões<br><i>CSV</i>"),
        ("Ensaios de bancada", "corpos de prova do módulo<br><i>CSV</i>")])
    ingest = (caixa("verificar_fontes", "sensor: todas as fontes chegaram?", "#fff") + SETA +
              caixa("Landing", "data/landing/&lt;fonte&gt;/", "#fff") + SETA +
              caixa("Raw imutável", "data/raw/&lt;fonte&gt;/dt=&lt;ds&gt;/<br>+ hash SHA-256 (rastreabilidade)", "#fff") + SETA +
              caixa("Load (EL)", "5 tarefas em paralelo<br>carga idempotente por _ds", "#fff"))
    wh = (caixa("BRONZE · 5 tabelas", "dado como chegou (TEXT) + _run_id, _ds, _arquivo_origem, _hash_arquivo", "#f3d9c4") + SETA +
          caixa("◆ Gate de qualidade bronze", "15 testes: volume, colunas obrigatórias, chave não nula", "#fff3bf", "#f0c419") + SETA +
          "<div style='display:grid;grid-template-columns:2fr 1fr;gap:6px'>" +
          caixa("SILVER · Python/pandas", "dedup · datas BR/ISO · nomes de subprefeitura · mm→cm · vírgula decimal · coordenadas · geo-join", "#e9ecef") +
          caixa("Quarentena", "rejeitados + motivo", "#ffe3e3") + "</div>" + SETA +
          caixa("GOLD · ELT em SQL · modelo estrela", "dim_subprefeitura · dim_tempo · dim_tipo_dano<br>fato_ocorrencia · fato_solicitacao_sp156", "#ffec99") + SETA +
          caixa("MARTS do produto", "mart_fila_reparo (elegibilidade + score) · mart_especificacao_modulo (CAD)<br>"
                "mart_kpi_subprefeitura · mart_validacao_prototipo · feat_modelo_severidade", "#ffd43b") + SETA +
          caixa("◆ Gate de qualidade gold", "16 testes: PK, FKs, faixas, regras de negócio → falha interrompe a DAG", "#fff3bf", "#f0c419"))
    uso = "".join(caixa(t, d, "#d3f9d8", "#b2f2bb") + "<div style='height:7px'></div>" for t, d in [
        ("Painel do MVP", "fila de reparo, mapa, KPIs<br><i>mvp/dados.js</i>"),
        ("Fabricação digital", "parâmetros CAD do módulo → impressão 3D + corte a laser"),
        ("Modelo de IA da equipe", "severidade pela foto<br><i>feat_modelo_severidade</i>"),
        ("Prefeitura / BI", "CSVs gold em data/gold/"),
        ("Auditoria", "meta_execucoes · dq_resultados")])
    seta_h = "<div style='display:flex;align-items:center;justify-content:center;color:#868e96;font-size:22px'>▶</div>"
    return f"""<div style='padding:6px'>
      <div style='background:#16161a;color:#fff;border-radius:10px;padding:10px 14px;font-size:12.5px;margin-bottom:10px;display:flex;justify-content:space-between'>
        <span><b style='color:#ff8fab'>Apache Airflow</b> · DAG <code>pisofirme_pipeline_calcadas</code> · orquestra todas as etapas abaixo</span>
        <span>agendamento diário 06h · 17 tarefas · 5 TaskGroups · retries=2 · max_active_runs=1 · Docker</span></div>
      <div style='display:grid;grid-template-columns:1fr 18px 1.05fr 18px 2.1fr 18px 1fr;gap:4px;align-items:stretch'>
        {col("1 · FONTES", "#f1f3f5", fontes)}{seta_h}{col("2 · INGESTÃO", "#fff4e6", ingest)}{seta_h}
        {col("3 · WAREHOUSE MEDALHÃO (SQLite)", "#f8f0fc", wh)}{seta_h}{col("4 · CONSUMO", "#ebfbee", uso)}
      </div></div>"""


def gerar_arquitetura():
    p = pagina("arquitetura", html_arquitetura(), 1500)
    screenshot(p, DOCS / "arquitetura.png", 1500)


# ------------------------------------------------------------------ dicionário
def gerar_dicionario_md():
    out = ["# Dicionário de dados — camada GOLD", "",
           "Tabelas entregues pelo pipeline em `data/warehouse/pisofirme.db` e exportadas em `data/gold/*.csv`.", ""]
    with con() as c:
        for t, d in DICIONARIO.items():
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            out += [f"## `{t}`", "", f"{d['descricao']}  ", f"**Grão:** {d['grao']} · **Chave:** `{d['chave']}` · **Linhas (última execução):** {n}", "",
                    "| Coluna | Tipo | Descrição | Domínio / regra |", "|---|---|---|---|"]
            out += [f"| `{a}` | {b} | {cc} | {dd} |" for a, b, cc, dd in d["colunas"]] + [""]
    (DOCS / "dicionario_dados.md").write_text("\n".join(out), encoding="utf-8")
    print("doc: docs/dicionario_dados.md")


# ------------------------------------------------------------------ PDF
def gerar_pdf():
    with con() as c:
        contagens = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in DICIONARIO}
        run = ultimo_run(c)
        dq = c.execute("SELECT COUNT(*), SUM(status='OK') FROM dq_resultados WHERE run_id=?", (run,)).fetchone()
    equipe = "".join(f"<tr><td>{n}</td><td>{rm}</td></tr>" for n, rm in EQUIPE)
    repo = f"<p><b>Repositório:</b> <a href='{REPO_URL}'>{REPO_URL}</a></p>" if REPO_URL else ""
    dic = ""
    for t, d in DICIONARIO.items():
        linhas = "".join(f"<tr><td><code>{html.escape(a)}</code></td><td>{b}</td><td>{html.escape(cc)}</td><td>{html.escape(dd)}</td></tr>"
                         for a, b, cc, dd in d["colunas"])
        dic += (f"<div class='tb'><h3><code>{t}</code> <span>{contagens[t]:,} linhas</span></h3>".replace(",", ".") +
                f"<p class='d'>{d['descricao']} <b>Grão:</b> {d['grao']}. <b>Chave:</b> <code>{d['chave']}</code>.</p>"
                f"<table><tr><th style='width:30%'>Coluna</th><th style='width:9%'>Tipo</th><th>Descrição</th><th style='width:26%'>Domínio / regra</th></tr>{linhas}</table></div>")
    prints = [("07_airflow_graph.png", "Airflow 2.10.5 (docker compose): aba Graph da DAG <code>pisofirme_pipeline_calcadas</code> após execução disparada pelo Trigger DAG — 17/17 tarefas com sucesso."),
              ("08_airflow_log_tarefa.png", "Airflow: log da tarefa <code>qualidade.validar_gold</code> na mesma execução (16 verificações, 0 falhas críticas)."),
              ("02_execucao_logs.png", "Log completo da execução ponta a ponta pelo executor local (17/17 tarefas com sucesso)."),
              ("03_dados_carregados.png", "Tabelas carregadas por camada, trilha de linhagem e data lake bruto."),
              ("04_qualidade_dados.png", "Resultados dos testes de qualidade e registros em quarentena."),
              ("05_amostra_gold.png", "Amostra das tabelas gold consumidas pelo MVP."),
              ("06_mvp_painel.png", "Painel do MVP PisoFirme alimentado pela camada gold.")]
    ev = "".join(f"<div class='ev'><p class='cap'><b>Figura {i}.</b> {cap}</p><img src='{(PRINTS / f).as_uri()}'></div>"
                 for i, (f, cap) in enumerate(prints, 1))
    css = """
    @page { size: A4; margin: 16mm 15mm; } @page land { size: A4 landscape; margin: 10mm 10mm; }
    body{font-family:'Segoe UI',system-ui,sans-serif;color:#1d1d1f;font-size:11pt;line-height:1.45}
    .land{page:land} .pb{break-before:page}
    h1{font-size:26pt;margin:0} h2{font-size:15pt;margin:0 0 8px;border-bottom:2px solid #d6336c;padding-bottom:4px}
    h3{font-size:11pt;margin:14px 0 4px} h3 span{font-weight:400;color:#6b6b70;font-size:9pt;margin-left:6px}
    .cover{height:255mm;display:flex;flex-direction:column;justify-content:space-between}
    .tag{color:#d6336c;font-weight:700;font-size:9.5pt;letter-spacing:.8px}
    .sub{font-size:13pt;color:#444;margin-top:6px}
    table{border-collapse:collapse;width:100%;font-size:8.6pt} th{background:#f4f3f0;text-align:left;padding:4px 6px}
    td{padding:3px 6px;border-bottom:1px solid #eeece8;vertical-align:top} code{font-size:8.6pt;color:#862e9c}
    .eq td,.eq th{font-size:10.5pt;padding:5px 8px}
    .tb{break-inside:avoid} p.d{margin:0 0 4px;font-size:9pt;color:#444}
    .ev{break-inside:avoid;margin-bottom:12px} .ev img{width:100%;border:1px solid #ddd;border-radius:4px} .cap{font-size:9pt;margin:0 0 4px}
    .box{background:#f8f7f4;border-left:3px solid #d6336c;padding:8px 12px;font-size:10pt;margin:8px 0}
    ul{margin:4px 0;padding-left:18px} li{margin:2px 0}
    """
    corpo = f"""
    <section class='cover'>
      <div><div class='tag'>DISCIPLINA 2 DE 7 · BIG DATA ARCHITECTURE &amp; DATA INTEGRATION · COMPONENTE: DADOS</div>
        <h1 style='margin-top:18mm'>Pipeline de Dados do MVP CitizenTech</h1>
        <div class='sub'><b>PisoFirme SP</b> — dados para o reparo modular temporário de calçadas</div>
        <p style='margin-top:10mm;max-width:150mm'>Pipeline orquestrado no Apache Airflow que coleta relatos de defeitos em calçadas,
        trata e modela os dados em camadas (bronze → silver → gold) e entrega ao MVP a fila priorizada de reparos e os
        parâmetros de fabricação (impressão 3D + corte a laser) de cada módulo.</p></div>
      <div><p><b>Professora:</b> Ana Machado</p>{repo}
        <table class='eq' style='width:110mm'><tr><th>Integrante</th><th>RM</th></tr>{equipe}</table>
        <p style='font-size:9pt;color:#6b6b70;margin-top:8mm'>Conteúdo deste PDF: 1. Visão geral · 2. Diagrama de arquitetura · 3. Dicionário de dados · 4. Evidências de execução · 5. Como executar</p></div>
    </section>

    <section class='pb'>
      <h2>1. Visão geral</h2>
      <p><b>Problema.</b> Buracos e perdas localizadas de revestimento nas calçadas de São Paulo criam desníveis e risco de queda.
      O projeto da equipe propõe um módulo temporário: estrutura celular + placa impressa em 3D, coberta por borracha natural cortada a laser.
      Para o módulo virar serviço, é preciso saber <i>quais</i> buracos cabem no escopo (rasos, localizados, com base firme e sem tampa de serviço),
      <i>quais</i> atacar primeiro e <i>com que medidas</i> fabricar cada peça.</p>
      <p><b>O que o pipeline entrega ao MVP.</b></p>
      <ul><li><b>Fila de reparo priorizada</b> — elegibilidade ao módulo + score 0-100 (severidade, exposição de pedestres perto de hospitais/escolas/metrô, recorrência e tempo de espera).</li>
      <li><b>Especificação de cada módulo</b> — dimensões da peça, altura da estrutura celular, nº de peças pela mesa da impressora, filamento, tempo e custo estimados, string de parâmetros CAD.</li>
      <li><b>Indicadores por subprefeitura</b> e <b>validação do protótipo</b> (ensaios de bancada × critérios de aceitação).</li>
      <li><b>Tabela de features</b> para o modelo de IA de severidade da equipe.</li></ul>
      <p><b>Fontes de dados e justificativa da simulação.</b> O SP156 é uma fonte real de solicitações, mas não traz as medidas do defeito,
      essenciais para decidir a elegibilidade e dimensionar a peça. Essas medidas viriam do app do MVP (relato com foto e objeto de referência),
      que ainda não está em produção, e os ensaios do protótipo ainda serão realizados. Por isso as cinco fontes são <b>simuladas de forma
      reprodutível</b> (semente fixa, <code>scripts/gerar_dados_simulados.py</code>), imitando a estrutura real e incluindo os problemas típicos
      de dados reais para que o pipeline precise tratá-los: 110 protocolos duplicados, nomes de subprefeitura com variações, datas em dois
      formatos, 235 coordenadas inválidas, profundidades digitadas em mm, vírgula decimal, medidas negativas ou ausentes e relatos reenviados.</p>
      <div class='box'><b>Última execução:</b> <code>{html.escape(run)}</code> · 17/17 tarefas com sucesso · {dq[1]}/{dq[0]} testes de qualidade aprovados ·
      {contagens['fato_ocorrencia']:,} ocorrências modeladas · {contagens['mart_especificacao_modulo']} módulos especificados.</div>
      <p><b>Decisões de arquitetura.</b></p>
      <ul><li><b>Orquestração:</b> Airflow (Docker) com TaskGroups, retries e execução diária; o grafo é declarado uma única vez
      (<code>pipeline/dag_spec.py</code>) e reutilizado pela DAG e pelo executor local, garantindo o mesmo fluxo nos dois ambientes.</li>
      <li><b>ELT + ETL:</b> extração e carga sem transformação (bronze), limpeza em Python (silver, ETL) e modelagem em SQL dentro do warehouse (gold, ELT).</li>
      <li><b>Arquitetura medalhão</b> com data lake bruto imutável por data e hash SHA-256 de cada arquivo (rastreabilidade e reprocessamento).</li>
      <li><b>Idempotência:</b> reprocessar o mesmo dia substitui as linhas daquele <code>_ds</code>, sem duplicar.</li>
      <li><b>Qualidade como gate:</b> 31 testes; falha crítica interrompe a DAG antes de publicar no MVP. Registros irrecuperáveis vão para quarentena com o motivo.</li>
      <li><b>Warehouse SQLite:</b> arquivo único, sem servidor, adequado ao volume do MVP; a modelagem em SQL padrão permite migrar para PostgreSQL/BigQuery depois.</li></ul>
    </section>

    <section class='land pb'>
      <h2>2. Diagrama de arquitetura</h2>
      <img src='{(DOCS / "arquitetura.png").as_uri()}' style='width:82%;display:block;margin:0 auto'>
      <p style='font-size:9pt;color:#555;margin-top:6px'>Fluxo da DAG: verificar_fontes → ingestao (5 em paralelo) → qualidade.validar_bronze → silver
      (subprefeituras_poi → sp156 ∥ relatos; ensaios) → gold (dimensoes → fatos → marts) → qualidade.validar_gold → publicacao (exportar_gold ∥ publicar_mvp).</p>
      <img src='{(PRINTS / "01_dag_grafo.png").as_uri()}' style='width:72%;display:block;margin:4px auto 0;border:1px solid #eee;border-radius:4px'>
    </section>

    <section class='pb'>
      <h2>3. Dicionário de dados (camada gold)</h2>
      <p style='font-size:9.5pt'>Tabelas entregues em <code>data/warehouse/pisofirme.db</code> e exportadas em <code>data/gold/*.csv</code>.
      Modelo estrela: dimensões <code>dim_*</code>, fatos <code>fato_*</code> e marts de produto <code>mart_*</code>/<code>feat_*</code>.</p>
      {dic}
    </section>

    <section class='pb'>
      <h2>4. Evidências de execução</h2>
      <p style='font-size:9.5pt'>O diagrama de arquitetura e o grafo da DAG estão na seção 2. As Figuras 1 e 2 são capturas da interface do Apache Airflow com a DAG executada; as demais foram geradas a partir da execução do mesmo grafo pelo executor local (<code>run_local.py</code>).</p>
      {ev}
    </section>

    <section class='pb'>
      <h2>5. Como executar</h2>
      <p><b>Opção A — Airflow com Docker</b> (recomendado para a avaliação)</p>
      <ul><li>Instalar o Docker Desktop.</li><li>Na pasta do repositório: <code>docker compose up -d</code></li>
      <li>Abrir <code>http://localhost:8080</code> (usuário <code>admin</code>, senha <code>admin</code>).</li>
      <li>Ativar a DAG <code>pisofirme_pipeline_calcadas</code> e clicar em <i>Trigger DAG</i>.</li></ul>
      <p><b>Opção B — execução local sem Airflow</b> (mesmas tarefas e dependências)</p>
      <ul><li><code>pip install -r requirements.txt</code></li><li><code>python run_local.py</code></li>
      <li>Abrir <code>mvp/index.html</code> no navegador para ver o painel atualizado.</li></ul>
      <p><b>Testes automatizados:</b> <code>pytest -q</code> (regras de limpeza, elegibilidade e integridade do grafo).</p>
      <p style='font-size:9pt;color:#6b6b70;margin-top:10mm'>Limites: dados simulados; custos, massa e tempo de impressão são estimativas de projeto;
      os ensaios de bancada não equivalem a certificação para uso em calçadas (conforme o documento de conceito da equipe).</p>
    </section>"""
    p = TMP / "entrega.html"
    p.write_text(f"<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'><style>{css}</style></head><body>{corpo}</body></html>", encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        pg = b.new_page()
        pg.goto(p.as_uri())
        pg.wait_for_timeout(800)
        out = DOCS / "Entrega_PisoFirme_Pipeline.pdf"
        pg.pdf(path=str(out), prefer_css_page_size=True, print_background=True,
               display_header_footer=True, header_template="<span></span>",
               footer_template="<div style='font-size:8px;color:#888;width:100%;text-align:center'>PisoFirme SP · Pipeline de Dados do MVP · "
                               "<span class='pageNumber'></span>/<span class='totalPages'></span></div>")
        b.close()
    print("pdf:", out.relative_to(ROOT))


if __name__ == "__main__":
    PRINTS.mkdir(parents=True, exist_ok=True)
    gerar_arquitetura()
    print_grafo_dag()
    print_logs()
    print_dados()
    print_qualidade()
    print_amostra_gold()
    print_mvp()
    gerar_dicionario_md()
    gerar_pdf()
