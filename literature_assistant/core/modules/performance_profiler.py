"""
Performance Profiler Module

Tools for profiling and measuring performance of the scoring system.
"""

import time
import functools
from typing import Dict, Callable, Any, Optional
from contextlib import contextmanager
from collections import defaultdict
from modules.logger_config import get_logger

logger = get_logger("scoring_system.profiler")


class PerformanceProfiler:
    """Profiler for measuring execution time of different components"""

    def __init__(self):
        """Initialize profiler"""
        self.timings: Dict[str, list] = defaultdict(list)
        self.call_counts: Dict[str, int] = defaultdict(int)

    @contextmanager
    def timer(self, name: str):
        """
        Context manager for timing code blocks

        Usage:
            profiler = PerformanceProfiler()
            with profiler.timer("evidence_classification"):
                score = classifier.classify_evidence(text)
        """
        start_time = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start_time
            self.timings[name].append(elapsed)
            self.call_counts[name] += 1
            logger.debug(f"Timer '{name}': {elapsed:.6f}s")

    def add_timing(self, name: str, elapsed: float) -> None:
        """Manually add timing measurement"""
        self.timings[name].append(elapsed)
        self.call_counts[name] += 1

    def report(self) -> Dict[str, Dict[str, Any]]:
        """
        Generate profiling report

        Returns:
            Dictionary with statistics for each timed section
        """
        report = {}

        for name, times in self.timings.items():
            if not times:
                continue

            total_time = sum(times)
            avg_time = total_time / len(times)
            min_time = min(times)
            max_time = max(times)

            # Calculate percentiles
            sorted_times = sorted(times)
            p50 = sorted_times[len(sorted_times) // 2]
            p95 = sorted_times[int(len(sorted_times) * 0.95)]
            p99 = sorted_times[int(len(sorted_times) * 0.99)]

            report[name] = {
                "count": self.call_counts[name],
                "total_seconds": round(total_time, 6),
                "avg_seconds": round(avg_time, 6),
                "min_seconds": round(min_time, 6),
                "max_seconds": round(max_time, 6),
                "p50_seconds": round(p50, 6),
                "p95_seconds": round(p95, 6),
                "p99_seconds": round(p99, 6),
            }

        return report

    def print_report(self, top_n: int = 10) -> None:
        """Print profiling report to console"""
        report = self.report()

        if not report:
            print("No timing data collected")
            return

        print("\n" + "=" * 80)
        print("PERFORMANCE PROFILING REPORT")
        print("=" * 80)

        # Sort by total time
        sorted_items = sorted(report.items(), key=lambda x: x[1]["total_seconds"], reverse=True)

        for i, (name, stats) in enumerate(sorted_items[:top_n], 1):
            print(f"\n{i}. {name}")
            print(f"   Calls: {stats['count']}")
            print(f"   Total: {stats['total_seconds']:.6f}s")
            print(f"   Avg:   {stats['avg_seconds']:.6f}s")
            print(f"   Min:   {stats['min_seconds']:.6f}s")
            print(f"   Max:   {stats['max_seconds']:.6f}s")
            print(f"   P95:   {stats['p95_seconds']:.6f}s")

    def clear(self) -> None:
        """Clear all recorded timings"""
        self.timings.clear()
        self.call_counts.clear()


# Global profiler instance
_default_profiler: Optional[PerformanceProfiler] = None


def get_profiler() -> PerformanceProfiler:
    """Get or create global profiler instance"""
    global _default_profiler
    if _default_profiler is None:
        _default_profiler = PerformanceProfiler()
    return _default_profiler


def timed(profile_name: str, profiler: Optional[PerformanceProfiler] = None):
    """
    Decorator for timing function execution

    Usage:
        @timed("evidence_classification")
        def classify_evidence(text):
            return ...
    """
    prof = profiler or get_profiler()

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            with prof.timer(profile_name or func.__name__):
                return func(*args, **kwargs)

        return wrapper

    return decorator


class MemoryProfiler:
    """Simple memory usage tracker"""

    @staticmethod
    def get_object_size(obj: Any) -> int:
        """Get size of object in bytes"""
        import sys
        return sys.getsizeof(obj)

    @staticmethod
    def format_bytes(num_bytes: int) -> str:
        """Format bytes to human-readable format"""
        for unit in ["B", "KB", "MB", "GB"]:
            if num_bytes < 1024:
                return f"{num_bytes:.2f}{unit}"
            num_bytes /= 1024
        return f"{num_bytes:.2f}TB"


class BenchmarkResult:
    """Container for benchmark results"""

    def __init__(self, name: str, duration: float, iterations: int = 1):
        """Initialize benchmark result"""
        self.name = name
        self.duration = duration
        self.iterations = iterations

    @property
    def ops_per_second(self) -> float:
        """Calculate operations per second"""
        if self.duration == 0:
            return float("inf")
        return self.iterations / self.duration

    def __str__(self) -> str:
        return (
            f"{self.name}: {self.iterations} iterations in {self.duration:.4f}s "
            f"({self.ops_per_second:.2f} ops/sec)"
        )


def benchmark(func: Callable, iterations: int = 100, *args, **kwargs) -> BenchmarkResult:
    """
    Simple benchmarking utility

    Usage:
        result = benchmark(classifier.classify_evidence, iterations=1000, text=sample_text)
        print(result)
    """
    start = time.perf_counter()

    for _ in range(iterations):
        func(*args, **kwargs)

    duration = time.perf_counter() - start
    return BenchmarkResult(func.__name__, duration, iterations)


class MemoryTracker:
    """Track memory usage during execution"""

    def __init__(self):
        """Initialize tracker"""
        self.snapshots: Dict[str, int] = {}

    def snapshot(self, name: str) -> None:
        """Take memory snapshot"""
        import tracemalloc

        if not tracemalloc.is_tracing():
            tracemalloc.start()

        current, peak = tracemalloc.get_traced_memory()
        self.snapshots[name] = {"current": current, "peak": peak}
        logger.debug(f"Memory snapshot '{name}': {MemoryProfiler.format_bytes(current)}")

    def get_diff(self, name1: str, name2: str) -> Dict[str, int]:
        """Get memory difference between two snapshots"""
        if name1 not in self.snapshots or name2 not in self.snapshots:
            return {}

        return {
            "current_diff": self.snapshots[name2]["current"] - self.snapshots[name1]["current"],
            "peak_diff": self.snapshots[name2]["peak"] - self.snapshots[name1]["peak"],
        }

    def report(self) -> None:
        """Print memory usage report"""
        print("\n" + "=" * 60)
        print("MEMORY USAGE REPORT")
        print("=" * 60)

        for name, data in sorted(self.snapshots.items()):
            print(f"\n{name}:")
            print(f"  Current: {MemoryProfiler.format_bytes(data['current'])}")
            print(f"  Peak:    {MemoryProfiler.format_bytes(data['peak'])}")
