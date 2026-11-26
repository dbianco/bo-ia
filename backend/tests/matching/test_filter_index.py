"""Plan 3: the inverted filter index gives exactly what `cumple_filtros` gives."""
import random

import numpy as np
import pytest

from src.matching.filter_index import FilterIndex
from src.search.filters import cumple_filtros


def select(value):
    return {"tipo": "seleccion", "valor": value}


def between(value):
    return {"tipo": "rango_numerico", "valor": value}


def allowed(index: FilterIndex, metadata: dict) -> list[int]:
    return np.flatnonzero(index.allowed(metadata)).tolist()


def test_a_subscription_without_filters_accepts_every_document() -> None:
    index = FilterIndex()
    index.add(0, {})
    assert allowed(index, {}) == [0]
    assert allowed(index, {"provincia": "Córdoba"}) == [0]


def test_the_subscription_carries_the_filter_and_the_document_the_metadata() -> None:
    index = FilterIndex()
    index.add(0, {"provincia": select("Córdoba")})
    index.add(1, {"provincia": select("San Luis")})
    index.add(2, {"provincia": select("Córdoba"), "municipio": select("Noetinger")})
    index.add(3, {})
    assert allowed(index, {"provincia": "Córdoba"}) == [0, 3]
    assert allowed(index, {"provincia": "Córdoba", "municipio": "Noetinger"}) == [0, 2, 3]
    assert allowed(index, {"municipio": "Noetinger"}) == [3]


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(None, []), (5, [2]), (10, [0, 2]), (15, [0, 2]), (20, [0, 1, 2]), (25, [1]), ("15", [0, 2]), ("x", []), ([15], [])],
)
def test_ranges(amount, expected) -> None:
    index = FilterIndex()
    index.add(0, {"monto": between("10,20")})
    index.add(1, {"monto": between("20,")})
    index.add(2, {"monto": between(",20")})
    assert allowed(index, {"monto": amount}) == expected


def test_removed_slots_are_not_allowed_and_can_be_used_again() -> None:
    index = FilterIndex()
    index.add(0, {"a": select("x"), "monto": between("1,5")})
    index.add(1, {"a": select("x")})
    index.remove(0)
    assert allowed(index, {"a": "x", "monto": 3}) == [1]
    index.add(0, {"a": select("y")})
    assert allowed(index, {"a": "x", "monto": 3}) == [1]
    assert allowed(index, {"a": "y"}) == [0]
    index.remove(0)
    index.remove(1)
    assert allowed(index, {"a": "x"}) == []


def test_a_malformed_stored_range_matches_nothing_and_breaks_nothing() -> None:
    """`cumple_filtros` raises on it, which would stop matching for everybody."""
    index = FilterIndex()
    index.add(0, {"monto": between("abc,")})
    index.add(1, {})
    assert allowed(index, {"monto": 3}) == [1]


VALUES = ["x", "y", "z", 4, 4.0, True, None, ["x"], {"k": 1}, "4"]
RANGES = ["1,5", "2,", ",3", "3,3", ",", "-1.5,2.5", "5,1"]
NUMBERS = [0, 1, 2.5, 3, "3", 7, True, None, "x", float("nan"), float("inf"), [1]]


def _filters(rng: random.Random) -> dict:
    filters = {}
    for key in ("a", "b"):
        if rng.random() < 0.4:
            filters[key] = select(rng.choice(VALUES))
    for key in ("n", "m"):
        if rng.random() < 0.4:
            filters[key] = between(rng.choice(RANGES))
    if rng.random() < 0.05:  # the installation changed the type of the filter
        filters["a"] = between(rng.choice(RANGES))
    return filters


def _metadata(rng: random.Random) -> dict:
    metadata = {k: rng.choice(VALUES) for k in ("a", "b", "c") if rng.random() < 0.7}
    metadata.update({k: rng.choice(NUMBERS) for k in ("n", "m") if rng.random() < 0.7})
    return metadata


@pytest.mark.parametrize("seed", range(60))
def test_random_histories_equal_the_reference(seed: int) -> None:
    rng = random.Random(seed)
    index, stored = FilterIndex(), {}
    for _ in range(120):
        slot = rng.randrange(60)
        if slot in stored:
            if rng.random() < 0.5:
                index.remove(slot)
                del stored[slot]
        else:
            stored[slot] = _filters(rng)
            index.add(slot, stored[slot])
        if rng.random() < 0.3:
            metadata = _metadata(rng)
            expected = sorted(s for s, f in stored.items() if cumple_filtros(metadata, f))
            assert allowed(index, metadata) == expected, (metadata, stored)


def test_many_ranges_with_changes_in_between() -> None:
    rng = random.Random(1)
    index, stored = FilterIndex(), {}
    for slot in range(5000):
        low = rng.randrange(1000)
        stored[slot] = {"monto": between(f"{low},{low + rng.randrange(200)}")}
        index.add(slot, stored[slot])
        if slot % 500 == 17:
            index.remove(slot)
            del stored[slot]
        if slot % 400 == 0:
            value = rng.randrange(1200)
            assert allowed(index, {"monto": value}) == sorted(
                s for s, f in stored.items() if cumple_filtros({"monto": value}, f)
            )
