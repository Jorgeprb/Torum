import logging
from datetime import UTC, datetime, timedelta
from threading import Event, Thread

from app.db.session import SessionLocal
from app.news.service import NewsService, get_global_news_settings

logger = logging.getLogger(__name__)


class NewsProviderScheduler:
    def __init__(self) -> None:
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="torum-news-provider-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._sync_if_due()
            except Exception:
                logger.exception("News provider scheduler failed")
            self._stop.wait(60)

    def _sync_if_due(self) -> None:
        with SessionLocal() as db:
            settings = get_global_news_settings(db)
            if (
                not settings.provider_enabled
                or not settings.auto_sync_enabled
                or settings.provider.upper() == "MANUAL"
            ):
                return
            now = datetime.now(UTC)
            last = settings.last_sync_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            if last is not None and now - last < timedelta(minutes=settings.sync_interval_minutes):
                return
            result = NewsService(db).sync_provider()
            logger.info("News provider sync %s: saved=%s zones=%s errors=%s", result.status, result.saved, result.zones_generated, len(result.errors))


news_provider_scheduler = NewsProviderScheduler()
