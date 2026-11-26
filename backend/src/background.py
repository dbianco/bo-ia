"""A thread that does something again and again, in the backend process."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable


class PollingThread:
    """Runs `work` every `poll_seconds`. An error is logged and tried again."""

    def __init__(self, name: str, work: Callable[[threading.Event], None], poll_seconds: float) -> None:
        self._name = name
        self._work = work
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 30) -> None:
        """Waits for the work in hand."""
        self._stop.set()
        self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._work(self._stop)
            except Exception:  # the database is not available, for instance
                logging.getLogger(f"contextcrawl.{self._name}").exception("The work failed; it will be tried again")
            self._stop.wait(self._poll_seconds)
