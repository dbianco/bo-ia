"""The thread that matches documents in the background, in the backend process."""
from __future__ import annotations

import logging
import threading

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from src.matching.matchers import Matcher
from src.matching.queue import process_queue

logger = logging.getLogger("contextcrawl.matching")

DEFAULT_POLL_SECONDS = 1.0
CHUNK = 50  # documents between one look at whether to stop and the next


class MatchingWorker:
    def __init__(self, engine: Engine, matcher: Matcher, *, poll_seconds: float = DEFAULT_POLL_SECONDS) -> None:
        self._sessions = sessionmaker(bind=engine)
        self._matcher = matcher
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="matching", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 30) -> None:
        """Waits for the document in hand. What is left stays in the queue."""
        self._stop.set()
        self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with self._sessions() as session:
                    while not self._stop.is_set() and process_queue(session, self._matcher, limit=CHUNK):
                        pass
            except Exception:  # the database is not available, for instance: try again
                logger.exception("The matching queue could not be processed")
            self._stop.wait(self._poll_seconds)
