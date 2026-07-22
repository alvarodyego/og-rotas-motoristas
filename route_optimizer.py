"""
Otimizacao de sequencia de entrega por proximidade geografica.

AVISO IMPORTANTE: este algoritmo otimiza SOMENTE por distancia geografica
(nearest neighbor sobre distancia real de Haversine). Ele NAO considera
janela de horario, prazo de entrega combinado com o cliente, prioridade de
cliente, capacidade do veiculo por trecho, nem transito. Se a operacao
precisar respeitar horarios de entrega combinados, essa restricao precisa
ser adicionada depois (ex: nearest neighbor com janela de tempo, ou um
solver de VRPTW). Use o resultado como um ponto de partida geografico, nao
como a rota final se houver compromissos de horario com os clientes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from parsing import Entrega

RAIO_TERRA_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia real (em km) entre duas coordenadas, considerando a curvatura da Terra."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * RAIO_TERRA_KM * math.asin(math.sqrt(a))


@dataclass
class ParadaOtimizada:
    sequencia: int
    entrega: Entrega
    distancia_ate_proxima_km: float | None  # None na ultima parada


@dataclass
class ResultadoRota:
    rota: str
    ordem_original: list[Entrega]
    ordem_otimizada: list[ParadaOtimizada]
    distancia_total_original_km: float
    distancia_total_otimizada_km: float

    @property
    def economia_km(self) -> float:
        return self.distancia_total_original_km - self.distancia_total_otimizada_km

    @property
    def economia_percentual(self) -> float:
        if self.distancia_total_original_km == 0:
            return 0.0
        return (self.economia_km / self.distancia_total_original_km) * 100


def _distancia_total(entregas: list[Entrega]) -> float:
    total = 0.0
    for a, b in zip(entregas, entregas[1:]):
        total += haversine_km(a.latitude, a.longitude, b.latitude, b.longitude)
    return total


def _ordem_original_por_horario(entregas: list[Entrega]) -> list[Entrega]:
    """Ordem original do plano, pelo horario de entrega/chegada informado.

    Usada tanto para calcular a distancia 'antes' quanto para escolher o
    ponto de partida da otimizacao (parada mais cedo = proxy do ponto mais
    proximo do CD).
    """

    def chave(e: Entrega) -> str:
        return e.hora_chegada or e.hora_entrega_original or "99:99"

    return sorted(entregas, key=chave)


def otimizar_rota(rota: str, entregas: list[Entrega]) -> ResultadoRota:
    """Aplica nearest neighbor (Haversine) a uma rota e compara com o plano original."""
    ordem_original = _ordem_original_por_horario(entregas)
    distancia_original = _distancia_total(ordem_original)

    if not entregas:
        return ResultadoRota(rota, [], [], 0.0, 0.0)

    restantes = list(ordem_original)
    atual = restantes.pop(0)
    caminho = [atual]
    while restantes:
        proximo = min(
            restantes,
            key=lambda e: haversine_km(atual.latitude, atual.longitude, e.latitude, e.longitude),
        )
        restantes.remove(proximo)
        caminho.append(proximo)
        atual = proximo

    paradas: list[ParadaOtimizada] = []
    for i, entrega in enumerate(caminho):
        if i + 1 < len(caminho):
            dist = haversine_km(
                entrega.latitude, entrega.longitude,
                caminho[i + 1].latitude, caminho[i + 1].longitude,
            )
        else:
            dist = None
        paradas.append(ParadaOtimizada(sequencia=i + 1, entrega=entrega, distancia_ate_proxima_km=dist))

    distancia_otimizada = _distancia_total(caminho)

    return ResultadoRota(
        rota=rota,
        ordem_original=ordem_original,
        ordem_otimizada=paradas,
        distancia_total_original_km=distancia_original,
        distancia_total_otimizada_km=distancia_otimizada,
    )


def otimizar_todas(rotas: dict[str, list[Entrega]]) -> dict[str, ResultadoRota]:
    return {rota: otimizar_rota(rota, entregas) for rota, entregas in rotas.items()}
