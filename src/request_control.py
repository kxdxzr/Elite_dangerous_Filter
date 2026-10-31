"""Shared, conservative Spansh request pacing and bounded transient retries."""
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
import math
import random
import threading
import time
from urllib.parse import urlsplit

from search_recovery import transient

_context = threading.local()


@contextmanager
def context(stop=None, status=None):
    previous = getattr(_context, 'value', (None, None))
    _context.value = (stop if stop is not None else previous[0], status or previous[1])
    try:
        yield
    finally:
        _context.value = previous


class RequestControl:
    def __init__(self, concurrency=2, interval=.35, *, clock=time.monotonic,
                 sleep=time.sleep, wall_clock=time.time, jitter=lambda: random.uniform(0, .4)):
        self.slots = threading.BoundedSemaphore(concurrency)
        self.lock = threading.Lock()
        self.clock, self.sleep, self.wall_clock, self.jitter = clock, sleep, wall_clock, jitter
        self.interval = interval
        self.next_start = self.cooldown = 0.0
        self.failures = self.successes = 0

    @staticmethod
    def check(stop):
        if stop is not None and stop.is_set():
            raise InterruptedError('Search cancelled; results are incomplete.')

    def turn(self, stop):
        while True:
            self.check(stop)
            with self.lock:
                now = self.clock()
                delay = max(self.next_start, self.cooldown) - now
                if delay <= 0:
                    self.next_start = now + self.interval * (2 ** self.failures)
                    return
            if stop is not None:
                if stop.wait(min(.2, delay)):
                    self.check(stop)
            else:
                self.sleep(min(.2, delay))

    def retry_after(self, error):
        raw = (getattr(error, 'headers', None) or {}).get('Retry-After')
        if not raw:
            return 0
        try:
            delay = float(raw)
        except (ValueError, TypeError):
            try:
                delay = parsedate_to_datetime(raw).timestamp() - self.wall_clock()
            except (ValueError, TypeError, OverflowError):
                return 0
        return max(0, delay) if math.isfinite(delay) else 0

    def run(self, operation, stop=None, status=None):
        for attempt in range(3):  # One initial attempt, at most two automatic retries.
            self.check(stop)
            while not self.slots.acquire(timeout=.1):
                self.check(stop)
            try:
                self.turn(stop)
                try:
                    result = operation()
                except Exception as error:
                    if not transient(error):
                        raise
                    delay = max(1.5 * (2 ** attempt) + self.jitter(), self.retry_after(error))
                    with self.lock:
                        self.failures, self.successes = min(3, self.failures + 1), 0
                        self.cooldown = max(self.cooldown, self.clock() + delay)
                    # Retrying for a long server-requested delay is a UI decision,
                    # but every Spansh caller still respects its shared cooldown.
                    if attempt == 2 or delay > 8:
                        error.elite_retry_exhausted = True
                        error.elite_retry_attempts = attempt + 1
                        raise
                    if hasattr(error, 'close'):
                        error.close()
                    if status:
                        status('上游暂时异常，正在冷却后重试…')
                else:
                    with self.lock:
                        self.successes += 1
                        if self.successes >= 4:
                            self.failures = max(0, self.failures - 1)
                            self.successes = 0
                    return result
            finally:
                self.slots.release()


shared = RequestControl()


def request(url, operation):
    parsed = urlsplit(url)
    if parsed.hostname != 'spansh.co.uk' or not parsed.path.startswith('/api/'):
        return operation()
    stop, status = getattr(_context, 'value', (None, None))
    return shared.run(operation, stop, status)
