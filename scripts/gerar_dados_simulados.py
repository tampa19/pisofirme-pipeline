"""
Gera as fontes de dados SIMULADAS do MVP PisoFirme SP na pasta data/landing/.

Por que simular? (justificativa exigida pela atividade)
- O portal de dados abertos da Prefeitura de SP publica as solicitações do SP156,
  mas sem medidas do defeito (comprimento, largura, profundidade, firmeza da base),
  que são essenciais para decidir se o buraco cabe no reparo modular e para
  dimensionar a peça impressa em 3D.
- As medidas viriam do app do MVP (relato do cidadão + foto com referência de escala),
  que ainda não está em produção; os ensaios de bancada do protótipo ainda serão feitos.
- Por isso os dados são gerados com semente fixa (reprodutíveis), imitando a
  estrutura real das fontes e incluindo os "defeitos" típicos de dados reais
  (duplicatas, nomes inconsistentes, datas em formatos diferentes, coordenadas
  inválidas, unidades trocadas, campos vazios) para que o pipeline precise tratá-los.

Uso:  python scripts/gerar_dados_simulados.py
"""
from __future__ import annotations

import csv
import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "data" / "landing"

# Subprefeituras de SP com centróides APROXIMADOS (apenas para simulação espacial)
SUBPREFEITURAS = [
    ("Sé", "Centro", -23.550, -46.634), ("Pinheiros", "Oeste", -23.567, -46.702),
    ("Lapa", "Oeste", -23.522, -46.705), ("Butantã", "Oeste", -23.585, -46.740),
    ("Vila Mariana", "Sul", -23.589, -46.634), ("Ipiranga", "Sul", -23.600, -46.605),
    ("Jabaquara", "Sul", -23.645, -46.640), ("Santo Amaro", "Sul", -23.650, -46.705),
    ("Cidade Ademar", "Sul", -23.680, -46.655), ("Campo Limpo", "Sul", -23.640, -46.765),
    ("M'Boi Mirim", "Sul", -23.690, -46.775), ("Capela do Socorro", "Sul", -23.740, -46.700),
    ("Parelheiros", "Sul", -23.830, -46.720), ("Mooca", "Leste", -23.555, -46.595),
    ("Aricanduva/Formosa/Carrão", "Leste", -23.560, -46.525), ("Vila Prudente", "Leste", -23.585, -46.580),
    ("Sapopemba", "Leste", -23.605, -46.515), ("São Mateus", "Leste", -23.610, -46.475),
    ("Penha", "Leste", -23.525, -46.545), ("Ermelino Matarazzo", "Leste", -23.495, -46.480),
    ("Itaquera", "Leste", -23.540, -46.455), ("Guaianases", "Leste", -23.545, -46.410),
    ("Cidade Tiradentes", "Leste", -23.590, -46.400), ("São Miguel Paulista", "Leste", -23.495, -46.445),
    ("Itaim Paulista", "Leste", -23.500, -46.400), ("Santana/Tucuruvi", "Norte", -23.480, -46.620),
    ("Vila Maria/Vila Guilherme", "Norte", -23.510, -46.585), ("Jaçanã/Tremembé", "Norte", -23.455, -46.590),
    ("Casa Verde/Cachoeirinha", "Norte", -23.490, -46.665), ("Freguesia/Brasilândia", "Norte", -23.465, -46.695),
    ("Pirituba/Jaraguá", "Norte", -23.465, -46.735), ("Perus/Anhanguera", "Norte", -23.410, -46.760),
]

RUAS = ["Rua das Flores", "Av. Brasil", "Rua São Bento", "Rua Augusta", "Av. Paulista", "Rua da Mooca",
        "Rua Voluntários da Pátria", "Av. Celso Garcia", "Rua Teodoro Sampaio", "Av. Santo Amaro",
        "Rua Domingos de Morais", "Av. Itaquera", "Rua Cardeal Arcoverde", "Av. Sapopemba",
        "Rua Tuiuti", "Av. Inajar de Souza", "Rua Clélia", "Av. Guarapiranga", "Rua Butantã", "Av. Penha de França"]


def variante_nome(nome: str, rnd: random.Random) -> str:
    """Simula as inconsistências de digitação vistas em dados de atendimento."""
    import unicodedata
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", nome) if unicodedata.category(c) != "Mn")
    opcoes = [nome, nome.upper(), sem_acento.upper(), f" {nome} ", nome.replace("/", " / "),
              sem_acento.replace("'", " ").upper(), nome.lower()]
    pesos = [55, 15, 10, 5, 5, 5, 5]
    return rnd.choices(opcoes, pesos)[0]


def ponto_perto(lat, lon, rnd, raio=0.025):
    return round(lat + rnd.uniform(-raio, raio), 6), round(lon + rnd.uniform(-raio, raio), 6)


def gerar_subprefeituras():
    path = LANDING / "subprefeituras" / "subprefeituras.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["codigo", "nome", "zona", "lat_centroide", "lon_centroide"])
        for i, (nome, zona, lat, lon) in enumerate(SUBPREFEITURAS, start=1):
            w.writerow([f"SP{i:02d}", nome, zona, lat, lon])


def gerar_pois(rnd):
    tipos = [("hospital", 2), ("ubs", 4), ("escola", 6), ("estacao_metro_trem", 3), ("terminal_onibus", 1)]
    path = LANDING / "pontos_interesse" / "pontos_interesse.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id_poi", "tipo", "nome", "latitude", "longitude"])
        n = 0
        for nome, _, lat, lon in SUBPREFEITURAS:
            for tipo, qtd in tipos:
                for k in range(qtd):
                    n += 1
                    la, lo = ponto_perto(lat, lon, rnd, 0.03)
                    w.writerow([f"POI{n:04d}", tipo, f"{tipo.replace('_', ' ').title()} {nome} {k + 1}", la, lo])


def gerar_sp156(rnd, hoje):
    """Solicitações no formato do SP156 (atendimento ao cidadão)."""
    servicos = [("Calçada - buraco ou desnível", 45), ("Reparo de calçada danificada", 30),
                ("Tampa de concessionária quebrada na calçada", 10), ("Calçada obstruída por entulho", 10),
                ("Rebaixamento de guia", 5)]
    status_opts = [("FINALIZADA", 45), ("EM ANDAMENTO", 20), ("ABERTA", 28), ("CANCELADA", 7)]
    linhas = []
    for i in range(3200):
        nome, _, lat, lon = rnd.choices(SUBPREFEITURAS, weights=[3 if s[1] == "Leste" else 2 for s in SUBPREFEITURAS])[0]
        abertura = hoje - timedelta(days=rnd.randint(1, 300), hours=rnd.randint(0, 23), minutes=rnd.randint(0, 59))
        status = rnd.choices([s[0] for s in status_opts], [s[1] for s in status_opts])[0]
        conclusao = ""
        if status in ("FINALIZADA", "CANCELADA"):
            dt = abertura + timedelta(days=rnd.randint(2, 120))
            conclusao = min(dt, hoje).strftime("%Y-%m-%d %H:%M:%S")
        la, lo = ponto_perto(lat, lon, rnd)
        r = rnd.random()
        if r < 0.04:
            la, lo = "", ""            # sem coordenada
        elif r < 0.06:
            la, lo = 0, 0              # coordenada zerada
        elif r < 0.07:
            la, lo = -22.9, -43.2      # fora de SP (erro de geocodificação)
        data_txt = abertura.strftime("%Y-%m-%d %H:%M:%S") if rnd.random() > 0.25 else abertura.strftime("%d/%m/%Y %H:%M")
        linhas.append({
            "protocolo": f"2026{i + 100000:07d}",
            "data_abertura": data_txt,
            "subprefeitura": variante_nome(nome, rnd),
            "tema": "Ruas e calçadas",
            "servico": rnd.choices([s[0] for s in servicos], [s[1] for s in servicos])[0],
            "logradouro": f"{rnd.choice(RUAS)}, {rnd.randint(10, 3000)}",
            "latitude": la, "longitude": lo,
            "status": status if rnd.random() > 0.05 else status.lower(),
            "data_conclusao": conclusao,
        })
    # duplicatas (reenvio do mesmo protocolo com status atualizado)
    for d in rnd.sample(linhas, 110):
        dup = dict(d)
        if dup["status"].upper() == "ABERTA":
            dup["status"] = "EM ANDAMENTO"
        linhas.append(dup)
    rnd.shuffle(linhas)
    path = LANDING / "sp156" / "sp156_solicitacoes_calcadas.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(linhas)
    return [l for l in linhas if "buraco" in l["servico"] or "danificada" in l["servico"]]


def gerar_relatos_app(rnd, hoje, sp156_defeitos):
    """Relatos do app PisoFirme: foto + medidas estimadas com régua/objeto de referência."""
    tipos = [("buraco", 40), ("revestimento_solto", 25), ("desnivel", 15), ("raiz_arvore", 12), ("tampa_servico", 8)]
    relatos = []
    for i in range(1400):
        nome, _, lat, lon = rnd.choice(SUBPREFEITURAS)
        ts = hoje - timedelta(days=rnd.randint(0, 200), minutes=rnd.randint(0, 1440))
        tipo = rnd.choices([t[0] for t in tipos], [t[1] for t in tipos])[0]
        comp = round(rnd.lognormvariate(3.7, 0.55), 1)   # ~40 cm mediana
        larg = round(comp * rnd.uniform(0.35, 0.9), 1)
        prof = round(max(0.5, rnd.gauss(4.0, 2.2)), 1)
        if tipo == "desnivel":
            prof = round(rnd.uniform(0.5, 4.0), 1)
        protocolo = None
        if rnd.random() < 0.4 and sp156_defeitos:
            ref = rnd.choice(sp156_defeitos)
            protocolo = ref["protocolo"]
            if ref["latitude"] not in ("", 0):
                lat, lon = float(ref["latitude"]), float(ref["longitude"])
        la, lo = ponto_perto(lat, lon, rnd, 0.002 if protocolo else 0.025)
        base = rnd.choices(["sim", "nao", "nao_sei", True, False, None], [45, 15, 15, 10, 5, 10])[0]
        medidas = {"comprimento_cm": comp, "largura_cm": larg, "profundidade_cm": prof}
        r = rnd.random()
        if r < 0.04:
            medidas["profundidade_cm"] = round(prof * 10, 0)       # usuário digitou em mm
        elif r < 0.06:
            medidas["comprimento_cm"] = None
        elif r < 0.07:
            medidas["largura_cm"] = -abs(larg)                      # valor negativo inválido
        relatos.append({
            "id_relato": str(uuid.UUID(int=rnd.getrandbits(128))),
            "criado_em": ts.strftime("%Y-%m-%dT%H:%M:%S-03:00"),
            "protocolo_sp156": protocolo,
            "geo": {"lat": la, "lon": lo},
            "tipo_dano": tipo if rnd.random() > 0.03 else tipo.upper(),
            "medidas": medidas,
            "base_firme": base,
            "tampa_proxima": tipo == "tampa_servico" or rnd.random() < 0.05,
            "confirmacoes": rnd.choices([0, 1, 2, 3, 5, 8], [40, 25, 15, 10, 6, 4])[0],
            "foto_url": f"https://storage.pisofirme.app/fotos/{i:05d}.jpg",
            "usuario_hash": f"u{rnd.randint(1, 600):04d}",
        })
    # reenvio duplicado (mesmo id) por falha de rede no app
    relatos += [dict(r) for r in rnd.sample(relatos, 40)]
    path = LANDING / "relatos_app" / "relatos_app.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(relatos, ensure_ascii=False, indent=1), encoding="utf-8")


def gerar_ensaios(rnd, hoje):
    """Resultados de ensaios de bancada dos corpos de prova (versões do módulo)."""
    versoes = {
        "v0.1": dict(material="PLA", celula="retangular", infill=20, placa=6, borracha=2, q=1.6),
        "v0.2": dict(material="PETG", celula="hexagonal", infill=25, placa=8, borracha=3, q=1.1),
        "v0.3": dict(material="PETG", celula="giroide", infill=30, placa=8, borracha=3, q=0.75),
        "v0.4": dict(material="PETG", celula="giroide", infill=35, placa=10, borracha=4, q=0.55),
    }
    ensaios = [("nivel", "mm", 3.0), ("deformacao_residual", "mm", 1.6), ("deslocamento", "mm", 2.4),
               ("aderencia_seco", "PTV", 55), ("aderencia_molhado", "PTV", 34)]
    path = LANDING / "ensaios_bancada" / "ensaios_bancada.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["versao_modulo", "corpo_prova", "material_estrutura", "padrao_celula", "infill_pct",
                    "espessura_placa_mm", "espessura_borracha_mm", "ensaio", "carga_kgf", "valor", "unidade", "data_ensaio"])
        dia = hoje - timedelta(days=40)
        for vi, (v, p) in enumerate(versoes.items()):
            for cp in range(1, 4):
                for ens, un, base in ensaios:
                    if un == "PTV":   # aderência melhora com borracha mais espessa
                        val = base + (p["borracha"] - 2) * 2.2 + rnd.gauss(0, 1.5)
                    else:
                        val = base * p["q"] + abs(rnd.gauss(0, 0.25))
                    carga = 80 if ens in ("deformacao_residual", "deslocamento") else ""
                    valor = f"{val:.2f}".replace(".", ",") if rnd.random() < 0.15 else f"{val:.2f}"  # vírgula decimal
                    w.writerow([v, f"CP{vi + 1}{cp}", p["material"], p["celula"], p["infill"], p["placa"],
                                p["borracha"], ens, carga, valor, un, (dia + timedelta(days=vi * 9 + cp)).strftime("%Y-%m-%d")])


def main():
    rnd = random.Random(SEED)
    hoje = datetime(2026, 11, 12, 8, 0, 0)
    gerar_subprefeituras()
    gerar_pois(rnd)
    defeitos = gerar_sp156(rnd, hoje)
    gerar_relatos_app(rnd, hoje, defeitos)
    gerar_ensaios(rnd, hoje)
    for p in sorted(LANDING.rglob("*.*")):
        print(f"gerado: {p.relative_to(ROOT)}  ({p.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
