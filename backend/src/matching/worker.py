"""The thread that matches documents in the background, in the backend process."""
from __future__ import annotations

import threading

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from src.background import PollingThread
from src.matching.matchers import Matcher
from src.matching.queue import process_queue

DEFAULT_POLL_SECONDS = 1.0
CHUNK = 50  # documents between one look at whether to stop and the next


class MatchingWorker(PollingThread):
    def __init__(self, engine: Engine, matcher: Matcher, *, poll_seconds: float = DEFAULT_POLL_SECONDS) -> None:
        self._sessions = sessionmaker(bind=engine)
        self._matcher = matcher
        super().__init__("matching", self._process, poll_seconds)

    def _process(self, stop: threading.Event) -> None:
        with self._sessions() as session:
            while not stop.is_set() and process_queue(session, self._matcher, limit=CHUNK):
                pass
