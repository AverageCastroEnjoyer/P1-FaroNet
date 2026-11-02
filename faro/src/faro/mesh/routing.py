"""Búsqueda de rutas con un mínimo configurable de relays."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence


class RouteUnavailable(ValueError):
    """No hay una ruta que cumpla el mínimo de relays."""


def find_route(
    adjacency: Mapping[str, Sequence[str]],
    source: str,
    destination: str,
    *,
    min_relays: int = 3,
) -> tuple[str, ...]:
    """Devuelve la ruta válida más corta, incluido origen y destino.

    Los relays son los nodos entre source y destination. La búsqueda
    mantiene estado del número de relays para no elegir una ruta corta
    que incumpla el mínimo de anonimato.
    """
    if source == destination:
        raise ValueError("origen y destino deben ser distintos")
    if min_relays < 0:
        raise ValueError("min_relays no puede ser negativo")

    # Cada estado guarda nodo actual, cantidad de relays y ruta recorrida.
    queue = deque([(source, 0, (source,))])
    visited = {(source, 0)}

    while queue:
        current, relay_count, path = queue.popleft()

        for neighbor in sorted(adjacency.get(current, ())):
            if neighbor in path:
                continue

            if neighbor == destination:
                if relay_count >= min_relays:
                    return path + (destination,)
                continue

            next_count = relay_count + 1
            state = (neighbor, next_count)
            if state in visited:
                continue

            visited.add(state)
            queue.append((neighbor, next_count, path + (neighbor,)))

    raise RouteUnavailable(
        f"no se encontró ruta con al menos {min_relays} relays"
    )