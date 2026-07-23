from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ApiMetrics:
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    requests_total: Counter = field(default_factory=Counter)
    in_flight: int = 0
    duration_ms_sum: float = 0.0
    duration_count: int = 0

    def started(self) -> None:
        with self._lock:
            self.in_flight += 1

    def finished(self, *, route: str, status: str, elapsed_ms: float) -> None:
        with self._lock:
            self.in_flight = max(0, self.in_flight - 1)
            self.requests_total[(route, status)] += 1
            self.duration_ms_sum += max(0.0, float(elapsed_ms))
            self.duration_count += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "in_flight": self.in_flight,
                "requests_total": {
                    f"{route}|{status}": count
                    for (route, status), count in self.requests_total.items()
                },
                "duration_ms_avg": (
                    self.duration_ms_sum / self.duration_count if self.duration_count else 0.0
                ),
                "duration_count": self.duration_count,
            }

    def prometheus_text(self) -> str:
        snapshot = self.snapshot()
        lines = [
            "# HELP agent_api_in_flight Current in-flight API requests.",
            "# TYPE agent_api_in_flight gauge",
            f"agent_api_in_flight {snapshot['in_flight']}",
            "# HELP agent_api_requests_total Total API requests by route and status.",
            "# TYPE agent_api_requests_total counter",
        ]
        for key, count in sorted(snapshot["requests_total"].items()):
            route, status = key.split("|", 1)
            lines.append(
                f'agent_api_requests_total{{route="{route}",status="{status}"}} {count}'
            )
        lines.extend(
            [
                "# HELP agent_api_request_duration_ms_avg Average completed request duration.",
                "# TYPE agent_api_request_duration_ms_avg gauge",
                f"agent_api_request_duration_ms_avg {snapshot['duration_ms_avg']:.3f}",
            ]
        )
        return "\n".join(lines) + "\n"
