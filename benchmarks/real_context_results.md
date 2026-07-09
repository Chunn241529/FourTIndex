# Real Repository Context Benchmark

- Captured at: `2026-07-09T10:17:48.525201+00:00`
- Query: `embedding index search mcp server`
- Tokenizer: `chars/4 approximation`
- Files scanned: `61`
- Lines scanned: `10703`
- Scan time: `2052.57 ms`

| Scenario | Tokens | Est. input cost |
| :--- | :--- | :--- |
| Full repository context | 107,834 | $0.3235 |
| Targeted context sample | 7,623 | $0.0229 |

| Reduction | Value |
| :--- | :--- |
| Context shrink | 14.1x smaller |
| Cost reduction | 92.9% |

## Top Matched Files

| Rank | File | Score |
| :--- | :--- | :--- |
| 1 | `src/mcp_server.py` | 227 |
| 2 | `tests/test_mcp_server.py` | 220 |
| 3 | `README.md` | 182 |
| 4 | `main.py` | 119 |
| 5 | `src/indexing_service.py` | 89 |
| 6 | `.agents/skills/FourTIndex/SKILL.md` | 73 |
| 7 | `src/templates/SKILL.md` | 64 |
| 8 | `benchmarks/benchmark_mcp.py` | 60 |
