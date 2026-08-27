"""Decide which MCP servers a participant is asked to rate.

Rating all five servers is a long sitting, so each participant gets a subset.
Choosing that subset uniformly at random would leave coverage lumpy at the sample
sizes this study is likely to reach — with 20 participants and 2 servers each,
pure chance can easily give one server 12 ratings and another 4.

Instead the subset is *balanced*: the servers with the fewest responses so far are
picked first, with ties broken at random. Coverage stays within one of even at all
times, while an individual participant still cannot predict what they will get.
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

from survey.config import Server

ASSIGNED_SEPARATOR = "|"


def parse_assigned(value: Any) -> list[str]:
    """`"calendar|slack"` -> `["calendar", "slack"]`. Tolerates blanks and lists."""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    return [part for part in str(value).split(ASSIGNED_SEPARATOR) if part]


def format_assigned(server_keys: Iterable[str]) -> str:
    return ASSIGNED_SEPARATOR.join(server_keys)


def counts_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """How many stored responses cover each server, from their `assigned_servers`."""
    counter: Counter[str] = Counter()
    for row in rows:
        for key in parse_assigned(row.get("assigned_servers")):
            counter[key] += 1
    return dict(counter)


def choose_servers(
    servers: Sequence[Server],
    counts: Mapping[str, int],
    how_many: int,
    rng: random.Random | None = None,
) -> list[Server]:
    """Pick `how_many` servers, least-covered first, ties broken at random.

    Shuffling before a *stable* sort is what randomises ties: equal-count servers
    keep their shuffled order, while the sort still puts under-covered servers first.
    """
    if how_many <= 0:
        return []
    rng = rng or random
    pool = list(servers)
    rng.shuffle(pool)
    pool.sort(key=lambda server: counts.get(server.key, 0))
    return pool[: min(how_many, len(pool))]
