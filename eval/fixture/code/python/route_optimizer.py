"""Hub-to-hub route selection for the linehaul network.

The network is a directed graph of regional hubs connected by trucking
and air legs, each with its own cost and transit time. Routing purely
on cost tends to funnel everything through one cheap-but-slow hub and
creates a bottleneck at peak season, so this blends cost and speed
rather than optimizing either alone.
"""

import heapq
from collections import defaultdict
from dataclasses import dataclass

SPEED_WEIGHT_DEFAULT = 0.4
MAX_HOPS = 6  # beyond this a route is operationally unworkable


class UnreachableDestinationError(Exception):
    """Raised when no path exists between two hubs within MAX_HOPS."""


@dataclass
class Leg:
    origin: str
    destination: str
    cost_cents: int
    transit_hours: float
    carrier: str = "own-fleet"


@dataclass
class RoutePlan:
    hubs: list[str]
    legs: list[Leg]
    total_cost_cents: int
    total_transit_hours: float


def leg_score(leg: Leg, speed_weight: float) -> float:
    """Blend cost and transit time into a single comparable weight.

    speed_weight of 0 behaves like pure cheapest-path routing; 1.0
    behaves like pure fastest-path routing. Ops asks for around 0.4
    in normal operations and closer to 0.8 in peak season, when a
    missed delivery window costs more than the extra fuel spend.
    """
    normalized_cost = leg.cost_cents / 100.0
    return (1 - speed_weight) * normalized_cost + speed_weight * leg.transit_hours


class LinehaulNetwork:
    """A directed multigraph of hubs used to plan multi-leg shipment routes."""

    def __init__(self):
        self._adjacency: dict[str, list[Leg]] = defaultdict(list)

    def add_leg(self, leg: Leg) -> None:
        self._adjacency[leg.origin].append(leg)

    def neighbors(self, hub: str) -> list[Leg]:
        return self._adjacency.get(hub, [])

    def find_best_route(
        self, origin: str, destination: str, speed_weight: float = SPEED_WEIGHT_DEFAULT
    ) -> RoutePlan:
        """Dijkstra over blended leg scores, capped at MAX_HOPS.

        We cap hop count rather than let the search run unbounded: an
        eight-hop route is never something dispatch would actually
        book, even if the math says it's marginally cheaper.
        """
        frontier = [(0.0, origin, [origin], [], 0)]
        best_seen: dict[str, float] = {origin: 0.0}

        while frontier:
            score, hub, path, legs_used, hops = heapq.heappop(frontier)
            if hub == destination:
                return RoutePlan(
                    hubs=path,
                    legs=legs_used,
                    total_cost_cents=sum(l.cost_cents for l in legs_used),
                    total_transit_hours=sum(l.transit_hours for l in legs_used),
                )
            if hops >= MAX_HOPS:
                continue
            for leg in self.neighbors(hub):
                new_score = score + leg_score(leg, speed_weight)
                if new_score >= best_seen.get(leg.destination, float("inf")):
                    continue
                best_seen[leg.destination] = new_score
                heapq.heappush(
                    frontier,
                    (new_score, leg.destination, path + [leg.destination], legs_used + [leg], hops + 1),
                )

        raise UnreachableDestinationError(f"no route from {origin} to {destination} within {MAX_HOPS} hops")

    def reachable_hubs(self, origin: str) -> set[str]:
        seen = {origin}
        stack = [origin]
        while stack:
            hub = stack.pop()
            for leg in self.neighbors(hub):
                if leg.destination not in seen:
                    seen.add(leg.destination)
                    stack.append(leg.destination)
        return seen


def estimate_peak_season_delay(base_transit_hours: float, congestion_factor: float) -> float:
    """Pad a normal-season transit estimate for holiday-volume congestion."""
    return base_transit_hours * (1 + congestion_factor)
