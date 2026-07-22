"""
Gera o site estatico publicado no GitHub Pages: uma pagina HTML por rota
(link individual para cada motorista, com mapa Leaflet + lista de paradas)
e uma pagina inicial (docs/index.html) listando as rotas do dia.

Nao existe backend nem senha: qualquer pessoa com o link de uma rota
consegue abri-la (decisao do usuario). Por isso os arquivos NAO devem conter
nada alem do que e necessario para a entrega (sem dados financeiros da
empresa, por exemplo, alem do que ja constava no relatorio original).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from route_optimizer import ResultadoRota

AVISO_OTIMIZACAO = (
    "Sequencia calculada apenas por proximidade geografica (vizinho mais "
    "proximo / Haversine). NAO considera janela de horario nem prazo de "
    "entrega combinado com o cliente."
)

_ESTILO = """
:root { --azul: #1f4e78; --azul-claro: #eaf1f8; --texto: #1a1a1a; --borda: #d9dfe6; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, Helvetica, sans-serif; color: var(--texto); background: #f4f6f8; }
header { background: var(--azul); color: #fff; padding: 12px 16px; }
header h1 { margin: 0; font-size: 1.1rem; }
header .sub { font-size: 0.8rem; opacity: 0.85; margin-top: 2px; }
.aviso { background: #fff3cd; color: #664d03; font-size: 0.8rem; padding: 8px 16px; border-bottom: 1px solid #ffe69c; }
.resumo { font-size: 0.85rem; padding: 8px 16px; background: var(--azul-claro); display: flex; gap: 16px; flex-wrap: wrap; }
.resumo b { color: var(--azul); }
#mapa { width: 100%; height: 42vh; min-height: 260px; }
main { max-width: 720px; margin: 0 auto; }
ol.paradas { list-style: none; margin: 0; padding: 8px; }
.parada { display: flex; gap: 10px; background: #fff; border: 1px solid var(--borda); border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
.parada .num { background: var(--azul); color: #fff; border-radius: 50%; width: 26px; height: 26px; min-width: 26px; display: flex; align-items: center; justify-content: center; font-size: 0.85rem; font-weight: bold; align-self: flex-start; }
.parada .info { flex: 1; }
.parada .cliente { font-weight: bold; font-size: 0.95rem; }
.parada .endereco { font-size: 0.82rem; color: #444; margin-top: 2px; }
.parada .meta { font-size: 0.78rem; color: var(--azul); margin-top: 4px; }
footer { text-align: center; font-size: 0.72rem; color: #888; padding: 16px; }
ul.lista-rotas { list-style: none; margin: 0; padding: 12px; max-width: 480px; margin: 0 auto; }
ul.lista-rotas li { margin-bottom: 10px; }
ul.lista-rotas a { display: block; background: #fff; border: 1px solid var(--borda); border-radius: 8px; padding: 14px 16px; text-decoration: none; color: var(--texto); font-weight: bold; }
ul.lista-rotas a small { display: block; font-weight: normal; color: #666; margin-top: 4px; }
"""

_ROTA_TEMPLATE = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>{rota} - Rota de entrega</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>{estilo}</style>
</head>
<body>
<header>
  <h1>Rota {rota}</h1>
  <div class="sub">Atualizado em {gerado_em}</div>
</header>
<div class="aviso">{aviso}</div>
<div class="resumo">
  <span>Distancia original: <b>{dist_original:.2f} km</b></span>
  <span>Distancia otimizada: <b>{dist_otimizada:.2f} km</b></span>
  <span>Economia: <b>{economia_km:.2f} km ({economia_pct:.1f}%)</b></span>
  <span>Saida ate a 1a parada: <b>{dist_origem_primeira:.2f} km</b></span>
</div>
<div id="mapa"></div>
<main>
  <ol class="paradas" id="listaParadas"></ol>
</main>
<footer><a href="../index.html">Ver todas as rotas de hoje</a></footer>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const PARADAS = {paradas_json};
const ORIGEM = {origem_json};

const listaEl = document.getElementById('listaParadas');
const mapa = L.map('mapa');
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}}).addTo(mapa);

function iconeNumerado(numero) {{
  return L.divIcon({{
    className: 'icone-parada',
    html: '<div style="background:#1f4e78;color:#fff;border-radius:50%;width:26px;height:26px;' +
          'display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:bold;' +
          'border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4);">' + numero + '</div>',
    iconSize: [26, 26],
    iconAnchor: [13, 13]
  }});
}}

const iconeOrigem = L.divIcon({{
  className: 'icone-origem',
  html: '<div style="background:#c00000;color:#fff;border-radius:50%;width:26px;height:26px;' +
        'display:flex;align-items:center;justify-content:center;font-size:14px;' +
        'border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4);">&#128666;</div>',
  iconSize: [26, 26],
  iconAnchor: [13, 13]
}});

const pontos = [[ORIGEM.lat, ORIGEM.lon]];
L.marker([ORIGEM.lat, ORIGEM.lon], {{ icon: iconeOrigem }})
  .bindPopup('<b>Saida do caminhao</b>')
  .addTo(mapa);

PARADAS.forEach(p => {{
  const li = document.createElement('li');
  li.className = 'parada';
  const distTxt = (p.dist_proxima_km === null) ? 'ultima parada'
    : ('proxima: ' + p.dist_proxima_km.toFixed(2) + ' km');
  li.innerHTML =
    '<div class="num">' + p.seq + '</div>' +
    '<div class="info">' +
      '<div class="cliente">' + p.cliente + '</div>' +
      '<div class="endereco">' + p.endereco + '</div>' +
      '<div class="meta">' + distTxt + '</div>' +
    '</div>';
  listaEl.appendChild(li);
  pontos.push([p.lat, p.lon]);
  L.marker([p.lat, p.lon], {{ icon: iconeNumerado(p.seq) }})
    .bindPopup('<b>' + p.seq + '. ' + p.cliente + '</b><br>' + p.endereco)
    .addTo(mapa);
}});
if (pontos.length > 1) {{
  L.polyline(pontos, {{ color: '#1f4e78', weight: 3, opacity: 0.8 }}).addTo(mapa);
}}
if (pontos.length) {{
  mapa.fitBounds(pontos, {{ padding: [30, 30] }});
}}
</script>
</body>
</html>
"""

_INDEX_TEMPLATE = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Rotas de hoje - PathFind</title>
<style>{estilo}</style>
</head>
<body>
<header>
  <h1>Cargas otimizadas - PathFind</h1>
  <div class="sub">Atualizado em {gerado_em}</div>
</header>
<div class="aviso">{aviso}</div>
<main>
  <ul class="lista-rotas">
    {itens}
  </ul>
</main>
<footer>Gerado automaticamente a partir do relatorio do dia.</footer>
</body>
</html>
"""


def _slug_rota(rota: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", rota)


def _resultado_para_paradas(resultado: ResultadoRota) -> list[dict]:
    return [
        {
            "seq": p.sequencia,
            "cliente": p.entrega.cliente,
            "endereco": p.entrega.endereco,
            "lat": p.entrega.latitude,
            "lon": p.entrega.longitude,
            "dist_proxima_km": p.distancia_ate_proxima_km,
        }
        for p in resultado.ordem_otimizada
    ]


def gerar_site(
    resultados: dict[str, ResultadoRota],
    docs_dir: str,
    origem_lat: float,
    origem_lon: float,
) -> list[str]:
    """Gera docs/index.html e docs/rotas/<ROTA>.html. Retorna a lista de
    arquivos gerados (paths relativos a docs_dir), util para o watcher decidir
    o que commitar."""
    rotas_dir = os.path.join(docs_dir, "rotas")
    os.makedirs(rotas_dir, exist_ok=True)

    gerado_em = datetime.now().strftime("%d/%m/%Y %H:%M")
    arquivos_gerados = []
    origem_json = json.dumps({"lat": origem_lat, "lon": origem_lon})

    itens_index = []
    for rota in sorted(resultados):
        resultado = resultados[rota]
        slug = _slug_rota(rota)
        paradas = _resultado_para_paradas(resultado)

        html_rota = _ROTA_TEMPLATE.format(
            rota=rota,
            estilo=_ESTILO,
            gerado_em=gerado_em,
            aviso=AVISO_OTIMIZACAO,
            dist_original=resultado.distancia_total_original_km,
            dist_otimizada=resultado.distancia_total_otimizada_km,
            economia_km=resultado.economia_km,
            economia_pct=resultado.economia_percentual,
            dist_origem_primeira=resultado.distancia_origem_primeira_km,
            paradas_json=json.dumps(paradas, ensure_ascii=False),
            origem_json=origem_json,
        )
        caminho_rota = os.path.join(rotas_dir, f"{slug}.html")
        with open(caminho_rota, "w", encoding="utf-8") as f:
            f.write(html_rota)
        arquivos_gerados.append(os.path.join("rotas", f"{slug}.html"))

        itens_index.append(
            f'<li><a href="rotas/{slug}.html">{rota} '
            f'<small>{len(paradas)} paradas &middot; '
            f'{resultado.distancia_total_otimizada_km:.1f} km</small></a></li>'
        )

    html_index = _INDEX_TEMPLATE.format(
        estilo=_ESTILO,
        gerado_em=gerado_em,
        aviso=AVISO_OTIMIZACAO,
        itens="\n    ".join(itens_index),
    )
    caminho_index = os.path.join(docs_dir, "index.html")
    with open(caminho_index, "w", encoding="utf-8") as f:
        f.write(html_index)
    arquivos_gerados.append("index.html")

    return arquivos_gerados
