from __future__ import annotations

import os
import statistics
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

import psutil


@dataclass
class ResourceSamples:
    cpu: list[float] = field(default_factory=list)
    rss: list[int] = field(default_factory=list)

    @property
    def cpu_mean(self) -> float:
        return statistics.fmean(self.cpu) if self.cpu else 0.0

    @property
    def cpu_peak(self) -> float:
        return max(self.cpu, default=0.0)

    @property
    def rss_peak(self) -> int:
        return max(self.rss, default=0)


class ResourceMonitor:
    def __init__(self, interval: float = 0.05) -> None:
        self.interval = interval
        self.samples = ResourceSamples()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process = psutil.Process(os.getpid())

    def start(self) -> None:
        self._process.cpu_percent(None)
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self) -> ResourceSamples:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, self.interval * 4))
        return self.samples

    def _sample(self) -> None:
        while not self._stop.wait(self.interval):
            children = self._process.children(recursive=True)
            cpu = self._process.cpu_percent(None)
            rss = self._process.memory_info().rss
            for child in children:
                try:
                    cpu += child.cpu_percent(None)
                    rss += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.samples.cpu.append(cpu)
            self.samples.rss.append(rss)


@contextmanager
def measured(interval: float = 0.05):
    monitor = ResourceMonitor(interval)
    monitor.start()
    started = time.perf_counter()
    payload: dict[str, object] = {}
    try:
        yield payload
    finally:
        payload["runtime_seconds"] = time.perf_counter() - started
        payload["resources"] = monitor.stop()

