"""A lock for many readers or one writer. Waiting writers go first, so that a
steady flow of searches does not hold back an update for ever."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class ReadWriteLock:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._readers = 0
        self._writing = False
        self._waiting = 0

    @contextmanager
    def read(self) -> Iterator[None]:
        with self._condition:
            while self._writing or self._waiting:
                self._condition.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._condition:
                self._readers -= 1
                if not self._readers:
                    self._condition.notify_all()

    @contextmanager
    def write(self) -> Iterator[None]:
        with self._condition:
            self._waiting += 1
            while self._writing or self._readers:
                self._condition.wait()
            self._waiting -= 1
            self._writing = True
        try:
            yield
        finally:
            with self._condition:
                self._writing = False
                self._condition.notify_all()
