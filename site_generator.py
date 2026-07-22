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
from datetime import date, datetime

from route_optimizer import ResultadoRota

# Nota interna (nao exibida na pagina): o algoritmo de otimizacao usa apenas
# distancia geografica (Haversine + vizinho mais proximo) e NAO considera
# janela de horario nem prazo de entrega combinado com o cliente. Ver
# route_optimizer.py para detalhes -- essa limitacao continua valendo mesmo
# sem o aviso aparecer para o motorista.

MARCA = "Distribuidora OG de Bebidas &middot; Revendedor Autorizado Heineken"

# Config publica do Firebase (projeto "rotacertaog") -- NAO e' segredo, e'
# seguro embutir no HTML/JS publico. A seguranca de verdade vem das regras
# do Firestore (configuradas direto no console do Firebase), nao desses
# valores. Usado pra sincronizar o status de entrega (Entregue/Devolucao/
# Fechado) entre o celular do motorista e o painel do supervisor.
FIREBASE_CONFIG = {
    "apiKey": "AIzaSyDZpcc1GgdbknHdkuI4dOx1myDR6PsLPic",
    "authDomain": "rotacertaog.firebaseapp.com",
    "projectId": "rotacertaog",
    "storageBucket": "rotacertaog.firebasestorage.app",
    "messagingSenderId": "1048075742585",
    "appId": "1:1048075742585:web:424f99f9a29fa0f23593a8",
}
FIRESTORE_COLECAO_STATUS = "status_entregas"
FIRESTORE_COLECAO_MOTORISTAS = "motoristas"

# Faixa de numeros de motorista da empresa (720 a 731). Usado pra pre-gerar
# senhas padrao na pagina de administracao. NAO e' derivado dos dados do
# dia -- e' o quadro fixo de motoristas, independente de quem estiver
# escalado numa rota especifica hoje.
NUMERO_MOTORISTA_MIN = 720
NUMERO_MOTORISTA_MAX = 731


def senha_padrao(numero: int) -> str:
    """Gera a senha padrao de um motorista no formato pedido (ex: 720 ->
    '720OG0', 731 -> '731OG1'): o numero do motorista + 'OG' + o ultimo
    digito do numero."""
    return f"{numero}OG{numero % 10}"

_ESTILO = """
:root { --azul: #1f4e78; --azul-claro: #eaf1f8; --texto: #1a1a1a; --borda: #d9dfe6; }
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; font-family: Arial, Helvetica, sans-serif; color: var(--texto); background: #f4f6f8; -webkit-tap-highlight-color: transparent; animation: entrada 0.15s ease-out; }
@keyframes entrada { from { opacity: 0; } to { opacity: 1; } }
header { background: var(--azul); color: #fff; padding: 12px 16px; }
header h1 { margin: 0; font-size: 1.1rem; }
header .marca { font-size: 0.75rem; opacity: 0.9; margin-top: 3px; }
header .sub { font-size: 0.72rem; opacity: 0.75; margin-top: 2px; }
.filtro-data { display: flex; gap: 8px; align-items: center; padding: 10px 16px; background: #fff; border-bottom: 1px solid var(--borda); flex-wrap: wrap; }
.filtro-data label { font-size: 0.85rem; }
.filtro-data select { font-size: 1rem; padding: 6px 8px; border-radius: 6px; border: 1px solid var(--borda); flex: 1; min-width: 160px; }
.filtro-data a { font-size: 0.8rem; color: var(--azul); text-decoration: none; white-space: nowrap; }
.aviso-linha-reta { background: #fff3cd; color: #664d03; font-size: 0.75rem; padding: 6px 16px; border-bottom: 1px solid #ffe69c; }
.resumo { font-size: 0.72rem; background: var(--azul-claro); display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; padding: 10px 12px; border-radius: 8px; margin-top: 4px; }
.resumo > div { display: flex; flex-direction: column; }
.resumo span { color: #555; }
.resumo b { color: var(--azul); font-size: 0.8rem; }
#mapa { width: 100%; height: 68vh; min-height: 460px; }
main { max-width: 720px; margin: 0 auto; padding: 0 4px; }
ol.paradas { list-style: none; margin: 0; padding: 8px; }
.parada { display: flex; gap: 10px; background: #fff; border: 1px solid var(--borda); border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; }
.parada .num { background: var(--azul); color: #fff; border-radius: 50%; width: 26px; height: 26px; min-width: 26px; display: flex; align-items: center; justify-content: center; font-size: 0.85rem; font-weight: bold; align-self: flex-start; }
.parada .info { flex: 1; }
.parada .codigo { font-size: 0.68rem; color: #888; font-weight: bold; }
.parada .cliente { font-weight: bold; font-size: 0.85rem; }
.parada .endereco { font-size: 0.72rem; color: #444; margin-top: 2px; }
.parada .meta { font-size: 0.68rem; color: var(--azul); margin-top: 4px; }
.parada .btn-maps { display: inline-block; margin-top: 8px; padding: 6px 12px; background: var(--azul); color: #fff; border-radius: 6px; text-decoration: none; font-size: 0.78rem; font-weight: bold; }
.parada .btn-maps:visited { color: #fff; }
.parada.status-entregue { border-left: 4px solid #1e7e34; }
.parada.status-devolucao { border-left: 4px solid #c00000; }
.parada.status-fechado { border-left: 4px solid #b8860b; }
.status-botoes { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.status-btn { flex: 1; min-width: 84px; padding: 6px 8px; border-radius: 6px; font-size: 0.7rem; font-weight: bold; background: #fff; cursor: pointer; text-align: center; }
.status-btn.entregue { border: 1.5px solid #1e7e34; color: #1e7e34; }
.status-btn.devolucao { border: 1.5px solid #c00000; color: #c00000; }
.status-btn.fechado { border: 1.5px solid #b8860b; color: #b8860b; }
.status-btn.entregue.ativo { background: #1e7e34; color: #fff; }
.status-btn.devolucao.ativo { background: #c00000; color: #fff; }
.status-btn.fechado.ativo { background: #b8860b; color: #fff; }
footer { text-align: center; font-size: 0.72rem; color: #888; padding: 16px; }
footer a { color: var(--azul); }
ul.lista-rotas { list-style: none; margin: 0; padding: 12px; max-width: 480px; margin: 0 auto; }
ul.lista-rotas li { margin-bottom: 10px; }
ul.lista-rotas a { display: block; background: #fff; border: 1px solid var(--borda); border-radius: 8px; padding: 14px 16px; text-decoration: none; color: var(--texto); font-weight: bold; }
ul.lista-rotas a small { display: block; font-weight: normal; color: #666; margin-top: 4px; }
.link-painel { display: block; text-align: center; padding: 10px 16px; background: #fff; border-bottom: 1px solid var(--borda); font-size: 0.85rem; }
.painel-rota { background: #fff; border: 1px solid var(--borda); border-radius: 8px; margin: 10px; padding: 12px; }
.painel-rota h2 { margin: 0 0 8px 0; font-size: 0.95rem; }
.painel-contagem { display: flex; gap: 10px; flex-wrap: wrap; font-size: 0.72rem; font-weight: bold; margin-bottom: 8px; }
.painel-contagem .c-entregue { color: #1e7e34; }
.painel-contagem .c-devolucao { color: #c00000; }
.painel-contagem .c-fechado { color: #b8860b; }
.painel-contagem .c-pendente { color: #888; }
.painel-linha { display: flex; justify-content: space-between; gap: 8px; font-size: 0.75rem; padding: 5px 0; border-top: 1px solid #f0f0f0; }
.painel-linha .p-status { font-weight: bold; white-space: nowrap; }
.painel-linha.status-entregue .p-status { color: #1e7e34; }
.painel-linha.status-devolucao .p-status { color: #c00000; }
.painel-linha.status-fechado .p-status { color: #b8860b; }
.painel-linha.status-pendente .p-status { color: #bbb; }
.painel-atualizado { text-align: center; font-size: 0.7rem; color: #888; padding: 8px; }
.bloqueio { display: none; position: fixed; inset: 0; background: var(--azul); color: #fff; align-items: center; justify-content: center; z-index: 9999; padding: 20px; }
body.bloqueado .bloqueio { display: flex; }
body.bloqueado > *:not(.bloqueio) { display: none !important; }
.bloqueio-caixa { max-width: 320px; width: 100%; text-align: center; }
.bloqueio-caixa h2 { margin: 0 0 4px 0; font-size: 1.1rem; }
.bloqueio-caixa p { font-size: 0.8rem; opacity: 0.85; margin: 0 0 16px 0; }
.bloqueio-caixa input { width: 100%; padding: 12px; border-radius: 8px; border: none; font-size: 1rem; text-align: center; margin-bottom: 10px; box-sizing: border-box; }
.bloqueio-caixa button { width: 100%; padding: 12px; border-radius: 8px; border: none; background: #fff; color: var(--azul); font-weight: bold; font-size: 1rem; cursor: pointer; }
.bloqueio-erro { color: #ffd6d6; font-size: 0.78rem; margin-top: 10px; min-height: 1em; }
.admin-linha { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #fff; border: 1px solid var(--borda); border-radius: 8px; margin: 0 10px 8px 10px; }
.admin-linha span { min-width: 40px; font-weight: bold; font-size: 0.85rem; }
.admin-linha input { flex: 1; padding: 8px; border-radius: 6px; border: 1px solid var(--borda); font-size: 0.9rem; }
.admin-linha button { padding: 8px 12px; border-radius: 6px; border: none; background: var(--azul); color: #fff; font-size: 0.78rem; font-weight: bold; cursor: pointer; }
.admin-topo { display: flex; gap: 8px; padding: 10px; flex-wrap: wrap; }
.admin-topo button { padding: 10px 14px; border-radius: 6px; border: none; background: var(--azul); color: #fff; font-size: 0.8rem; font-weight: bold; cursor: pointer; }
.admin-msg { text-align: center; font-size: 0.8rem; padding: 8px; min-height: 1.2em; }
"""

_ROTA_TEMPLATE = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="theme-color" content="#1f4e78">
<title>{rotulo} - Rota de entrega</title>
<link rel="preconnect" href="https://unpkg.com">
<link rel="preconnect" href="https://tile.openstreetmap.org" crossorigin>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<style>{estilo}</style>
</head>
<body>
{bloqueio_html}<header>
  <h1>{rotulo}</h1>
  <div class="marca">{marca}</div>
  <div class="sub">Atualizado em {gerado_em}</div>
</header>
{link_painel}
{aviso_linha_reta}<div id="mapa"></div>
<main>
  <ol class="paradas" id="listaParadas"></ol>
  <div class="resumo">
    <div><span>Original (ida/volta)</span><b>{dist_original:.2f} km</b></div>
    <div><span>Otimizada (ida/volta)</span><b>{dist_otimizada:.2f} km</b></div>
    <div><span>Economia</span><b>{economia_km:.2f} km ({economia_pct:.1f}%)</b></div>
    <div><span>Saida &rarr; 1a parada</span><b>{dist_origem_primeira:.2f} km</b></div>
    <div><span>Ultima parada &rarr; volta</span><b>{dist_retorno:.2f} km</b></div>
  </div>
</main>
<footer><a href="../index.html">Ver todas as rotas desta data</a></footer>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore-compat.js"></script>
<script>
const PARADAS = {paradas_json};
const ORIGEM = {origem_json};
const TRACADO_IDA = {tracado_ida_json};
const TRACADO_VOLTA = {tracado_volta_json};
const DATA_ISO = '{data_atual_iso}';
const ROTULO_ROTA = {rotulo_json};
const NUMERO_MOTORISTA = {numero_motorista_json};

// Status de entrega marcado pelo motorista (Entregue / Devolucao / Voltar
// depois-Fechado). Fica salvo em 2 lugares: localStorage (instantaneo,
// funciona ate' sem internet no momento do clique) e no Firestore (nuvem,
// pra sincronizar entre o celular do motorista e o painel do supervisor).
// Escopado por dia (chave inclui DATA_ISO) para que a marcacao de hoje nao
// apareca, por engano, numa rota de um dia futuro com o mesmo cliente.
const CORES_STATUS = {{ '': '#1f4e78', entregue: '#1e7e34', devolucao: '#c00000', fechado: '#b8860b' }};

let db = null;
try {{
  firebase.initializeApp({firebase_config_json});
  db = firebase.firestore();
}} catch (e) {{
  console.error('Firebase nao inicializou (marcacao vai funcionar so neste aparelho):', e);
}}

function chaveStatus(codigo) {{
  return 'status_' + DATA_ISO + '_' + codigo;
}}
function lerStatus(codigo) {{
  return localStorage.getItem(chaveStatus(codigo)) || '';
}}
function salvarStatusRemoto(p, status) {{
  if (!db) return;
  const ref = db.collection('{firestore_colecao}').doc(DATA_ISO + '_' + p.codigo);
  if (status) {{
    ref.set({{
      data: DATA_ISO,
      rotulo: ROTULO_ROTA,
      codigo: p.codigo,
      cliente: p.cliente,
      seq: p.seq,
      status: status,
      atualizado_em: firebase.firestore.FieldValue.serverTimestamp()
    }}).catch(err => console.error('Falha ao sincronizar status:', err));
  }} else {{
    ref.delete().catch(err => console.error('Falha ao limpar status remoto:', err));
  }}
}}
function iconeNumerado(numero, cor) {{
  cor = cor || '#1f4e78';
  return L.divIcon({{
    className: 'icone-parada',
    html: '<div style="background:' + cor + ';color:#fff;border-radius:50%;width:26px;height:26px;' +
          'display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:bold;' +
          'border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4);">' + numero + '</div>',
    iconSize: [26, 26],
    iconAnchor: [13, 13]
  }});
}}

function aplicarStatus(li, status, marker, numero) {{
  li.classList.remove('status-entregue', 'status-devolucao', 'status-fechado');
  li.querySelectorAll('.status-btn').forEach(b => b.classList.remove('ativo'));
  if (status) {{
    li.classList.add('status-' + status);
    const btn = li.querySelector('.status-btn.' + status);
    if (btn) btn.classList.add('ativo');
  }}
  if (marker) {{
    marker.setIcon(iconeNumerado(numero, CORES_STATUS[status] || CORES_STATUS['']));
  }}
}}

function iniciarPagina() {{
const listaEl = document.getElementById('listaParadas');
const mapa = L.map('mapa', {{ preferCanvas: true }});
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  maxZoom: 19,
  updateWhenZooming: false,
  keepBuffer: 3,
  attribution: '&copy; OpenStreetMap contributors'
}}).addTo(mapa);

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

const referencias = {{}};  // codigo -> {{ li, marker }}, usado pra aplicar o status vindo do Firestore

PARADAS.forEach(p => {{
  const li = document.createElement('li');
  li.className = 'parada';
  const origemTxt = (p.seq === 1) ? 'saida' : 'parada anterior';
  const chegadaTxt = 'de ' + origemTxt + ': ' + p.dist_anterior_km.toFixed(2) + ' km';
  const proximaTxt = (p.dist_proxima_km === null) ? 'ultima parada'
    : ('proxima: ' + p.dist_proxima_km.toFixed(2) + ' km');
  const mapsUrl = 'https://www.google.com/maps/dir/?api=1&destination=' + p.lat + ',' + p.lon;
  li.innerHTML =
    '<div class="num">' + p.seq + '</div>' +
    '<div class="info">' +
      '<div class="codigo">' + p.codigo + '</div>' +
      '<div class="cliente">' + p.cliente + '</div>' +
      '<div class="endereco">' + p.endereco + '</div>' +
      '<div class="meta">' + chegadaTxt + ' &middot; ' + proximaTxt + '</div>' +
      '<div class="status-botoes">' +
        '<div class="status-btn entregue" data-status="entregue">Entregue</div>' +
        '<div class="status-btn devolucao" data-status="devolucao">Devolucao</div>' +
        '<div class="status-btn fechado" data-status="fechado">Voltar depois/Fechado</div>' +
      '</div>' +
      '<a class="btn-maps" href="' + mapsUrl + '" target="_blank" rel="noopener">Abrir no Google Maps</a>' +
    '</div>';
  listaEl.appendChild(li);
  pontos.push([p.lat, p.lon]);
  const statusInicial = lerStatus(p.codigo);
  const marker = L.marker([p.lat, p.lon], {{ icon: iconeNumerado(p.seq, CORES_STATUS[statusInicial]) }})
    .bindPopup('<b>' + p.seq + '. ' + p.codigo + ' - ' + p.cliente + '</b><br>' + p.endereco)
    .addTo(mapa);
  aplicarStatus(li, statusInicial, marker, p.seq);
  referencias[p.codigo] = {{ li, marker }};
  li.querySelectorAll('.status-btn').forEach(btn => {{
    btn.addEventListener('click', () => {{
      const status = btn.dataset.status;
      const novo = btn.classList.contains('ativo') ? '' : status;
      if (novo) {{
        localStorage.setItem(chaveStatus(p.codigo), novo);
      }} else {{
        localStorage.removeItem(chaveStatus(p.codigo));
      }}
      aplicarStatus(li, novo, marker, p.seq);
      salvarStatusRemoto(p, novo);
    }});
  }});
}});

// Ao abrir a pagina, busca no Firestore o status mais recente de cada
// parada (pode ter sido marcado de outro aparelho) e sobrescreve o que
// veio do localStorage, que e' so' um cache instantaneo local.
if (db) {{
  db.collection('{firestore_colecao}').where('data', '==', DATA_ISO).get().then(snapshot => {{
    snapshot.forEach(doc => {{
      const dados = doc.data();
      const ref = referencias[dados.codigo];
      if (ref && dados.status && dados.status !== lerStatus(dados.codigo)) {{
        localStorage.setItem(chaveStatus(dados.codigo), dados.status);
        const seqNum = parseInt(ref.li.querySelector('.num').textContent, 10);
        aplicarStatus(ref.li, dados.status, ref.marker, seqNum);
      }}
    }});
  }}).catch(err => console.error('Falha ao buscar status remoto:', err));
}}

if (pontos.length > 1) {{
  // TRACADO_IDA/TRACADO_VOLTA vem do OSRM (segue as ruas de verdade). Se o
  // servico falhou na hora de gerar a pagina, caimos para uma linha reta
  // entre os pontos, so pra sempre ter algo desenhado no mapa.
  const linhaIda = (TRACADO_IDA && TRACADO_IDA.length > 1) ? TRACADO_IDA : pontos;
  const linhaVolta = (TRACADO_VOLTA && TRACADO_VOLTA.length > 1)
    ? TRACADO_VOLTA
    : [pontos[pontos.length - 1], [ORIGEM.lat, ORIGEM.lon]];
  L.polyline(linhaIda, {{ color: '#1f4e78', weight: 4, opacity: 0.75 }}).addTo(mapa);
  L.polyline(linhaVolta, {{ color: '#c00000', weight: 4, opacity: 0.65, dashArray: '6 8' }}).addTo(mapa);
}}
if (pontos.length) {{
  mapa.fitBounds(pontos, {{ padding: [30, 30] }});
}}
}}  // fim de iniciarPagina()

// --- controle de acesso por senha (por motorista) ---------------------
// Protecao simples: impede abertura casual do link. Nao e' seguranca forte
// (o codigo roda todo no navegador, alguem tecnico poderia contornar), mas
// evita que quem receba o link por engano veja dados do cliente. A senha
// fica guardada no Firestore (colecao "{firestore_colecao_motoristas}"),
// nunca no codigo desta pagina.
if (!NUMERO_MOTORISTA) {{
  iniciarPagina();  // rota sem motorista definido: nao da pra proteger, abre direto
}} else {{
  const chaveDesbloqueio = 'desbloqueado_motorista_' + NUMERO_MOTORISTA;
  if (localStorage.getItem(chaveDesbloqueio) === 'sim') {{
    iniciarPagina();
  }} else {{
    document.body.classList.add('bloqueado');
    const form = document.getElementById('formSenha');
    const erroEl = document.getElementById('bloqueioErro');
    form.addEventListener('submit', ev => {{
      ev.preventDefault();
      if (!db) {{
        erroEl.textContent = 'Sem conexao com o servidor de senhas. Confira sua internet e tente de novo.';
        return;
      }}
      const senhaDigitada = document.getElementById('campoSenha').value;
      erroEl.textContent = 'Verificando...';
      db.collection('{firestore_colecao_motoristas}').doc(NUMERO_MOTORISTA).get().then(doc => {{
        if (doc.exists && doc.data().senha === senhaDigitada) {{
          localStorage.setItem(chaveDesbloqueio, 'sim');
          document.body.classList.remove('bloqueado');
          iniciarPagina();
        }} else {{
          erroEl.textContent = 'Senha incorreta.';
        }}
      }}).catch(err => {{
        erroEl.textContent = 'Erro ao verificar a senha. Confira sua internet.';
        console.error(err);
      }});
    }});
  }}
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
<meta name="theme-color" content="#1f4e78">
<title>{titulo_pagina} - PathFind</title>
<style>{estilo}</style>
</head>
<body>
<header>
  <h1>{titulo_pagina}</h1>
  <div class="marca">{marca}</div>
  <div class="sub">Atualizado em {gerado_em}</div>
</header>
<div class="filtro-data">
  <label for="seletorData">Ver rotas de:</label>
  <select id="seletorData"><option value="{data_atual_iso}">{data_atual_br} (hoje)</option></select>
  <a href="{hoje_rel}">Ir para hoje</a>
</div>
{link_painel_index}<main>
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

_PAINEL_TEMPLATE = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="theme-color" content="#1f4e78">
<title>Painel do supervisor - {data_atual_br}</title>
<style>{estilo}</style>
</head>
<body class="bloqueado">
<div class="bloqueio"><div class="bloqueio-caixa">
  <h2>Painel do supervisor</h2>
  <p>Digite a senha administrativa pra continuar.</p>
  <form id="formSenhaAdmin">
    <input type="password" id="campoSenhaAdmin" placeholder="Senha administrativa" autocomplete="current-password" required>
    <button type="submit">Entrar</button>
  </form>
  <div class="bloqueio-erro" id="bloqueioErroAdmin"></div>
</div></div>
<header>
  <h1>Painel do supervisor</h1>
  <div class="marca">{marca}</div>
  <div class="sub">Rotas de {data_atual_br}</div>
</header>
<main id="painel"></main>
<div class="painel-atualizado" id="statusConexao">Conectando ao painel em tempo real...</div>
<footer><a href="index.html">Ver lista de rotas</a></footer>

<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore-compat.js"></script>
<script>
const ROTAS = {rotas_json};
const DATA_ISO = '{data_atual_iso}';
const painelEl = document.getElementById('painel');
const statusConexaoEl = document.getElementById('statusConexao');

let db = null;
try {{
  firebase.initializeApp({firebase_config_json});
  db = firebase.firestore();
}} catch (e) {{
  statusConexaoEl.textContent = 'Nao foi possivel conectar ao painel em tempo real.';
  console.error(e);
}}

// Controle de acesso: pede a senha administrativa (guardada no Firestore,
// colecao "{firestore_colecao_motoristas}", documento "admin"). Fica
// desbloqueado so' durante esta aba/sessao (sessionStorage), nao para
// sempre -- ao fechar o navegador, pede a senha de novo.
if (sessionStorage.getItem('painel_desbloqueado') === 'sim') {{
  document.body.classList.remove('bloqueado');
}} else {{
  document.getElementById('formSenhaAdmin').addEventListener('submit', ev => {{
    ev.preventDefault();
    const erroEl = document.getElementById('bloqueioErroAdmin');
    if (!db) {{
      erroEl.textContent = 'Sem conexao. Confira sua internet e tente de novo.';
      return;
    }}
    const senhaDigitada = document.getElementById('campoSenhaAdmin').value;
    erroEl.textContent = 'Verificando...';
    db.collection('{firestore_colecao_motoristas}').doc('admin').get().then(doc => {{
      if (doc.exists && doc.data().senha === senhaDigitada) {{
        sessionStorage.setItem('painel_desbloqueado', 'sim');
        document.body.classList.remove('bloqueado');
      }} else {{
        erroEl.textContent = 'Senha incorreta.';
      }}
    }}).catch(err => {{
      erroEl.textContent = 'Erro ao verificar a senha.';
      console.error(err);
    }});
  }});
}}

const RESPOSTA_STATUS = {{ entregue: 'Entregue', devolucao: 'Devolucao', fechado: 'Voltar depois/Fechado', '': 'Pendente' }};

function renderizar(statusPorCodigo) {{
  painelEl.innerHTML = '';
  ROTAS.forEach(rota => {{
    const contagem = {{ entregue: 0, devolucao: 0, fechado: 0, pendente: 0 }};
    const linhas = rota.paradas.map(p => {{
      const status = statusPorCodigo[p.codigo] || '';
      contagem[status || 'pendente']++;
      return '<div class="painel-linha status-' + (status || 'pendente') + '">' +
        '<span class="p-seq">' + p.seq + '. ' + p.cliente + '</span>' +
        '<span class="p-status">' + RESPOSTA_STATUS[status] + '</span>' +
        '</div>';
    }}).join('');
    const card = document.createElement('div');
    card.className = 'painel-rota';
    card.innerHTML =
      '<h2>' + rota.rotulo + '</h2>' +
      '<div class="painel-contagem">' +
        '<span class="c-entregue">Entregues: ' + contagem.entregue + '</span>' +
        '<span class="c-devolucao">Devolucoes: ' + contagem.devolucao + '</span>' +
        '<span class="c-fechado">Fechados: ' + contagem.fechado + '</span>' +
        '<span class="c-pendente">Pendentes: ' + contagem.pendente + '</span>' +
      '</div>' +
      '<div class="painel-linhas">' + linhas + '</div>';
    painelEl.appendChild(card);
  }});
}}

// Ja renderiza a lista completa (todos "pendente") antes mesmo do Firestore
// responder, pra pagina nao ficar em branco -- e depois atualiza sozinha,
// em tempo real, toda vez que algum motorista marcar algo (onSnapshot).
renderizar({{}});

if (db) {{
  db.collection('{firestore_colecao}').where('data', '==', DATA_ISO)
    .onSnapshot(snapshot => {{
      const statusPorCodigo = {{}};
      snapshot.forEach(doc => {{
        const d = doc.data();
        statusPorCodigo[d.codigo] = d.status;
      }});
      renderizar(statusPorCodigo);
      const agora = new Date().toLocaleTimeString('pt-BR', {{ hour: '2-digit', minute: '2-digit', second: '2-digit' }});
      statusConexaoEl.textContent = 'Atualizado automaticamente às ' + agora;
    }}, err => {{
      statusConexaoEl.textContent = 'Erro ao conectar ao painel em tempo real.';
      console.error(err);
    }});
}}
</script>
</body>
</html>
"""


_ADMIN_TEMPLATE = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<meta name="theme-color" content="#1f4e78">
<title>Administracao de senhas</title>
<style>{estilo}</style>
</head>
<body class="bloqueado">
<div class="bloqueio"><div class="bloqueio-caixa">
  <h2>Administracao</h2>
  <p>Digite a senha administrativa pra continuar.</p>
  <form id="formSenhaAdmin">
    <input type="password" id="campoSenhaAdmin" placeholder="Senha administrativa" autocomplete="current-password" required>
    <button type="submit">Entrar</button>
  </form>
  <div class="bloqueio-erro" id="bloqueioErroAdmin"></div>
</div></div>
<header>
  <h1>Administracao de senhas</h1>
  <div class="marca">{marca}</div>
</header>
<main>
  <div class="admin-topo">
    <button id="btnGerarPadrao">Gerar senha padrao pra todo mundo</button>
  </div>
  <div class="admin-msg" id="adminMsg"></div>
  <div id="listaMotoristas"></div>
  <div class="admin-linha" style="margin-top:16px;">
    <span>Admin</span>
    <input type="text" id="novaSenhaAdmin" placeholder="Nova senha administrativa">
    <button id="btnSalvarAdmin">Salvar</button>
  </div>
</main>
<footer><a href="index.html">Ver lista de rotas</a></footer>

<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-firestore-compat.js"></script>
<script>
const NUMERO_MIN = {numero_min};
const NUMERO_MAX = {numero_max};
const adminMsgEl = document.getElementById('adminMsg');

let db = null;
try {{
  firebase.initializeApp({firebase_config_json});
  db = firebase.firestore();
}} catch (e) {{
  console.error(e);
}}

function senhaPadrao(numero) {{
  return numero + 'OG' + (numero % 10);
}}

function mensagem(texto, ehErro) {{
  adminMsgEl.textContent = texto;
  adminMsgEl.style.color = ehErro ? '#c00000' : '#1e7e34';
}}

function montarLinha(numero) {{
  const linha = document.createElement('div');
  linha.className = 'admin-linha';
  linha.innerHTML =
    '<span>' + numero + '</span>' +
    '<input type="text" id="senha-' + numero + '" placeholder="(sem senha definida)">' +
    '<button data-numero="' + numero + '">Salvar</button>';
  linha.querySelector('button').addEventListener('click', () => {{
    const valor = document.getElementById('senha-' + numero).value.trim();
    if (!valor) {{ mensagem('Digite uma senha antes de salvar (motorista ' + numero + ').', true); return; }}
    db.collection('{firestore_colecao_motoristas}').doc(String(numero)).set({{ senha: valor }})
      .then(() => mensagem('Senha do motorista ' + numero + ' salva.', false))
      .catch(err => {{ mensagem('Erro ao salvar a senha do motorista ' + numero + '.', true); console.error(err); }});
  }});
  return linha;
}}

function carregarMotoristas() {{
  const listaEl = document.getElementById('listaMotoristas');
  listaEl.innerHTML = '';
  for (let numero = NUMERO_MIN; numero <= NUMERO_MAX; numero++) {{
    listaEl.appendChild(montarLinha(numero));
    db.collection('{firestore_colecao_motoristas}').doc(String(numero)).get().then(doc => {{
      if (doc.exists && doc.data().senha) {{
        const campo = document.getElementById('senha-' + numero);
        if (campo) campo.value = doc.data().senha;
      }}
    }}).catch(err => console.error(err));
  }}
}}

document.getElementById('btnGerarPadrao').addEventListener('click', () => {{
  if (!confirm('Isso substitui a senha de TODOS os motoristas (' + NUMERO_MIN + ' a ' + NUMERO_MAX + ') pelo padrao. Continuar?')) return;
  let pendentes = 0;
  for (let numero = NUMERO_MIN; numero <= NUMERO_MAX; numero++) {{
    pendentes++;
    const senha = senhaPadrao(numero);
    db.collection('{firestore_colecao_motoristas}').doc(String(numero)).set({{ senha: senha }})
      .then(() => {{
        const campo = document.getElementById('senha-' + numero);
        if (campo) campo.value = senha;
        pendentes--;
        if (pendentes === 0) mensagem('Senhas padrao geradas para todos os motoristas.', false);
      }})
      .catch(err => {{ mensagem('Erro ao gerar as senhas padrao.', true); console.error(err); }});
  }}
}});

document.getElementById('btnSalvarAdmin').addEventListener('click', () => {{
  const valor = document.getElementById('novaSenhaAdmin').value.trim();
  if (!valor) {{ mensagem('Digite a nova senha administrativa antes de salvar.', true); return; }}
  db.collection('{firestore_colecao_motoristas}').doc('admin').set({{ senha: valor }})
    .then(() => {{ mensagem('Senha administrativa atualizada.', false); document.getElementById('novaSenhaAdmin').value = ''; }})
    .catch(err => {{ mensagem('Erro ao salvar a senha administrativa.', true); console.error(err); }});
}});

if (sessionStorage.getItem('painel_desbloqueado') === 'sim') {{
  document.body.classList.remove('bloqueado');
  carregarMotoristas();
}} else {{
  document.getElementById('formSenhaAdmin').addEventListener('submit', ev => {{
    ev.preventDefault();
    const erroEl = document.getElementById('bloqueioErroAdmin');
    if (!db) {{
      erroEl.textContent = 'Sem conexao. Confira sua internet e tente de novo.';
      return;
    }}
    const senhaDigitada = document.getElementById('campoSenhaAdmin').value;
    erroEl.textContent = 'Verificando...';
    db.collection('{firestore_colecao_motoristas}').doc('admin').get().then(doc => {{
      if (doc.exists && doc.data().senha === senhaDigitada) {{
        sessionStorage.setItem('painel_desbloqueado', 'sim');
        document.body.classList.remove('bloqueado');
        carregarMotoristas();
      }} else {{
        erroEl.textContent = 'Senha incorreta.';
      }}
    }}).catch(err => {{
      erroEl.textContent = 'Erro ao verificar a senha.';
      console.error(err);
    }});
  }});
}}
</script>
</body>
</html>
"""


def gerar_admin(docs_dir: str) -> None:
    """Gera docs/admin.html: pagina protegida pela senha administrativa,
    onde da pra ver/trocar a senha de cada motorista (720 a 731) e gerar as
    senhas padrao de uma vez."""
    html_admin = _ADMIN_TEMPLATE.format(
        estilo=_ESTILO,
        marca=MARCA,
        numero_min=NUMERO_MOTORISTA_MIN,
        numero_max=NUMERO_MOTORISTA_MAX,
        firebase_config_json=json.dumps(FIREBASE_CONFIG),
        firestore_colecao_motoristas=FIRESTORE_COLECAO_MOTORISTAS,
    )
    with open(os.path.join(docs_dir, "admin.html"), "w", encoding="utf-8") as f:
        f.write(html_admin)


def gerar_painel(
    resultados: dict[str, ResultadoRota],
    docs_dir: str,
    data_iso: str,
    data_br: str,
    gerado_em: str,
) -> None:
    """Gera docs/painel.html: uma pagina so' pro supervisor, com o status de
    entrega de TODAS as rotas do dia, atualizando sozinha em tempo real
    (Firestore onSnapshot) conforme os motoristas forem marcando."""
    rotas_json = [
        {
            "rotulo": rotulo_rota(resultado),
            "paradas": [
                {"seq": p.sequencia, "codigo": p.entrega.codigo_cliente, "cliente": p.entrega.cliente}
                for p in resultado.ordem_otimizada
            ],
        }
        for _, resultado in sorted(resultados.items())
    ]
    html_painel = _PAINEL_TEMPLATE.format(
        estilo=_ESTILO,
        marca=MARCA,
        data_atual_iso=data_iso,
        data_atual_br=data_br,
        rotas_json=json.dumps(rotas_json, ensure_ascii=False),
        firebase_config_json=json.dumps(FIREBASE_CONFIG),
        firestore_colecao=FIRESTORE_COLECAO_STATUS,
        firestore_colecao_motoristas=FIRESTORE_COLECAO_MOTORISTAS,
    )
    with open(os.path.join(docs_dir, "painel.html"), "w", encoding="utf-8") as f:
        f.write(html_painel)


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


def numero_motorista(resultado: ResultadoRota) -> str | None:
    """Numero do motorista dessa rota (ex: '720'), usado pra saber qual
    senha checar. None se a rota nao tiver motorista definido -- nesse caso
    nao da pra proteger a pagina com senha (nao ha dono definido)."""
    if not resultado.ordem_otimizada:
        return None
    primeira = resultado.ordem_otimizada[0].entrega
    codigo_m = _CODIGO_MOTORISTA_RE.search(primeira.motorista_nome or "")
    return codigo_m.group(1) if codigo_m else None


def _slug(texto: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", texto).strip("-")
    return slug or "rota"


def _resultado_para_paradas(resultado: ResultadoRota) -> list[dict]:
    return [
        {
            "seq": p.sequencia,
            "codigo": p.entrega.codigo_cliente,
            "cliente": p.entrega.cliente,
            "endereco": p.entrega.endereco,
            "lat": p.entrega.latitude,
            "lon": p.entrega.longitude,
            "dist_anterior_km": p.distancia_desde_anterior_km,
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
    painel_rel: str | None = None,
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

        aviso_linha_reta = (
            '<div class="aviso-linha-reta">Nao foi possivel calcular a distancia real de '
            'estrada agora (servico indisponivel); os valores abaixo sao em linha reta, '
            'menos precisos que o normal.</div>\n'
        ) if not resultado.usou_distancia_real else ""

        link_painel = (
            f'<a class="link-painel" href="{painel_rel}">Ver painel do supervisor (todas as rotas)</a>'
            if painel_rel else ""
        )

        numero_mot = numero_motorista(resultado)
        bloqueio_html = (
            '<div class="bloqueio"><div class="bloqueio-caixa">'
            '<h2>Rota protegida</h2>'
            '<p>Digite a senha do motorista pra ver essa rota.</p>'
            '<form id="formSenha">'
            '<input type="password" id="campoSenha" placeholder="Senha" autocomplete="current-password" required>'
            '<button type="submit">Entrar</button>'
            '</form>'
            '<div class="bloqueio-erro" id="bloqueioErro"></div>'
            '</div></div>\n'
        ) if numero_mot else ""

        html_rota = _ROTA_TEMPLATE.format(
            rotulo=rotulo,
            rotulo_json=json.dumps(rotulo, ensure_ascii=False),
            estilo=_ESTILO,
            marca=MARCA,
            gerado_em=gerado_em,
            link_painel=link_painel,
            aviso_linha_reta=aviso_linha_reta,
            dist_original=resultado.distancia_total_original_km,
            dist_otimizada=resultado.distancia_total_otimizada_km,
            economia_km=resultado.economia_km,
            economia_pct=resultado.economia_percentual,
            dist_origem_primeira=resultado.distancia_origem_primeira_km,
            dist_retorno=resultado.distancia_retorno_km,
            paradas_json=json.dumps(paradas, ensure_ascii=False),
            origem_json=origem_json,
            tracado_ida_json=json.dumps(resultado.tracado_ida),
            tracado_volta_json=json.dumps(resultado.tracado_volta),
            data_atual_iso=data_atual_iso,
            firebase_config_json=json.dumps(FIREBASE_CONFIG),
            firestore_colecao=FIRESTORE_COLECAO_STATUS,
            firestore_colecao_motoristas=FIRESTORE_COLECAO_MOTORISTAS,
            numero_motorista_json=json.dumps(numero_mot),
            bloqueio_html=bloqueio_html,
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

    link_painel_index = (
        '<a class="link-painel" href="painel.html">Ver painel do supervisor (todas as rotas)</a>'
        if painel_rel else ""
    )
    html_index = _INDEX_TEMPLATE.format(
        estilo=_ESTILO,
        marca=MARCA,
        gerado_em=gerado_em,
        titulo_pagina=titulo_pagina,
        itens="\n    ".join(itens_index),
        manifest_rel=manifest_rel,
        historico_base_rel=historico_base_rel,
        hoje_rel=hoje_rel,
        data_atual_iso=data_atual_iso,
        data_atual_br=data_atual_br,
        link_painel_index=link_painel_index,
    )
    caminho_index = os.path.join(base_dir, "index.html")
    with open(caminho_index, "w", encoding="utf-8") as f:
        f.write(html_index)
    arquivos_gerados.append("index.html")

    return arquivos_gerados


def _ler_manifest(historico_dir: str) -> list[dict]:
    caminho = os.path.join(historico_dir, "manifest.json")
    if not os.path.isfile(caminho):
        return []
    with open(caminho, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _atualizar_manifest(historico_dir: str, data_iso: str, data_br: str, gerado_em: str, total_rotas: int) -> None:
    caminho = os.path.join(historico_dir, "manifest.json")
    dias = _ler_manifest(historico_dir)
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
    data_referencia: date | None = None,
) -> list[str]:
    """Gera a pagina 'de hoje' (docs/index.html e docs/rotas/*.html -- o link
    fixo que os motoristas devem usar todo dia) e uma copia arquivada em
    docs/historico/<AAAA-MM-DD>/, alimentando o filtro de data da pagina
    inicial. Retorna a lista de arquivos gerados (paths relativos a
    docs_dir), util para o watcher decidir o que commitar.

    `data_referencia` e' a data REAL a que os dados se referem (normalmente
    extraida do nome do arquivo do PathFind pelo watcher, ex:
    "rastro_rotas_22-07-2026.txt" -> 22/07/2026) -- nao a data em que o
    script rodou. Isso importa quando dois arquivos de dias diferentes sao
    processados no mesmo dia (ex: um atrasado); sem essa distincao, os dois
    cairiam no mesmo dia do historico e um sobrescreveria o outro. Se nao
    for informada, usa a data de hoje (uso direto/testes).

    A pagina "de hoje" (docs/index.html, o link fixo que os motoristas usam)
    SO e' atualizada se `data_referencia` for a maior data ja vista ate agora
    (olhando o manifest do historico). Isso evita que, ao processar um
    arquivo atrasado/antigo depois de um mais recente, a pagina "de hoje"
    volte a mostrar dados velhos -- ela sempre reflete a data mais nova
    conhecida, nao "o ultimo arquivo processado"."""
    agora = datetime.now()
    gerado_em = agora.strftime("%d/%m/%Y %H:%M")
    data_ref = data_referencia or agora.date()
    data_iso = data_ref.strftime("%Y-%m-%d")
    data_br = data_ref.strftime("%d/%m/%Y")

    historico_dir = os.path.join(docs_dir, "historico")
    dia_dir = os.path.join(historico_dir, data_iso)
    os.makedirs(historico_dir, exist_ok=True)

    manifest_atual = _ler_manifest(historico_dir)
    maior_data_existente = max((d.get("data", "") for d in manifest_atual), default="")
    e_a_mais_recente = data_iso >= maior_data_existente

    arquivos_gerados = []

    # Pagina "de hoje": link fixo que nao muda de endereco dia a dia. So
    # atualiza se esta for a data mais recente conhecida (ver docstring).
    if e_a_mais_recente:
        arquivos_hoje = _gerar_paginas(
            resultados, docs_dir, origem_lat, origem_lon, gerado_em,
            titulo_pagina="Cargas otimizadas",
            manifest_rel="historico/manifest.json",
            historico_base_rel="historico/",
            hoje_rel="index.html",
            data_atual_iso=data_iso,
            data_atual_br=data_br,
            painel_rel="../painel.html",
        )
        arquivos_gerados.extend(arquivos_hoje)

        gerar_painel(resultados, docs_dir, data_iso, data_br, gerado_em)
        arquivos_gerados.append("painel.html")

        gerar_admin(docs_dir)
        arquivos_gerados.append("admin.html")

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
