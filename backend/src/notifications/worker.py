"""The thread that sends emails and builds digests, in the backend process."""
from __future__ import annotations

import threading

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from src.background import PollingThread
from src.notifications.digests import build_digests
from src.notifications.outbox import send_pending
from src.notifications.settings import NotificationSettings

DEFAULT_POLL_SECONDS = 5.0
CHUNK = 20  # emails between one look at whether to stop and the next


class NotificationWorker(PollingThread):
    def __init__(
        self, engine: Engine, settings: NotificationSettings, *, poll_seconds: float = DEFAULT_POLL_SECONDS
    ) -> None:
        self._sessions = sessionmaker(bind=engine)
        self._settings = settings
        super().__init__("notifications", self._deliver, poll_seconds)

    def _deliver(self, stop: threading.Event) -> None:
        with self._sessions() as session:
            build_digests(session, self._settings)
            while not stop.is_set() and send_pending(session, self._settings, limit=CHUNK):
                pass
