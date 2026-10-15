import logging
import time

import requests

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9",
}


class Http:
    def __init__(self, pause: float = 1.5, timeout: int = 25):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.pause = pause
        self.timeout = timeout
        self._last = 0.0

    def _wait(self):
        delta = time.monotonic() - self._last
        if delta < self.pause:
            time.sleep(self.pause - delta)
        self._last = time.monotonic()

    def get(self, url: str, **kw) -> requests.Response:
        self._wait()
        resp = self.session.get(url, timeout=self.timeout, **kw)
        resp.raise_for_status()
        return resp

    def post(self, url: str, **kw) -> requests.Response:
        self._wait()
        resp = self.session.post(url, timeout=self.timeout, **kw)
        resp.raise_for_status()
        return resp
