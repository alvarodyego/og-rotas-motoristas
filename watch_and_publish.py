"""
Vigia uma pasta (ex: a pasta sincronizada do Google Drive) esperando o novo
relatorio .txt do PathFind. Quando um arquivo novo (ou modificado) aparece:

  1. faz o parsing e a otimizacao de rota (parsing.py + route_optimizer.py)
  2. gera o site em docs/ (site_generator.py)
  3. faz commit + push no git, publicando no GitHub Pages

Uso:
    python watch_and_publish.py "C:\\caminho\\da\\pasta\\do\\Drive"

Deixe esta janela aberta (ou registre como tarefa agendada do Windows) para
que a publicacao aconteca sozinha sempre que a PathFind exportar um novo
arquivo nessa pasta. Nao ha necessidade de rodar mais nada manualmente.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time
from datetime import datetime

from parsing import parse_arquivo
from route_optimizer import otimizar_todas
from site_generator import gerar_site

PADRAO_ARQUIVO_PADRAO = "rastro_rotas*.txt"
ARQUIVO_ESTADO = ".watch_state.json"
INTERVALO_SEGUNDOS = 30

# Coordenada fixa de saida do caminhao (ponto de partida usado para otimizar
# a sequencia de entrega). Ajuste aqui se o ponto de saida mudar, ou passe
# --origem-lat / --origem-lon na linha de comando.
ORIGEM_LAT_PADRAO = -7.22722092594843
ORIGEM_LON_PADRAO = -48.24978544427654


def log(mensagem: str) -> None:
    """print() com timestamp, e com flush imediato (necessario quando a saida
    esta indo para um arquivo de log em vez de um console interativo)."""
    print(f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] {mensagem}", flush=True)


def _carregar_estado(caminho_estado: str) -> dict:
    if os.path.isfile(caminho_estado):
        with open(caminho_estado, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _salvar_estado(caminho_estado: str, estado: dict) -> None:
    with open(caminho_estado, "w", encoding="utf-8") as f:
        json.dump(estado, f)


def _listar_candidatos(pasta: str, padrao: str) -> list[str]:
    return [
        os.path.join(pasta, nome)
        for nome in os.listdir(pasta)
        if fnmatch.fnmatch(nome.lower(), padrao.lower())
    ]


def _publicar_no_git(repo_dir: str, mensagem: str) -> None:
    def rodar(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo_dir, check=True)

    rodar("add", "docs")
    resultado = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=repo_dir
    )
    if resultado.returncode == 0:
        log("Nada mudou no site, pulando commit.")
        return
    rodar("commit", "-m", mensagem)
    rodar("push")
    log("Publicado no GitHub Pages.")


def processar_arquivo(caminho_txt: str, repo_dir: str, origem_lat: float, origem_lon: float) -> None:
    log(f"Processando {caminho_txt} ...")
    rotas = parse_arquivo(caminho_txt)
    if not rotas:
        log("  Nenhuma entrega reconhecida nesse arquivo, ignorando.")
        return

    total = sum(len(v) for v in rotas.values())
    log(f"  {len(rotas)} rota(s) / {total} entrega(s).")

    resultados = otimizar_todas(rotas, origem_lat, origem_lon)
    docs_dir = os.path.join(repo_dir, "docs")
    gerar_site(resultados, docs_dir, origem_lat, origem_lon)

    nome_arquivo = os.path.basename(caminho_txt)
    _publicar_no_git(repo_dir, f"Atualiza rotas a partir de {nome_arquivo}")


def watch(pasta_observada: str, repo_dir: str, padrao: str, origem_lat: float, origem_lon: float) -> None:
    caminho_estado = os.path.join(repo_dir, ARQUIVO_ESTADO)
    estado = _carregar_estado(caminho_estado)

    log(f"Vigiando: {pasta_observada} (padrao: {padrao})")
    log(f"Repositorio: {repo_dir}")
    log(f"Ponto de saida do caminhao: {origem_lat}, {origem_lon}")
    log("Iniciado. Pressione Ctrl+C para parar (se estiver rodando visivel).")

    while True:
        try:
            for caminho in _listar_candidatos(pasta_observada, padrao):
                try:
                    mtime = os.path.getmtime(caminho)
                except OSError:
                    continue
                chave = os.path.abspath(caminho)
                if estado.get(chave) == mtime:
                    continue  # ja processado, sem mudanca
                try:
                    processar_arquivo(caminho, repo_dir, origem_lat, origem_lon)
                except Exception as exc:  # nao derruba o watcher por um arquivo ruim
                    log(f"  Erro ao processar {caminho}: {exc}")
                    continue
                estado[chave] = mtime
                _salvar_estado(caminho_estado, estado)
        except Exception as exc:
            log(f"Erro no ciclo de verificacao: {exc}")

        time.sleep(INTERVALO_SEGUNDOS)


def main() -> None:
    ap = argparse.ArgumentParser(description="Vigia uma pasta e publica as rotas otimizadas no GitHub Pages")
    ap.add_argument("pasta_observada", help="Pasta onde o PathFind/Drive deixa o .txt do dia")
    ap.add_argument("--repo-dir", default=os.path.dirname(os.path.abspath(__file__)),
                     help="Pasta do repositorio git local (padrao: pasta deste script)")
    ap.add_argument("--padrao", default=PADRAO_ARQUIVO_PADRAO,
                     help=f"Padrao de nome de arquivo a vigiar (padrao: {PADRAO_ARQUIVO_PADRAO})")
    ap.add_argument("--log-file", default=None,
                     help="Se definido, grava a saida nesse arquivo em vez do console "
                          "(necessario ao rodar sem janela, via pythonw/tarefa agendada)")
    ap.add_argument("--origem-lat", type=float, default=ORIGEM_LAT_PADRAO,
                     help=f"Latitude do ponto de saida do caminhao (padrao: {ORIGEM_LAT_PADRAO})")
    ap.add_argument("--origem-lon", type=float, default=ORIGEM_LON_PADRAO,
                     help=f"Longitude do ponto de saida do caminhao (padrao: {ORIGEM_LON_PADRAO})")
    args = ap.parse_args()

    if not os.path.isdir(args.pasta_observada):
        sys.exit(f"Pasta nao encontrada: {args.pasta_observada}")

    if args.log_file:
        log_f = open(args.log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_f
        sys.stderr = log_f

    watch(args.pasta_observada, args.repo_dir, args.padrao, args.origem_lat, args.origem_lon)


if __name__ == "__main__":
    main()
