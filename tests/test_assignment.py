"""Tests for balanced server assignment."""

import random
from collections import Counter

import pytest

from survey.assignment import (
    choose_servers,
    counts_from_rows,
    format_assigned,
    parse_assigned,
)
from survey.config import Item, Server


def server(key: str) -> Server:
    return Server(
        key=key,
        title=key.title(),
        enabled=True,
        scenario="",
        tools=(Item("t", "d"),),
        assets=(Item("a", "d"),),
        blast_tools=("t",),
        blast_assets=(Item("a", "d"),),
        blast_live=frozenset({("a", "t")}),
    )


SERVERS = [server(k) for k in ("calendar", "github", "slack", "filesystem", "sqlite")]


class TestParsing:
    def test_round_trip(self):
        assert parse_assigned(format_assigned(["calendar", "slack"])) == ["calendar", "slack"]

    def test_blank_means_nothing_assigned(self):
        assert parse_assigned("") == []
        assert parse_assigned(None) == []

    def test_accepts_a_list(self):
        assert parse_assigned(["calendar"]) == ["calendar"]


class TestCounts:
    def test_counts_each_server_once_per_response(self):
        rows = [
            {"assigned_servers": "calendar|github"},
            {"assigned_servers": "calendar|slack"},
        ]
        assert counts_from_rows(rows) == {"calendar": 2, "github": 1, "slack": 1}

    def test_rows_without_an_assignment_are_ignored(self):
        assert counts_from_rows([{"assigned_servers": ""}, {}]) == {}


class TestChoosing:
    def test_picks_the_requested_number(self):
        assert len(choose_servers(SERVERS, {}, 2, random.Random(0))) == 2

    def test_never_repeats_a_server(self):
        chosen = choose_servers(SERVERS, {}, 3, random.Random(1))
        assert len({s.key for s in chosen}) == 3

    def test_prefers_the_least_covered_servers(self):
        counts = {"calendar": 9, "github": 9, "slack": 0, "filesystem": 0, "sqlite": 9}
        chosen = {s.key for s in choose_servers(SERVERS, counts, 2, random.Random(0))}
        assert chosen == {"slack", "filesystem"}

    def test_a_single_starved_server_is_always_included(self):
        counts = {"calendar": 5, "github": 5, "slack": 5, "filesystem": 5, "sqlite": 1}
        for seed in range(20):
            chosen = {s.key for s in choose_servers(SERVERS, counts, 2, random.Random(seed))}
            assert "sqlite" in chosen

    def test_ties_are_broken_at_random_not_by_config_order(self):
        seen = set()
        for seed in range(40):
            chosen = choose_servers(SERVERS, {}, 2, random.Random(seed))
            seen.add(tuple(sorted(s.key for s in chosen)))
        assert len(seen) > 1, "assignment is deterministic; ties are not being shuffled"

    def test_asking_for_more_than_exists_returns_everything(self):
        assert len(choose_servers(SERVERS, {}, 99, random.Random(0))) == len(SERVERS)

    def test_asking_for_none_returns_nothing(self):
        assert choose_servers(SERVERS, {}, 0, random.Random(0)) == []


class TestBalanceOverASimulatedStudy:
    """The property that matters: coverage stays even as participants arrive."""

    @pytest.mark.parametrize("participants", [10, 25, 60])
    def test_coverage_stays_within_one_of_even(self, participants):
        rng = random.Random(7)
        counts: Counter[str] = Counter()
        for _ in range(participants):
            for chosen in choose_servers(SERVERS, counts, 2, rng):
                counts[chosen.key] += 1

        tally = [counts.get(s.key, 0) for s in SERVERS]
        assert max(tally) - min(tally) <= 1, tally
        assert sum(tally) == participants * 2

    def test_pure_random_would_be_worse(self):
        """Sanity check that the balancing is doing something."""
        rng = random.Random(7)
        random_tally = Counter()
        for _ in range(25):
            for chosen in rng.sample(SERVERS, 2):
                random_tally[chosen.key] += 1
        spread_random = max(random_tally.values()) - min(random_tally.values())

        balanced: Counter[str] = Counter()
        for _ in range(25):
            for chosen in choose_servers(SERVERS, balanced, 2, rng):
                balanced[chosen.key] += 1
        spread_balanced = max(balanced.values()) - min(balanced.values())

        assert spread_balanced < spread_random

    def test_participants_do_not_all_get_the_same_pair(self):
        rng = random.Random(3)
        counts: Counter[str] = Counter()
        pairs = set()
        for _ in range(20):
            chosen = choose_servers(SERVERS, counts, 2, rng)
            pairs.add(tuple(sorted(s.key for s in chosen)))
            for server_ in chosen:
                counts[server_.key] += 1
        assert len(pairs) >= 5
