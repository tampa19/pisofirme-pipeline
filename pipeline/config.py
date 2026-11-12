"""Configurações centrais do pipeline PisoFirme SP."""
import os
from pathlib import Path

# Raiz do projeto: no Airflow (docker) é montada em /opt/airflow/project
PROJECT_HOME = Path(os.environ.get("PISOFIRME_HOME", Path(__file__).resolve().parents[1]))

DATA = PROJECT_HOME / "data"
LANDING = DATA / "landing"            # onde as fontes chegam (zona de pouso)
RAW = DATA / "raw"                    # cópia imutável por execução (data lake bruto)
WAREHOUSE = DATA / "warehouse" / "pisofirme.db"   # SQLite com camadas bronze/silver/gold
GOLD_EXPORT = DATA / "gold"           # exportação das tabelas gold (CSV)
MVP_DIR = PROJECT_HOME / "mvp"        # front-end do MVP que consome o gold
SQL_DIR = PROJECT_HOME / "sql"

# Fontes de dados: nome -> (arquivo na landing, formato)
FONTES = {
    "sp156": ("sp156/sp156_solicitacoes_calcadas.csv", "csv;"),
    "relatos_app": ("relatos_app/relatos_app.json", "json"),
    "pontos_interesse": ("pontos_interesse/pontos_interesse.csv", "csv"),
    "subprefeituras": ("subprefeituras/subprefeituras.csv", "csv"),
    "ensaios_bancada": ("ensaios_bancada/ensaios_bancada.csv", "csv"),
}

# Limites aproximados do município de São Paulo (validação de coordenadas)
BBOX_SP = {"lat_min": -24.01, "lat_max": -23.35, "lon_min": -46.83, "lon_max": -46.36}

# --- Regras de negócio do reparo modular (do documento de conceito do projeto) ---
ELEGIBILIDADE = {
    "profundidade_max_cm": 6.0,      # "cavidade rasa"
    "profundidade_min_cm": 1.0,      # abaixo disso é desnível leve, não cavidade
    "comprimento_max_cm": 60.0,      # "dano localizado" (cabe em 2x1 placas de impressora)
    "largura_max_cm": 40.0,
    "tipos_aceitos": ("buraco", "revestimento_solto"),
}

MODULO = {
    "folga_borda_mm": 3,             # folga lateral para encaixe
    "espessura_placa_mm": 8,         # placa superior impressa (versão de referência v0.3)
    "espessura_borracha_mm": 3,      # cobertura de borracha natural (corte a laser)
    "mesa_impressora_mm": 250,       # área útil da mesa (ex.: impressoras 256x256)
    "infill_placa": 0.45,            # paredes + preenchimento da placa superior
    "infill_celular": 0.15,          # fração ocupada pela estrutura celular giroide
    "densidade_petg_g_cm3": 1.27,
    "custo_petg_por_kg": 120.0,      # R$ (referência para estimativa)
    "custo_borracha_por_m2": 180.0,  # R$ (referência para estimativa)
    "vazao_impressao_g_h": 30.0,     # bico 0,6 mm
}

# Critérios de aceitação propostos pela equipe para os ensaios de bancada.
# Referências: NBR 9050 (desníveis até 5 mm dispensam tratamento) e valores de
# pêndulo (PTV >= 36 = baixo risco de escorregamento em piso molhado).
CRITERIOS_ENSAIO = {
    "nivel": ("<=", 5.0),
    "deformacao_residual": ("<=", 2.0),
    "deslocamento": ("<=", 3.0),
    "aderencia_seco": (">=", 36.0),
    "aderencia_molhado": (">=", 36.0),
}

# Pesos do score de prioridade (0-100)
PESOS_PRIORIDADE = {"severidade": 0.40, "exposicao": 0.30, "recorrencia": 0.15, "espera": 0.15}
RAIO_POI_M = 300
PESO_POI = {"hospital": 3, "ubs": 2, "escola": 2, "estacao_metro_trem": 3, "terminal_onibus": 2}
