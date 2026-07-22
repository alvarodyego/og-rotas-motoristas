"""
Gera o site estatico publicado no GitHub Pages: uma pagina HTML por rota
(link individual para cada motorista, com mapa Leaflet + lista de paradas)
e uma pagina inicial (docs/index.html) listando as rotas do dia.

Alem da pagina "de hoje" (docs/index.html e docs/rotas/*.html, que e o que
os motoristas devem usar no link fixo do dia a dia), cada execucao tambem
grava uma copia arquivada em docs/historico/<AAAA-MM-DD>/, para permitir o
filtro por data na pagina inicial. O historico nunca é apagado
automaticamente; ele so cresce um dia por vez.

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
.filtro-data { display: flex; gap: 8px; align-items: center; padding: 10px 16px; background: #fff; border-bottom: 1px solid var(--borda); flex-wrap: wrap; }
.filtro-data label { font-size: 0.85rem; }
.filtro-data select { font-size: 1rem; padding: 6px 8px; border-radius: 6px; border: 1px solid var(--borda); flex: 1; min-width: 160px; }
.filtro-data a { font-size: 0.8rem; color: var(--azul); text-decoration: none; white-space: nowrap; }
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
.parada .btn-maps { display: inline-block; margin-top: 8px; padding: 6px 12px; background: var(--azul); color: #fff; border-radius: 6px; text-decoration: none; font-size: 0.78rem; font-weight: bold; }
.parada .btn-maps:visited { color: #fff; }
footer { text-align: center; font-size: 0.72rem; color: #888; padding: 16px; }
footer a { color: var(--azul); }
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
<title>{rotulo} - Rota de entrega</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>{estilo}</style>
</head>
<body>
<header>
  <h1>{rotulo}</h1>
  <div class="sub">Atualizado em {gerado_em}</div>
</header>
<div class="aviso">{aviso}</div>
<div class="resumo">
  <span>Distancia original (ida e volta): <b>{dist_original:.2f} km</b></span>
  <span>Distancia otimizada (ida e volta): <b>{dist_otimizada:.2f} km</b></span>
  <span>Economia: <b>{economia_km:.2f} km ({economia_pct:.1f}%)</b></span>
  <span>Saida ate a 1a parada: <b>{dist_origem_primeira:.2f} km</b></span>
  <span>Volta ao ponto de partida: <b>{dist_retorno:.2f} km</b></span>
</div>
<div id="mapa"></div>
<main>
  <ol class="paradas" id="listaParadas"></ol>
</main>
<footer><a href="../index.html">Ver todas as rotas desta data</a></footer>

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
  const mapsUrl = 'https://www.google.com/maps/dir/?api=1&destination=' + p.lat + ',' + p.lon;
  li.innerHTML =
    '<div class="num">' + p.seq + '</div>' +
    '<div class="info">' +
      '<div class="cliente">' + p.cliente + '</div>' +
      '<div class="endereco">' + p.endereco + '</div>' +
      '<div class="meta">' + distTxt + '</div>' +
      '<a class="btn-maps" href="' + mapsUrl + '" target="_blank" rel="noopener">Abrir no Google Maps</a>' +
    '</div>';
  listaEl.appendChild(li);
  pontos.push([p.lat, p.lon]);
  L.marker([p.lat, p.lon], {{ icon: iconeNumerado(p.seq) }})
    .bindPopup('<b>' + p.seq + '. ' + p.cliente + '</b><br>' + p.endereco)
    .addTo(mapa);
}});
if (pontos.length > 1) {{
  L.polyline(pontos, {{ color: '#1f4e78', weight: 3, opacity: 0.8 }}).addTo(mapa);
  L.polyline([pontos[pontos.length - 1], [ORIGEM.lat, ORIGEM.lon]], {{
    color: '#c00000', weight: 3, opacity: 0.7, dashArray: '6 8'
  }}).addTo(mapa);
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
<title>{titulo_pagina} - PathFind</title>
<style>{estilo}</style>
</head>
<body>
<header>
  <h1>{titulo_pagina}</h1>
  <div class="sub">Atualizado em {gerado_em}</div>
</header>
<div class="aviso">{aviso}</div>
<div class="filtro-data">
  <label for="seletorData">Ver rotas de:</label>
  <select id="seletorData"><option value="{data_atual_iso}">{data_atual_br} (hoje)</option></select>
  <a href="{hoje_rel}">Ir para hoje</a>
</div>
<main>
  <ul class="lista-rotas">
    {itens}
  </ul>
</main>
<footer>Gerado automaticamente a partir do relatorio do dia.</footer>

<script>
fetch('{manifest_rel}').then(r => r.json()).then(dias => {{
  const sel = document.getElementById('seletorData');
  sel.innerHTML = '';
  dias.forEach(d => {{
    const opt = document.createElement('option');
    opt.value = d.data;
    opt.textContent = d.data_br + ' (' + d.rotas + ' rota(s))';
    sel.appendChild(opt);
  }});
  sel.value = '{data_atual_iso}';
  sel.addEventListener('change', () => {{
    window.location.href = '{historico_base_rel}' + sel.value + '/index.html';
  }});
}}).catch(() => {{}});
</script>
</body>
</html>
"""


_CODIGO_MOTORISTA_RE = re.compile(r"(\d+)")


def rotulo_rota(resultado: ResultadoRota) -> str:
    """Rotulo mostrado ao motorista: placa do veiculo + codigo do motorista
    (ex: 'TVA-5A26 - Motorista 729'), em vez do codigo interno da rota
    (RTxxxxxx), que nao significa nada pra quem esta dirigindo."""
    if not resultado.ordem_otimizada:
        return resultado.rota
    primeira = resultado.ordem_otimizada[0].entrega
    placa = primeira.veiculo or "Veiculo"
    codigo_m = _CODIGO_MOTORISTA_RE.search(primeira.motorista_nome or "")
    if codigo_m:
        return f"{placa} - Motorista {codigo_m.group(1)}"
    return f"{placa} - Sem motorista definido"


def _slug(texto: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", texto).strip("-")
    return slug or "rota"


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


def _gerar_paginas(
    resultados: dict[str, ResultadoRota],
    base_dir: str,
    origem_lat: float,
    origem_lon: float,
    gerado_em: str,
    titulo_pagina: str,
    manifest_rel: str,
    historico_base_rel: str,
    hoje_rel: str,
    data_atual_iso: str,
    data_atual_br: str,
) -> list[str]:
    """Escreve <base_dir>/index.html e <base_dir>/rotas/*.html. Usada tanto
    para a pagina 'de hoje' (docs/) quanto para a copia arquivada
    (docs/historico/<data>/)."""
    rotas_dir = os.path.join(base_dir, "rotas")
    os.makedirs(rotas_dir, exist_ok=True)

    # Limpa paginas de rotas de execucoes anteriores nesta mesma pasta: como
    # o nome do arquivo depende da placa/motorista (que pode mudar de rota
    # pra rota), sem isso paginas antigas ficariam "orfas" (publicadas, mas
    # sem link nenhum apontando pra elas).
    for nome in os.listdir(rotas_dir):
        if nome.endswith(".html"):
            os.remove(os.path.join(rotas_dir, nome))

    arquivos_gerados = []
    origem_json = json.dumps({"lat": origem_lat, "lon": origem_lon})

    itens_index = []
    slugs_usados: dict[str, int] = {}
    for rota in sorted(resultados):
        resultado = resultados[rota]
        rotulo = rotulo_rota(resultado)
        slug_base = _slug(rotulo)
        contagem = slugs_usados.get(slug_base, 0)
        slugs_usados[slug_base] = contagem + 1
        slug = slug_base if contagem == 0 else f"{slug_base}-{contagem + 1}"
        paradas = _resultado_para_paradas(resultado)

        html_rota = _ROTA_TEMPLATE.format(
            rotulo=rotulo,
            estilo=_ESTILO,
            gerado_em=gerado_em,
            aviso=AVISO_OTIMIZACAO,
            dist_original=resultado.distancia_total_original_km,
            dist_otimizada=resultado.distancia_total_otimizada_km,
            economia_km=resultado.economia_km,
            economia_pct=resultado.economia_percentual,
            dist_origem_primeira=resultado.distancia_origem_primeira_km,
            dist_retorno=resultado.distancia_retorno_km,
            paradas_json=json.dumps(paradas, ensure_ascii=False),
            origem_json=origem_json,
        )
        caminho_rota = os.path.join(rotas_dir, f"{slug}.html")
        with open(caminho_rota, "w", encoding="utf-8") as f:
            f.write(html_rota)
        arquivos_gerados.append(os.path.join("rotas", f"{slug}.html"))

        itens_index.append(
            f'<li><a href="rotas/{slug}.html">{rotulo} '
            f'<small>{len(paradas)} paradas &middot; '
            f'{resultado.distancia_total_otimizada_km:.1f} km</small></a></li>'
        )

    html_index = _INDEX_TEMPLATE.format(
        estilo=_ESTILO,
        gerado_em=gerado_em,
        aviso=AVISO_OTIMIZACAO,
        titulo_pagina=titulo_pagina,
        itens="\n    ".join(itens_index),
        manifest_rel=manifest_rel,
        historico_base_rel=historico_base_rel,
        hoje_rel=hoje_rel,
        data_atual_iso=data_atual_iso,
        data_atual_br=data_atual_br,
    )
    caminho_index = os.path.join(base_dir, "index.html")
    with open(caminho_index, "w", encoding="utf-8") as f:
        f.write(html_index)
    arquivos_gerados.append("index.html")

    return arquivos_gerados


def _atualizar_manifest(historico_dir: str, data_iso: str, data_br: str, gerado_em: str, total_rotas: int) -> None:
    caminho = os.path.join(historico_dir, "manifest.json")
    dias = []
    if os.path.isfile(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            try:
                dias = json.load(f)
            except json.JSONDecodeError:
                dias = []
    dias = [d for d in dias if d.get("data") != data_iso]
    dias.append({"data": data_iso, "data_br": data_br, "rotas": total_rotas, "gerado_em": gerado_em})
    dias.sort(key=lambda d: d["data"], reverse=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dias, f, ensure_ascii=False, indent=2)


def gerar_site(
    resultados: dict[str, ResultadoRota],
    docs_dir: str,
    origem_lat: float,
    origem_lon: float,
) -> list[str]:
    """Gera a pagina 'de hoje' (docs/index.html e docs/rotas/*.html -- o link
    fixo que os motoristas devem usar todo dia) e uma copia arquivada em
    docs/historico/<AAAA-MM-DD>/, alimentando o filtro de data da pagina
    inicial. Retorna a lista de arquivos gerados (paths relativos a
    docs_dir), util para o watcher decidir o que commitar."""
    agora = datetime.now()
    gerado_em = agora.strftime("%d/%m/%Y %H:%M")
    data_iso = agora.strftime("%Y-%m-%d")
    data_br = agora.strftime("%d/%m/%Y")

    historico_dir = os.path.join(docs_dir, "historico")
    dia_dir = os.path.join(historico_dir, data_iso)
    os.makedirs(historico_dir, exist_ok=True)

    arquivos_gerados = []

    # Pagina "de hoje": link fixo que nao muda de endereco dia a dia.
    arquivos_hoje = _gerar_paginas(
        resultados, docs_dir, origem_lat, origem_lon, gerado_em,
        titulo_pagina="Cargas otimizadas",
        manifest_rel="historico/manifest.json",
        historico_base_rel="historico/",
        hoje_rel="index.html",
        data_atual_iso=data_iso,
        data_atual_br=data_br,
    )
    arquivos_gerados.extend(arquivos_hoje)

    # Copia arquivada do dia, para o filtro de data poder consultar depois.
    arquivos_dia = _gerar_paginas(
        resultados, dia_dir, origem_lat, origem_lon, gerado_em,
        titulo_pagina=f"Rotas de {data_br}",
        manifest_rel="../manifest.json",
        historico_base_rel="../",
        hoje_rel="../../index.html",
        data_atual_iso=data_iso,
        data_atual_br=data_br,
    )
    arquivos_gerados.extend(os.path.join("historico", data_iso, a) for a in arquivos_dia)

    _atualizar_manifest(historico_dir, data_iso, data_br, gerado_em, len(resultados))
    arquivos_gerados.append(os.path.join("historico", "manifest.json"))

    return arquivos_gerados
