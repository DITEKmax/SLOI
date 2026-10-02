from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from typing import Any, Callable

import psutil


METRICS = ("gpu_utilization_pct", "gpu_memory_used_mb", "gpu_temperature_c", "gpu_power_w", "gpu_clock_mhz", "cpu_utilization_pct", "system_ram_used_mb", "process_tree_rss_mb")


class Aggregate:
    def __init__(self):
        self.samples = 0
        self.first: float | None = None
        self.last: float | None = None
        self.values: dict[str, dict[str, float]] = {}
        self.previous: dict[str, Any] | None = None
        self.lock = threading.Lock()

    def add(self, sample: dict[str, Any]) -> None:
        with self.lock:
            timestamp = float(sample["monotonic"])
            self.samples += 1
            self.first = timestamp if self.first is None else self.first
            delta = max(0, timestamp - self.last) if self.last is not None else 0
            for key in METRICS:
                current = sample.get(key)
                if current is None or not math.isfinite(float(current)):
                    continue
                state = self.values.setdefault(key, {"sum": 0.0, "count": 0, "peak": float(current), "area": 0.0, "seconds": 0.0})
                state["sum"] += float(current)
                state["count"] += 1
                state["peak"] = max(state["peak"], float(current))
                previous = self.previous.get(key) if self.previous else None
                if previous is not None and delta > 0:
                    state["area"] += (float(previous) + float(current)) * 0.5 * delta
                    state["seconds"] += delta
            self.last = timestamp
            self.previous = sample.copy()

    def summary(self) -> dict[str, Any]:
        with self.lock:
            result: dict[str, Any] = {"samples": self.samples, "aggregation": "time_weighted_mean_sampled_peak"}
            for key in METRICS:
                state = self.values.get(key)
                result[key] = None if not state else {
                    "average": round(state["area"] / state["seconds"] if state["seconds"] else state["sum"] / state["count"], 3),
                    "peak": round(state["peak"], 3),
                }
            return result


class Telemetry:
    def __init__(self, interval: float = 1.0, history_seconds: int = 60, gpu_index: int = 0):
        self.interval = interval
        self.gpu_index = gpu_index
        self.lock = threading.RLock()
        self.history: deque[dict[str, Any]] = deque(maxlen=max(2, int(history_seconds / interval)))
        self.stop_event = threading.Event()
        self.listener: Callable[[dict[str, Any]], None] | None = None
        self.nvml: Any = None
        self.handle: Any = None
        self.gpu_error: str | None = None
        self.process = psutil.Process()
        self.started = time.monotonic()
        try:
            import pynvml
            pynvml.nvmlInit()
            self.handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
            self.nvml = pynvml
        except Exception:
            self.gpu_error = "NVML недоступен: NVIDIA GPU или драйвер не обнаружены."
        psutil.cpu_percent(interval=None)
        self.current = self.sample()

    def _gpu(self, function: str, *args: Any) -> Any:
        try:
            return getattr(self.nvml, function)(self.handle, *args)
        except Exception:
            return None

    def sample(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        rss = 0
        for process in [self.process, *self.process.children(recursive=True)]:
            try:
                rss += process.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            frequency = psutil.cpu_freq()
        except (OSError, NotImplementedError):
            frequency = None
        try:
            battery = psutil.sensors_battery()
        except (OSError, NotImplementedError):
            battery = None
        data: dict[str, Any] = {
            "timestamp": time.time(), "monotonic": time.monotonic(), "cpu_utilization_pct": psutil.cpu_percent(interval=None),
            "cpu_frequency_mhz": round(frequency.current) if frequency else None,
            "system_ram_used_mb": round(memory.used / 1024**2, 1), "system_ram_total_mb": round(memory.total / 1024**2, 1),
            "system_ram_available_mb": round(memory.available / 1024**2, 1), "process_tree_rss_mb": round(rss / 1024**2, 1),
            "battery_percent": battery.percent if battery else None, "on_ac_power": battery.power_plugged if battery else None,
            "gpu_name": None, "gpu_available": self.handle is not None, "gpu_message": self.gpu_error,
            "gpu_utilization_pct": None, "gpu_memory_used_mb": None, "gpu_memory_total_mb": None,
            "gpu_temperature_c": None, "gpu_power_w": None, "gpu_clock_mhz": None, "gpu_throttle_reasons": None,
        }
        if self.handle is not None:
            name = self._gpu("nvmlDeviceGetName")
            data["gpu_name"] = name.decode() if isinstance(name, bytes) else name
            util = self._gpu("nvmlDeviceGetUtilizationRates")
            mem = self._gpu("nvmlDeviceGetMemoryInfo")
            data["gpu_utilization_pct"] = util.gpu if util else None
            if mem:
                data["gpu_memory_used_mb"] = round(mem.used / 1024**2, 1)
                data["gpu_memory_total_mb"] = round(mem.total / 1024**2, 1)
            data["gpu_temperature_c"] = self._gpu("nvmlDeviceGetTemperature", 0)
            power = self._gpu("nvmlDeviceGetPowerUsage")
            data["gpu_power_w"] = round(power / 1000, 2) if power is not None else None
            data["gpu_clock_mhz"] = self._gpu("nvmlDeviceGetClockInfo", 0)
            data["gpu_throttle_reasons"] = self._gpu("nvmlDeviceGetCurrentClocksThrottleReasons")
        return data

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True, name="telemetry")
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                sample = self.sample()
                with self.lock:
                    self.current = sample
                    self.history.append(sample)
                if self.listener:
                    self.listener(sample)
            except Exception:
                pass
            self.stop_event.wait(self.interval)

    def snapshot(self, include_history: bool = True) -> dict[str, Any]:
        with self.lock:
            result = dict(self.current)
            if include_history:
                result["history"] = [{key: row.get(key) for key in ("timestamp", "gpu_utilization_pct", "gpu_memory_used_mb", "cpu_utilization_pct", "system_ram_used_mb")} for row in self.history]
            return result

    def close(self) -> None:
        self.stop_event.set()
        if hasattr(self, "thread"):
            self.thread.join(timeout=3)
        if self.nvml:
            try:
                self.nvml.nvmlShutdown()
            except Exception:
                pass
