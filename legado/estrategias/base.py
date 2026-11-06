"""
Módulo Base para el Patrón Estrategia Cuantitativa.
Define la interfaz unificada que debe implementar cualquier estrategia nueva.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set, Tuple


class EstrategiaBase(ABC):
    """Clase base abstracta para todas las estrategias de trading."""

    id: str = "base"
    nombre: str = "Estrategia Base"
    descripcion: str = ""
    autor: str = "Comunidad"
    activos_recomendados: List[str] = []
    temporalidades_permitidas: Set[str] = {"15m", "1h"}
    horario_operativo: str = "24/7"
    parametros_por_defecto: Dict[str, Any] = {}

    @abstractmethod
    def evaluar(
        self,
        ind: Dict[str, Any],
        tp: float,
        sl: float,
        fee: float,
        spread: float,
        min_profit_pct: float,
        round_trip_cost: float,
        net_tp_manual: float,
        df: Optional[Any] = None,
    ) -> Tuple[Dict[str, Any], float, bool, List[str], float]:
        """
        Evalúa los filtros deterministas y devuelve:
        (strategy_metrics, effective_net_tp, candidate_eligible, filter_failures, minimum_strategy_net_tp)
        """
        pass

    def to_dict(self) -> Dict[str, Any]:
        """Serializa la ficha técnica de la estrategia para la API y el Frontend."""
        return {
            "id": self.id,
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "autor": self.autor,
            "activos_recomendados": self.activos_recomendados,
            "temporalidades_permitidas": sorted(list(self.temporalidades_permitidas)),
            "horario_operativo": self.horario_operativo,
            "parametros_por_defecto": self.parametros_por_defecto,
        }
