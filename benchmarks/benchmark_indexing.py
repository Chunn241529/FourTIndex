"""Generate a deterministic large fixture for manual first-index benchmarks."""

import argparse
import tempfile
import time
from pathlib import Path


def create_fixture(root: Path, file_count: int, lines_per_file: int) -> None:
    body = "\n".join(f"    value_{line} = {line}" for line in range(lines_per_file))
    for index in range(file_count):
        (root / f"module_{index:05d}.py").write_text(
            f"def function_{index}():\n{body}\n    return value_0\n", encoding="utf-8"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=2000)
    parser.add_argument("--lines", type=int, default=100)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        started = time.perf_counter()
        create_fixture(root, args.files, args.lines)
        elapsed = time.perf_counter() - started
        print(f"Created {args.files} files in {elapsed:.2f}s at {root}")
        print("Run: fourtindex index <path> --rebuild --embedding-provider <provider>")


if __name__ == "__main__":
    main()
