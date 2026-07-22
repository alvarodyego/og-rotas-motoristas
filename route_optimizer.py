"""
Otimizacao de sequencia de entrega por proximidade geografica.

AVISO IMPORTANTE: este algoritmo otimiza SOMENTE por distancia geografica
(nearest neighbor sobre distancia real de Haversine), partindo da coordenada
fixa de saida do caminhao. Ele NAO considera janela de horario, prazo de
entrega combinado com o cliente, prioridade de cliente, capacidade do
veiculo por trecho, nem transito. Se a operacao precisar respeitar horarios
de entrega combinados, essa restricao precisa ser adicionada depois (ex:
nearest neighbor com janela de tempo, ou um solver de VRPTW). Use o
resultado como um ponto de partida geografico, nao como a rota final se
houver compromissos de horario com os clientes.
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
    ordem_otimizada: list[ParadaOtimizada]
    distancia_origem_primeira_km: float  # saida do caminhao ate a 1a parada (ordem otimizada)
    distancia_retorno_km: float  # ultima parada de volta ate o ponto de partida (ordem otimizada)
    distancia_total_original_km: float  # ida (saida->1a...ultima) + volta, na ordem original do plano
    distancia_total_otimizada_km: float  # ida (saida->1a...ultima) + volta, na ordem otimizada

    @property
    def economia_km(self) -> float:
        return self.distancia_total_original_km - self.distancia_total_otimizada_km

    @property
    def economia_percentual(self) -> float:
        if self.distancia_total_original_km == 0:
            return 0.0
        return (self.economia_km / self.distancia_total_original_km) * 100


def _distancia_total(pontos: list[tuple[float, float]]) -> float:
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(pontos, pontos[1:]):
        total += haversine_km(lat1, lon1, lat2, lon2)
    return total


def otimizar_rota(
    rota: str,
    entregas: list[Entrega],
    origem_lat: float,
    origem_lon: float,
) -> ResultadoRota:
    """Aplica nearest neighbor (Haversine) a uma rota, partindo da coordenada
    de saida do caminhao e voltando a ela no final, e compara com o plano
    original (ordem em que as entregas aparecem no relatorio do PathFind)."""
    if not entregas:
        return ResultadoRota(rota, [], 0.0, 0.0, 0.0, 0.0)

    origem = (origem_lat, origem_lon)

    pontos_originais = [origem] + [(e.latitude, e.longitude) for e in entregas] + [origem]
    distancia_original = _distancia_total(pontos_originais)

    restantes = list(entregas)
    atual_lat, atual_lon = origem_lat, origem_lon
    caminho: list[Entrega] = []
    while restantes:
        proximo = min(
            restantes,
            key=lambda e: haversine_km(atual_lat, atual_lon, e.latitude, e.longitude),
        )
        restantes.remove(proximo)
        caminho.append(proximo)
        atual_lat, atual_lon = proximo.latitude, proximo.longitude

    distancia_origem_primeira = haversine_km(
        origem_lat, origem_lon, caminho[0].latitude, caminho[0].longitude
    )
    distancia_retorno = haversine_km(
        caminho[-1].latitude, caminho[-1].longitude, origem_lat, origem_lon
    )

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

    pontos_otimizados = [origem] + [(e.latitude, e.longitude) for e in caminho] + [origem]
    distancia_otimizada = _distancia_total(pontos_otimizados)

    return ResultadoRota(
        rota=rota,
        ordem_otimizada=paradas,
        distancia_origem_primeira_km=distancia_origem_primeira,
        distancia_retorno_km=distancia_retorno,
        distancia_total_original_km=distancia_original,
        distancia_total_otimizada_km=distancia_otimizada,
    )


def otimizar_todas(
    rotas: dict[str, list[Entrega]],
    origem_lat: float,
    origem_lon: float,
) -> dict[str, ResultadoRota]:
    return {
        rota: otimizar_rota(rota, entregas, origem_lat, origem_lon)
        for rota, entregas in rotas.items()
    }
