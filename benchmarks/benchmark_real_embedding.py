"""Run a real local embedding benchmark against the configured provider.

This benchmark intentionally uses the production Config and Embedder classes.
It does not monkeypatch providers, so the output reflects the local LM Studio
or Ollama service that is active on the machine running the script.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import Config  # noqa: E402
from src.embedder import Embedder  # noqa: E402


DEFAULT_JSON_PATH = PROJECT_ROOT / "benchmarks" / "real_embedding_results.json"
DEFAULT_MARKDOWN_PATH = PROJECT_ROOT / "benchmarks" / "real_embedding_results.md"


def percentile(values: list[float], pct: float) -> float:
    if not values:
        raise ValueError("Cannot calculate a percentile for an empty list")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def latency_summary(seconds: list[float]) -> dict[str, float]:
    if not seconds:
        raise ValueError("Cannot summarize an empty latency collection")
    avg_seconds = statistics.mean(seconds)
    return {
        "iterations": len(seconds),
        "avg_ms": avg_seconds * 1000,
        "min_ms": min(seconds) * 1000,
        "p50_ms": percentile(seconds, 0.50) * 1000,
        "p95_ms": percentile(seconds, 0.95) * 1000,
        "max_ms": max(seconds) * 1000,
        "ops_sec": 1.0 / avg_seconds if avg_seconds else 0.0,
    }


def make_payloads(count: int) -> list[str]:
    return [
        (
            f"Benchmark embedding payload {index}: summarize symbol lookup, "
            "outline retrieval, semantic code search, and incremental indexing."
        )
        for index in range(count)
    ]


def benchmark_single(embedder: Embedder, payloads: Iterable[str]) -> tuple[list[float], int]:
    latencies = []
    dimension = 0
    for payload in payloads:
        started = time.perf_counter()
        vector = embedder.get_embedding(payload)
        latencies.append(time.perf_counter() - started)
        if not vector:
            raise RuntimeError("Embedding provider returned an empty vector")
        dimension = len(vector)
    return latencies, dimension


def benchmark_batch(
    embedder: Embedder, payloads: list[str], batch_size: int
) -> tuple[list[float], int]:
    latencies = []
    dimensions = 0
    for offset in range(0, len(payloads), batch_size):
        batch = payloads[offset : offset + batch_size]
        started = time.perf_counter()
        vectors = embedder.get_embeddings_batch(batch)
        latencies.append(time.perf_counter() - started)
        if len(vectors) != len(batch):
            raise RuntimeError(
                f"Batch returned {len(vectors)} vectors for {len(batch)} inputs"
            )
        if any(not vector for vector in vectors):
            raise RuntimeError("Embedding provider returned an empty vector in a batch")
        dimensions = len(vectors[0])
    return latencies, dimensions


def write_markdown(results: dict, output_path: Path) -> None:
    single = results["single_query"]
    batch = results.get("batch_query")
    lines = [
        "# Real Embedding Benchmark Results",
        "",
        f"- Captured at: `{results['captured_at']}`",
        f"- Provider: `{results['provider']}`",
        f"- Model: `{results['model']}`",
        f"- Embedding dimension: `{results['dimension']}`",
        f"- Python: `{results['environment']['python']}`",
        f"- Platform: `{results['environment']['platform']}`",
        "",
        "## Single Query Latency",
        "",
        "| Iterations | Avg | p50 | p95 | Min | Max | Throughput |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        (
            f"| {single['iterations']} | {single['avg_ms']:.2f} ms | "
            f"{single['p50_ms']:.2f} ms | {single['p95_ms']:.2f} ms | "
            f"{single['min_ms']:.2f} ms | {single['max_ms']:.2f} ms | "
            f"{single['ops_sec']:.1f} ops/sec |"
        ),
    ]

    if batch:
        lines.extend(
            [
                "",
                "## Batch Embedding Throughput",
                "",
                "| Batches | Batch Size | Avg Batch | p95 Batch | Items/sec |",
                "| :--- | :--- | :--- | :--- | :--- |",
                (
                    f"| {batch['iterations']} | {batch['batch_size']} | "
                    f"{batch['avg_ms']:.2f} ms | {batch['p95_ms']:.2f} ms | "
                    f"{batch['items_sec']:.1f} items/sec |"
                ),
            ]
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark real embedding calls against the configured provider."
    )
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--batch-items", type=int, default=64)
    parser.add_argument("--skip-batch", action="store_true")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MARKDOWN_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be at least 1")
    if args.warmup < 0:
        raise SystemExit("--warmup cannot be negative")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")
    if args.batch_items < 1:
        raise SystemExit("--batch-items must be at least 1")

    config = Config()
    embedder = Embedder(config)

    print(f"Provider: {embedder.provider}")
    print(f"Model:    {embedder.model}")
    print(f"Warmup:   {args.warmup} single-query calls")

    warmup_payloads = make_payloads(args.warmup)
    if warmup_payloads:
        benchmark_single(embedder, warmup_payloads)

    print(f"Running {args.iterations} measured single-query calls...")
    single_latencies, dimension = benchmark_single(
        embedder, make_payloads(args.iterations)
    )
    single = latency_summary(single_latencies)

    results = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "provider": embedder.provider,
        "model": embedder.model,
        "dimension": dimension,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "single_query": single,
    }

    print(
        "Single-query avg: "
        f"{single['avg_ms']:.2f} ms, p95: {single['p95_ms']:.2f} ms, "
        f"throughput: {single['ops_sec']:.1f} ops/sec"
    )

    if not args.skip_batch:
        batch_payloads = make_payloads(args.batch_items)
        print(
            f"Running batch benchmark with {args.batch_items} items "
            f"at batch size {args.batch_size}..."
        )
        batch_latencies, batch_dimension = benchmark_batch(
            embedder, batch_payloads, args.batch_size
        )
        if batch_dimension != dimension:
            raise RuntimeError(
                f"Batch dimension {batch_dimension} differs from single dimension {dimension}"
            )
        batch = latency_summary(batch_latencies)
        batch["batch_size"] = args.batch_size
        batch["items"] = args.batch_items
        batch["items_sec"] = args.batch_items / sum(batch_latencies)
        results["batch_query"] = batch
        print(
            "Batch avg: "
            f"{batch['avg_ms']:.2f} ms/batch, p95: {batch['p95_ms']:.2f} ms, "
            f"throughput: {batch['items_sec']:.1f} items/sec"
        )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    write_markdown(results, args.output_md)

    print(f"Wrote JSON results to {args.output_json}")
    print(f"Wrote Markdown results to {args.output_md}")


if __name__ == "__main__":
    main()
