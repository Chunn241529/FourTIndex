<p align="center">
  <img src="assets/banner.png" alt="FourTIndex Banner" width="650px" style="border-radius: 8px;" />
</p>

<h1 align="center">FourTIndex 🚀</h1>

<p align="center">
  <strong>The Ultimate Local Codebase Indexer & MCP Server for AI Coding Agents.</strong>
</p>

<p align="center">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.9+-emerald.svg" alt="Python 3.9+"></a>
  <a href="https://ollama.com/"><img src="https://img.shields.io/badge/Ollama-Local%20LLM-pink.svg" alt="Ollama"></a>
  <a href="https://lmstudio.ai/"><img src="https://img.shields.io/badge/LM%20Studio-Local%20LLM-blue.svg" alt="LM Studio"></a>
  <a href="https://modelcontextprotocol.io/"><img src="https://img.shields.io/badge/MCP-Protocol-blueviolet.svg" alt="MCP"></a>
</p>

---

## 💡 The Problem with Modern AI Agents

Modern AI Coding frameworks (**Claude Code, Cursor, Codex (OpenAI), OpenDevin, Aider, Cline, Antigravity**, etc.) are incredibly smart, but they all share a critical weakness when it comes to navigating large codebases:
1. **Semantic Blindness:** They rely on standard `ripgrep` or basic AST parsers. If you ask them to "find the logic that splits the batch", and the function is actually named `chunk_array_size`, standard search fails.
2. **Context Window Burn:** When these tools find a file, they often dump the *entire file* into the prompt. This causes extreme API costs, slow response times, and LLM hallucinations due to context overload.

## 🚀 The FourTIndex Solution

**FourTIndex** acts as a localized, highly-efficient "brain" for your AI agents via the Model Context Protocol (MCP). It parses your code using Omni-Language Tree-sitter, chunks it, and indexes it into a local ChromaDB Vector Store.

Instead of your AI reading thousands of lines of irrelevant code, FourTIndex performs **True Hybrid Search (FTS5 + Vector + RRF)** and feeds your agent only the exact 60-line code snippets it needs.

---

## 📊 Hard Metrics: Real-World Benchmarks

*We ran brutal benchmarks on a real repository. Here are the hard numbers comparing standard Agent workflows vs FourTIndex.*

### 1. Context Shrink & Cost Savings
*Scenario: AI agent needs context on a specific feature across the project.*
| Metric | Standard Agent (Grep + Read File) | Agent + FourTIndex (Targeted Chunks) | Impact |
| :--- | :--- | :--- | :--- |
| **Token Load** | 112,162 tokens | **7,615 tokens** | **14.7x Smaller** |
| **Estimated API Cost** | ~$0.33 USD | **~$0.02 USD** | **93.2% Cheaper** |

### 2. Search Precision (Semantic vs Regex)
*Scenario: Find a function by its concept (e.g. "splits array into batches"), without knowing the exact variable name.*
| Metric | Standard Regex/Grep | FourTIndex Hybrid Search |
| :--- | :--- | :--- |
| **Context Pulled** | 93,093 tokens (44 noisy files) | **1,008 tokens** (Top 5 exact chunks) |
| **Result Quality** | ❌ Failed (Too much noise) | ✅ **Perfect Match (Targeted snippets)** |

---

## ✨ Key Features

- **Empowers ALL Frameworks:** Plug FourTIndex into **Cursor, Claude Desktop, Codex (OpenAI), OpenDevin, Cline, or Antigravity** via MCP.
- **100% Local Privacy:** Embeddings and Vector DB (ChromaDB) run entirely on your machine via **LM Studio** or **Ollama**. No source code is sent to third-party APIs for indexing.
- **True Hybrid Search:** Combines BM25 Keyword Search with Semantic Vector Search using Reciprocal Rank Fusion (RRF).
- **Omni-Language Tree-sitter:** Understands Python, TS/JS, React, Rust, Go, Java, Swift, C#, C++, Lua, and more. Automatically builds structural roadmaps of your project.
- **Zero-Config Agent Skills:** Auto-injects `SKILL.md` to instantly teach your agent how to use the MCP tools.
- **Zero-Prompt Auto-Resume (Memory Handoff):** Generates `.fourtindex_handoff.md` and rules for your agents to automatically inherit memory on new sessions. No more typing long prompts to continue your work!
- **Local File Summarization:** Offloads heavy codebase parsing to your local LLM (e.g. `monas` via LM Studio) via `summarize_file`, shrinking 2000-line files into a 100-token summary for your host Agent.

---

## ⚡ Quick Start

### 1. Install & Initialize
```bash
git clone https://github.com/Chunn241529/FourTIndex.git
cd FourTIndex
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e .
```

### 2. Configure Local Provider
Ensure Ollama or LM Studio is running.
```bash
# For Ollama
fourtindex setup-ollama

# For LM Studio
fourtindex setup-lmstudio
```

### 3. Index Your Codebase
```bash
fourtindex index .
```

---

## 🧩 MCP Client Integration

Add FourTIndex to your favorite agentic framework to supercharge its context retrieval.

### Cursor / Codex (OpenAI) / OpenDevin / Cline
Add a new `stdio` MCP server in your tool's configuration:
- **Command:** `/absolute/path/to/FourTIndex/.venv/Scripts/python.exe` (or `python` on Mac/Linux)
- **Args:** `/absolute/path/to/FourTIndex/main.py mcp`

### Claude Desktop
Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "fourtindex": {
      "command": "/absolute/path/to/FourTIndex/.venv/Scripts/python.exe",
      "args": ["/absolute/path/to/FourTIndex/main.py", "mcp"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/FourTIndex"
      }
    }
  }
}
```

### Project-safe agent bootstrap

Agents should resolve the project from their own workspace before searching:

1. Call `resolve_project(workspace_path=<agent cwd>, output_json=true)`.
2. Reuse the returned `project_name`, `project_root`, and `project_id` for the task.
3. Pass `project_name` explicitly to project-scoped tools.
4. Use `get_agent_context(workspace_path)` when delegating to another agent.

Resolution fails closed with `project_not_found`, `ambiguous_project`, or
`project_path_mismatch`; FourTIndex does not silently select a fallback project.
`list_projects()` includes canonical roots, stable IDs, and index status. JSON tool
results are compact by default, while `index_project(..., verbose=true)` includes
diagnostic details. Model cleanup remains explicit through `clean_mem()`.

---

<h2 align="center">💖 Support the Project</h2>

<p align="center">
  If <b>FourTIndex</b> has saved you API costs and helped you work faster, please consider supporting the project's development!
</p>

<p align="center">
  <a href="https://github.com/sponsors/Chunn241529" target="_blank"><img src="https://img.shields.io/badge/GitHub%20Sponsors-ea4aaa?style=for-the-badge&logo=githubsponsors&logoColor=white" alt="GitHub Sponsors" /></a>
  &nbsp;&nbsp;
  <a href="https://paypal.me/TrungVuong24/5USD" target="_blank"><img src="https://img.shields.io/badge/Donate%20via%20PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white" alt="PayPal" /></a>
</p>

<p align="center">
  <i>Click the buttons above to sponsor or donate via PayPal</i>
</p>

<br/>

<hr/>

<p align="center">
  <b>🇻🇳 Vietnamese Backers 🇻🇳</b><br/>
  Anh/chị có thể mời em một ly cà phê qua chuyển khoản ngân hàng nhanh (VietQR) dưới đây:
</p>

<div align="center">
  <table style="border: 1px solid #30363d; border-radius: 8px; border-collapse: separate; overflow: hidden; background-color: #0d1117;">
    <tr>
      <td align="center" style="padding: 20px; border: none; background-color: #161b22;">
        <b>Quét mã VietQR chuyển khoản</b><br/><br/>
        <img src="https://img.vietqr.io/image/MB-0358570211-compact2.png?addInfo=Donate%20FourTIndex&accountName=Vuong%20Nguyen%20Trung" width="220px" style="border-radius: 6px; border: 1px solid #30363d;" alt="VietQR Donation" />
      </td>
      <td align="left" style="padding: 25px; border: none; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; line-height: 1.6;">
        <h4 style="margin-top: 0; color: #58a6ff;">🏦 THÔNG TIN CHUYỂN KHOẢN</h4>
        <p style="margin: 6px 0;">Ngân hàng: <b>MB Bank (Ngân hàng Quân đội)</b></p>
        <p style="margin: 6px 0;">Số tài khoản: <code style="background-color: #30363d; padding: 2px 6px; border-radius: 4px; color: #ff7b72;">0358570211</code></p>
        <p style="margin: 6px 0;">Tên tài khoản: <b>VUONG NGUYEN TRUNG</b></p>
        <p style="margin: 6px 0;">Nội dung chuyển khoản: <code style="background-color: #30363d; padding: 2px 6px; border-radius: 4px; color: #ff7b72;">Donate FourTIndex</code></p>
        <hr style="border: 0; border-top: 1px solid #30363d; margin: 15px 0;"/>
        <p style="margin: 6px 0; font-size: 13px; color: #8b949e;">👉 <i>Hệ thống tự động nhận diện và ghi nhận đóng góp từ cộng đồng. Cảm ơn sự đồng hành của bạn!</i></p>
      </td>
    </tr>
  </table>
</div>
