# Real Repository Context Benchmark

- Captured at: `2026-07-09T17:20:25.202719+00:00`
- Query: `embedding index search mcp server`
- Tokenizer: `chars/4 approximation`
- Files scanned: `62`
- Lines scanned: `11079`
- Scan time: `2262.00 ms`

| Scenario | Tokens | Est. input cost |
| :--- | :--- | :--- |
| Full repository context | 112,162 | $0.3365 |
| Targeted context sample | 7,615 | $0.0228 |

| Reduction | Value |
| :--- | :--- |
| Context shrink | 14.7x smaller |
| Cost reduction | 93.2% |

## Top Matched Files

| Rank | File | Score |
| :--- | :--- | :--- |
| 1 | `src/mcp_server.py` | 246 |
| 2 | `tests/test_mcp_server.py` | 220 |
| 3 | `README.md` | 195 |
| 4 | `main.py` | 119 |
| 5 | `src/indexing_service.py` | 89 |
| 6 | `.agents/skills/FourTIndex/SKILL.md` | 79 |
| 7 | `src/templates/SKILL.md` | 64 |
| 8 | `benchmarks/benchmark_mcp.py` | 60 |
