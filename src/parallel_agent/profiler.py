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
        self._last_cpu_seconds = 0.0
        self._last_sample_time = 0.0

    def start(self) -> None:
        self._last_cpu_seconds, _ = self._tree_totals()
        self._last_sample_time = time.perf_counter()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self) -> ResourceSamples:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, self.interval * 4))
        return self.samples

    def _sample(self) -> None:
        while not self._stop.wait(self.interval):
            sampled_at = time.perf_counter()
            cpu_seconds, rss = self._tree_totals()
            elapsed = sampled_at - self._last_sample_time
            cpu_delta = max(0.0, cpu_seconds - self._last_cpu_seconds)
            cpu_percent = cpu_delta / elapsed * 100.0 if elapsed > 0 else 0.0
            self.samples.cpu.append(cpu_percent)
            self.samples.rss.append(rss)
            self._last_cpu_seconds = cpu_seconds
            self._last_sample_time = sampled_at

    def _tree_totals(self) -> tuple[float, int]:
        processes = [self._process]
        try:
            processes.extend(self._process.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        cpu_seconds = 0.0
        rss = 0
        for process in processes:
            try:
                times = process.cpu_times()
                cpu_seconds += times.user + times.system
                rss += process.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return cpu_seconds, rss


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
