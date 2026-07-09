"""Benchmark context savings on the real FourTIndex repository.

The older context benchmark builds a mock project. This script measures the
current checkout directly and builds a deterministic targeted context sample
from real files that match a coding task query.
"""

from __future__ import annotations

import argparse
import ast
import json
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON_PATH = PROJECT_ROOT / "benchmarks" / "real_context_results.json"
DEFAULT_MARKDOWN_PATH = PROJECT_ROOT / "benchmarks" / "real_context_results.md"
DEFAULT_QUERY = "embedding index search mcp server"
DEFAULT_EXTENSIONS = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".txt",
    ".json",
}
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".fourtindex",
    "build",
    "dist",
    "fourtindex.egg-info",
}


def get_token_count(text: str, tokenizer: str) -> tuple[int, str]:
    if tokenizer == "approx":
        return max(1, len(text) // 4), "chars/4 approximation"

    try:
        import tiktoken

        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text)), "tiktoken:cl100k_base"
    except Exception:
        return max(1, len(text) // 4), "chars/4 approximation"


def estimate_cost(tokens: int, cost_per_1m_tokens: float) -> float:
    return (tokens / 1_000_000) * cost_per_1m_tokens


def should_skip(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def iter_candidate_files(root: Path, extensions: set[str]) -> list[Path]:
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or should_skip(path.relative_to(root)):
            continue
        if path.suffix.lower() in extensions:
            files.append(path)
    return sorted(files)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def render_full_context(root: Path, files: list[Path]) -> tuple[str, dict[str, str]]:
    contents = {}
    parts = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        text = read_text(path)
        contents[relative] = text
        parts.append(f"--- {relative} ---\n{text}")
    return "\n\n".join(parts), contents


def rank_files(contents: dict[str, str], query: str) -> list[tuple[str, int]]:
    terms = [term.lower() for term in query.split() if term.strip()]
    ranked = []
    for relative, text in contents.items():
        haystack = f"{relative}\n{text}".lower()
        score = sum(haystack.count(term) for term in terms)
        if score:
            ranked.append((relative, score))
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


def python_outline(relative: str, text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    lines = [f"Outline: {relative}"]
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            lines.append(f"- class {node.name} (line {node.lineno})")
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lines.append(f"  - def {child.name} (line {child.lineno})")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.append(f"- def {node.name} (line {node.lineno})")
    return lines if len(lines) > 1 else []


def markdown_outline(relative: str, text: str) -> list[str]:
    headings = [
        f"- {line.strip()} (line {line_no})"
        for line_no, line in enumerate(text.splitlines(), start=1)
        if line.lstrip().startswith("#")
    ][:20]
    return [f"Outline: {relative}", *headings] if headings else []


def matched_windows(
    relative: str, text: str, query: str, max_lines: int
) -> list[str]:
    terms = [term.lower() for term in query.split() if term.strip()]
    source_lines = text.splitlines()
    matched = [
        index
        for index, line in enumerate(source_lines)
        if any(term in line.lower() for term in terms)
    ]
    if not matched:
        return []

    selected = []
    seen = set()
    for match in matched:
        start = max(0, match - 2)
        end = min(len(source_lines), match + 3)
        for line_index in range(start, end):
            if line_index not in seen:
                seen.add(line_index)
                selected.append(line_index)
            if len(selected) >= max_lines:
                break
        if len(selected) >= max_lines:
            break

    rendered = [f"Matched lines: {relative}"]
    rendered.extend(
        f"{line_index + 1}: {source_lines[line_index]}" for line_index in selected
    )
    return rendered


def render_targeted_context(
    contents: dict[str, str], ranked: list[tuple[str, int]], query: str, top_files: int
) -> str:
    parts = [f"Task query: {query}", ""]
    for relative, score in ranked[:top_files]:
        text = contents[relative]
        outline = (
            python_outline(relative, text)
            if relative.endswith(".py")
            else markdown_outline(relative, text)
        )
        if outline:
            parts.append("\n".join(outline))
        parts.append(f"Search score: {score}")
        parts.append("\n".join(matched_windows(relative, text, query, max_lines=60)))
        parts.append("")
    return "\n".join(part for part in parts if part)


def write_markdown(results: dict, output_path: Path) -> None:
    lines = [
        "# Real Repository Context Benchmark",
        "",
        f"- Captured at: `{results['captured_at']}`",
        f"- Query: `{results['query']}`",
        f"- Tokenizer: `{results['tokenizer']}`",
        f"- Files scanned: `{results['files_scanned']}`",
        f"- Lines scanned: `{results['lines_scanned']}`",
        f"- Scan time: `{results['scan_ms']:.2f} ms`",
        "",
        "| Scenario | Tokens | Est. input cost |",
        "| :--- | :--- | :--- |",
        (
            f"| Full repository context | {results['full_context_tokens']:,} | "
            f"${results['full_context_cost_usd']:.4f} |"
        ),
        (
            f"| Targeted context sample | {results['targeted_context_tokens']:,} | "
            f"${results['targeted_context_cost_usd']:.4f} |"
        ),
        "",
        "| Reduction | Value |",
        "| :--- | :--- |",
        f"| Context shrink | {results['context_reduction_x']:.1f}x smaller |",
        f"| Cost reduction | {results['cost_reduction_pct']:.1f}% |",
        "",
        "## Top Matched Files",
        "",
        "| Rank | File | Score |",
        "| :--- | :--- | :--- |",
    ]
    for index, item in enumerate(results["top_files"], start=1):
        lines.append(f"| {index} | `{item['file']}` | {item['score']} |")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure real context savings on this repository."
    )
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--top-files", type=int, default=8)
    parser.add_argument("--cost-per-1m", type=float, default=3.0)
    parser.add_argument("--tokenizer", choices=("approx", "tiktoken"), default="approx")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MARKDOWN_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_files < 1:
        raise SystemExit("--top-files must be at least 1")

    started = time.perf_counter()
    files = iter_candidate_files(PROJECT_ROOT, DEFAULT_EXTENSIONS)
    full_context, contents = render_full_context(PROJECT_ROOT, files)
    ranked = rank_files(contents, args.query)
    if not ranked:
        raise RuntimeError(f"No files matched query: {args.query}")
    targeted_context = render_targeted_context(
        contents, ranked, args.query, args.top_files
    )
    scan_ms = (time.perf_counter() - started) * 1000

    full_tokens, tokenizer = get_token_count(full_context, args.tokenizer)
    targeted_tokens, _ = get_token_count(targeted_context, args.tokenizer)
    full_cost = estimate_cost(full_tokens, args.cost_per_1m)
    targeted_cost = estimate_cost(targeted_tokens, args.cost_per_1m)
    line_count = sum(text.count("\n") + 1 for text in contents.values())

    results = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "query": args.query,
        "tokenizer": tokenizer,
        "files_scanned": len(files),
        "lines_scanned": line_count,
        "scan_ms": scan_ms,
        "full_context_tokens": full_tokens,
        "targeted_context_tokens": targeted_tokens,
        "full_context_cost_usd": full_cost,
        "targeted_context_cost_usd": targeted_cost,
        "context_reduction_x": full_tokens / max(1, targeted_tokens),
        "cost_reduction_pct": ((full_cost - targeted_cost) / max(full_cost, 0.0001))
        * 100,
        "top_files": [
            {"file": relative, "score": score}
            for relative, score in ranked[: args.top_files]
        ],
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    write_markdown(results, args.output_md)

    print("=== Real Repository Context Benchmark ===")
    print(f"Files scanned:       {results['files_scanned']}")
    print(f"Lines scanned:       {results['lines_scanned']:,}")
    print(f"Full context:        {results['full_context_tokens']:,} tokens")
    print(f"Targeted context:    {results['targeted_context_tokens']:,} tokens")
    print(f"Reduction:           {results['context_reduction_x']:.1f}x smaller")
    print(f"Cost reduction:      {results['cost_reduction_pct']:.1f}%")
    print(f"Wrote JSON results:  {args.output_json}")
    print(f"Wrote Markdown:      {args.output_md}")


if __name__ == "__main__":
    main()
