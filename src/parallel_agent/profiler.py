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
    def __init__(
        self, interval: float = 0.05, *, include_children: bool = True
    ) -> None:
        self.interval = interval
        self.include_children = include_children
        self.samples = ResourceSamples()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._process = psutil.Process(os.getpid())
        self._cpu_by_pid: dict[int, float] = {}
        self._last_sample_time = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        processes = self._processes()
        baselines: dict[int, float] = {}
        for process in processes:
            cpu_seconds = self._cpu_seconds(process)
            if cpu_seconds is not None:
                baselines[process.pid] = cpu_seconds
        self._cpu_by_pid = baselines
        self._last_sample_time = time.perf_counter()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self) -> ResourceSamples:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, self.interval * 4))
        self._record_sample()
        return self.samples

    def _sample(self) -> None:
        while not self._stop.wait(self.interval):
            self._record_sample()

    def _processes(self) -> list[psutil.Process]:
        processes = [self._process]
        if self.include_children:
            try:
                processes.extend(self._process.children(recursive=True))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return processes

    @staticmethod
    def _cpu_seconds(process: psutil.Process) -> float | None:
        try:
            times = process.cpu_times()
            return times.user + times.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def _record_sample(self) -> None:
        with self._lock:
            sampled_at = time.perf_counter()
            elapsed = sampled_at - self._last_sample_time
            if elapsed <= 0:
                return
            cpu_delta = 0.0
            rss = 0
            current_cpu: dict[int, float] = {}
            for process in self._processes():
                cpu_seconds = self._cpu_seconds(process)
                if cpu_seconds is None:
                    continue
                current_cpu[process.pid] = cpu_seconds
                previous = self._cpu_by_pid.get(process.pid)
                if previous is not None:
                    cpu_delta += max(0.0, cpu_seconds - previous)
                try:
                    rss += process.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.samples.cpu.append(cpu_delta / elapsed * 100.0)
            self.samples.rss.append(rss)
            self._cpu_by_pid = current_cpu
            self._last_sample_time = sampled_at


@contextmanager
def measured(interval: float = 0.05, *, include_children: bool = True):
    monitor = ResourceMonitor(interval, include_children=include_children)
    monitor.start()
    started = time.perf_counter()
    payload: dict[str, object] = {}
    try:
        yield payload
    finally:
        payload["runtime_seconds"] = time.perf_counter() - started
        payload["resources"] = monitor.stop()
