"""Plan 4: filters of the search engine."""
import random

import numpy as np
import pytest

from src.config.installation import FiltroRangoNumerico, FiltroSeleccion
from src.engine.metadata import MetadataIndex, resolve
from src.search.filters import FiltroNoDeclarado, ValorDeFiltroInvalido

DECLARED = [
    FiltroSeleccion(clave="provincia", etiqueta="P"),
    FiltroSeleccion(clave="municipio", etiqueta="M"),
    FiltroRangoNumerico(clave="monto", etiqueta="M"),
]


def rows(index: MetadataIndex, requested: dict | None = None, **dates) -> list[int]:
    mask = index.mask(resolve(requested or {}, DECLARED), **dates)
    return list(range(len(index))) if mask is None else np.flatnonzero(mask).tolist()


@pytest.fixture()
def index() -> MetadataIndex:
    index = MetadataIndex()
    index.add({"provincia": "Córdoba", "monto": 100}, 10, 2)
    index.add({"provincia": "Córdoba", "municipio": "Noetinger", "monto": 250.5}, 20, 1)
    index.add({"provincia": "San Luis"}, 30, 1)
    index.add({}, 40, 1)
    return index


def test_each_row_of_a_document_has_its_metadata(index) -> None:
    assert rows(index) == [0, 1, 2, 3, 4]
    assert rows(index, {"provincia": "Córdoba"}) == [0, 1, 2]
    assert rows(index, {"provincia": "Córdoba", "municipio": "Noetinger"}) == [2]
    assert rows(index, {"provincia": "Nowhere"}) == []


def test_several_values_of_a_key_are_alternatives(index) -> None:
    conditions = resolve({"provincia": "Córdoba"}, DECLARED)
    conditions["provincia"].values.append("San Luis")
    assert np.flatnonzero(index.mask(conditions)).tolist() == [0, 1, 2, 3]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("100,250.5", [0, 1, 2]), ("101,", [2]), (",100", [0, 1]), (",", [0, 1, 2, 3, 4]), ("300,", []), ("200,100", [])],
)
def test_ranges(index, value: str, expected: list) -> None:
    assert rows(index, {"monto": value}) == expected


def test_dates(index) -> None:
    assert rows(index, date_from=20) == [2, 3, 4]
    assert rows(index, date_to=20) == [0, 1, 2]
    assert rows(index, {"provincia": "Córdoba"}, date_from=15, date_to=25) == [2]


def test_removed_rows_are_never_allowed(index) -> None:
    index.remove(0, 2)
    assert rows(index) == [2, 3, 4]
    assert rows(index, {"provincia": "Córdoba"}) == [2]


def test_metadata_of_a_document_may_change(index) -> None:
    index.update(0, 2, {"provincia": "San Luis", "monto": 7}, 35)
    assert rows(index, {"provincia": "Córdoba"}) == [2]
    assert rows(index, {"provincia": "San Luis"}) == [0, 1, 3]
    assert rows(index, {"monto": "5,10"}) == [0, 1]
    assert rows(index, date_from=35) == [0, 1, 4]


def test_wrong_requests_fail_like_in_postgres() -> None:
    with pytest.raises(FiltroNoDeclarado):
        resolve({"unknown": "x"}, DECLARED)
    with pytest.raises(ValorDeFiltroInvalido):
        resolve({"monto": "abc,"}, DECLARED)


@pytest.mark.parametrize("seed", range(20))
def test_random_histories_equal_a_plain_loop(seed: int) -> None:
    rng = random.Random(seed)
    index, stored = MetadataIndex(), {}
    provinces, towns = ["A", "B", "C"], ["x", "y"]

    def metadata() -> dict:
        data = {}
        if rng.random() < 0.8:
            data["provincia"] = rng.choice([*provinces, 4, None, ["A"]])
        if rng.random() < 0.5:
            data["municipio"] = rng.choice(towns)
        if rng.random() < 0.6:
            data["monto"] = rng.choice([1, 2.5, "3", 10, None, "x", True])
        return data

    def number(value):
        if isinstance(value, bool) or value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    for _ in range(80):
        action = rng.random()
        if action < 0.6 or not stored:
            data, day, count = metadata(), rng.randrange(20), rng.randrange(1, 4)
            first = index.add(data, day, count)
            stored[first] = (count, data, day)
        elif action < 0.75:
            first = rng.choice(list(stored))
            index.remove(first, stored.pop(first)[0])
        else:
            first = rng.choice(list(stored))
            count = stored[first][0]
            stored[first] = (count, metadata(), rng.randrange(20))
            index.update(first, count, *stored[first][1:])
        requested = {}
        if rng.random() < 0.5:
            requested["provincia"] = rng.choice(provinces)
        if rng.random() < 0.3:
            requested["municipio"] = rng.choice(towns)
        low, high = rng.choice([(None, None), (2, None), (None, 3), (2, 10)])
        if low is not None or high is not None:
            requested["monto"] = f"{'' if low is None else low},{'' if high is None else high}"
        day_from = rng.choice([None, 5, 12])
        expected = []
        for first, (count, data, day) in stored.items():
            value = number(data.get("monto"))
            if (
                all(data.get(k) == requested[k] for k in ("provincia", "municipio") if k in requested)
                and ("monto" not in requested or value is not None)
                and (low is None or value >= low)
                and (high is None or value <= high)
                and (day_from is None or day >= day_from)
            ):
                expected.extend(range(first, first + count))
        assert rows(index, requested, date_from=day_from) == sorted(expected)
