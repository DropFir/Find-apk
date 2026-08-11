from __future__ import annotations

from datetime import date, timedelta
import json
import subprocess
import threading
import time
import xml.etree.ElementTree as ElementTree
from urllib.parse import urlparse
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from lan_share.production_queue import ProductionQueue


class ExternalProductionMonitor:
    """Poll an APKBA monitor and complete exact Android package matches."""

    def __init__(
        self,
        source_url: str,
        *,
        initial_lookback_days: int = 30,
        public_sitemap_url: str = "https://www.apkba.com/apps-sitemap.xml",
        public_refresh_seconds: int = 300,
    ) -> None:
        self.source_url = source_url.rstrip("/") + "/"
        self.initial_lookback_days = max(1, initial_lookback_days)
        self.public_sitemap_url = public_sitemap_url
        self.public_refresh_seconds = max(60, public_refresh_seconds)
        self._known_packages: dict[str, dict[str, object]] = {}
        self._initialized = False
        self._state_lock = threading.Lock()
        self._last_checked_at: float | None = None
        self._last_error: str | None = None
        self._last_new_completions = 0
        self._total_completions = 0
        self._last_public_checked_at: float | None = None
        self._last_public_error: str | None = None
        self._public_packages = 0

    @staticmethod
    def _fetch_text(url: str) -> str:
        request = Request(
            url,
            headers={
                "Accept": "application/json, application/xml, text/xml",
                "User-Agent": "Find-APK-LAN-Monitor/1.0",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                return response.read().decode("utf-8")
        except OSError:
            completed = subprocess.run(
                [
                    "/usr/bin/curl",
                    "-fsS",
                    "--max-time",
                    "20",
                    request.full_url,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=25,
            )
            return completed.stdout

    def _fetch_date(self, selected_date: str) -> list[dict[str, object]]:
        url = urljoin(self.source_url, "api/summary")
        payload = json.loads(
            self._fetch_text(f"{url}?{urlencode({'date': selected_date})}")
        )
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise ValueError("external monitor returned an invalid jobs list")
        return [job for job in jobs if isinstance(job, dict)]

    @staticmethod
    def _display_name(job: dict[str, object]) -> str:
        display_name = str(job.get("display_name") or "")
        package_name = str(job.get("package_name") or "")
        marker = f"_{package_name}_"
        if package_name and marker in display_name:
            name = display_name.split(marker, 1)[0]
        else:
            name = display_name.rsplit("_", 1)[0]
        return name.replace("_", " ").replace("-", " ")

    def _refresh_public_packages(self) -> None:
        now = time.time()
        if (
            self._last_public_checked_at is not None
            and now - self._last_public_checked_at
            < self.public_refresh_seconds
        ):
            return
        try:
            root = ElementTree.fromstring(
                self._fetch_text(self.public_sitemap_url)
            )
            public_packages: dict[str, dict[str, object]] = {}
            for element in root.iter():
                if not element.tag.endswith("loc") or not element.text:
                    continue
                path_parts = [
                    part
                    for part in urlparse(element.text).path.split("/")
                    if part
                ]
                if len(path_parts) < 2 or "." not in path_parts[-1]:
                    continue
                package_name = path_parts[-1]
                public_packages[package_name.casefold()] = {
                    "display_name": path_parts[-2],
                    "package_name": package_name,
                    "_source_url": "https://www.apkba.com/search?q=",
                }
            self._known_packages.update(public_packages)
            with self._state_lock:
                self._last_public_checked_at = now
                self._last_public_error = None
                self._public_packages = len(public_packages)
        except Exception as error:
            with self._state_lock:
                self._last_public_checked_at = now
                self._last_public_error = f"{type(error).__name__}: {error}"

    def check(
        self,
        deliveries: list[dict[str, object]],
        queue: ProductionQueue,
    ) -> int:
        try:
            lookback = self.initial_lookback_days if not self._initialized else 2
            selected = date.today()
            for offset in range(lookback):
                selected_date = (selected - timedelta(days=offset)).isoformat()
                for job in self._fetch_date(selected_date):
                    package_name = str(job.get("package_name") or "").strip()
                    if package_name:
                        self._known_packages[package_name.casefold()] = job
            self._refresh_public_packages()

            queue.sync_and_list(deliveries)
            completed = 0
            for delivery in deliveries:
                application_id = str(
                    delivery.get("application_id") or ""
                ).strip()
                if not application_id:
                    continue
                job = self._known_packages.get(application_id.casefold())
                if job is None:
                    continue
                if queue.mark_external_completed(
                    str(delivery["delivery_key"]),
                    keyword=str(delivery["keyword"]),
                    source_url=str(
                        job.get("_source_url") or self.source_url
                    ),
                    matched_name=self._display_name(job),
                    matched_package=str(job.get("package_name") or ""),
                ):
                    completed += 1

            with self._state_lock:
                self._initialized = True
                self._last_checked_at = time.time()
                self._last_error = None
                self._last_new_completions = completed
                self._total_completions += completed
            return completed
        except Exception as error:
            with self._state_lock:
                self._last_checked_at = time.time()
                self._last_error = f"{type(error).__name__}: {error}"
                self._last_new_completions = 0
            return 0

    def status(self) -> dict[str, object]:
        with self._state_lock:
            return {
                "source_url": self.source_url,
                "last_checked_at": self._last_checked_at,
                "last_error": self._last_error,
                "last_new_completions": self._last_new_completions,
                "total_completions": self._total_completions,
                "known_packages": len(self._known_packages),
                "public_sitemap_url": self.public_sitemap_url,
                "last_public_checked_at": self._last_public_checked_at,
                "last_public_error": self._last_public_error,
                "public_packages": self._public_packages,
            }
