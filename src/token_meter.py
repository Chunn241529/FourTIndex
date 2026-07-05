import os
import re
import json
import glob
import sqlite3
from datetime import datetime

# Đường dẫn DB và cấu hình
DB_DIR = os.path.expanduser("~/.agent_token_meter")
DB_PATH = os.path.join(DB_DIR, "meter.db")

PRICING_2026 = [
    ("gpt-4o", "OpenAI", 2.50, 10.00),
    ("gpt-5.5", "OpenAI", 5.00, 30.00),
    ("gpt-5.4", "OpenAI", 2.50, 15.00),
    ("claude-3-5-sonnet", "Anthropic", 3.00, 15.00),
    ("claude-sonnet-4.6", "Anthropic", 3.00, 15.00),
    ("claude-sonnet-5", "Anthropic", 3.00, 15.00),
    ("gemini-3.5-flash", "Google", 1.50, 9.00),
    ("gemini-3.1-pro", "Google", 2.00, 12.00),
]

_encoding = None

def get_encoding():
    global _encoding
    if _encoding is None:
        try:
            import tiktoken
            _encoding = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            _encoding = False
    return _encoding

def count_tokens(text: str, model_name: str) -> int:
    """Đếm token bằng tiktoken cho OpenAI/Cursor, hoặc heuristics cho Claude/Gemini."""
    if not text:
        return 0
    model_lower = model_name.lower()
    is_openai_or_cursor = "gpt" in model_lower or "cursor" in model_lower or "o1" in model_lower or "o3" in model_lower
    
    if is_openai_or_cursor:
        encoding = get_encoding()
        if encoding:
            try:
                return len(encoding.encode(text))
            except Exception:
                pass
    return max(1, len(text) // 4)

def get_db_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Khởi tạo cấu trúc CSDL."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS token_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                agent_name TEXT,
                model TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                estimated_cost REAL,
                conversation_id TEXT UNIQUE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_pricing (
                model TEXT PRIMARY KEY,
                provider TEXT,
                input_rate_per_1m REAL,
                output_rate_per_1m REAL
            )
        """)
        for model, provider, input_rate, output_rate in PRICING_2026:
            conn.execute("""
                INSERT INTO model_pricing (model, provider, input_rate_per_1m, output_rate_per_1m)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(model) DO UPDATE SET
                    input_rate_per_1m=excluded.input_rate_per_1m,
                    output_rate_per_1m=excluded.output_rate_per_1m
            """, (model, provider, input_rate, output_rate))
        conn.commit()

def get_pricing(model_name):
    model_lower = model_name.lower()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT input_rate_per_1m, output_rate_per_1m FROM model_pricing WHERE LOWER(model) = ?", 
            (model_lower,)
        ).fetchone()
        if row:
            return row["input_rate_per_1m"], row["output_rate_per_1m"]
        row = conn.execute(
            "SELECT input_rate_per_1m, output_rate_per_1m FROM model_pricing WHERE ? LIKE '%' || LOWER(model) || '%'",
            (model_lower,)
        ).fetchone()
        if row:
            return row["input_rate_per_1m"], row["output_rate_per_1m"]
        return 2.50, 10.00

def log_tokens(agent_name, model, prompt_tokens, completion_tokens, conversation_id):
    input_rate, output_rate = get_pricing(model)
    estimated_cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000.0
    total_tokens = prompt_tokens + completion_tokens
    
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO token_logs (agent_name, model, prompt_tokens, completion_tokens, total_tokens, estimated_cost, conversation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                agent_name=excluded.agent_name,
                model=excluded.model,
                prompt_tokens=excluded.prompt_tokens,
                completion_tokens=excluded.completion_tokens,
                total_tokens=excluded.total_tokens,
                estimated_cost=excluded.estimated_cost,
                timestamp=CURRENT_TIMESTAMP
        """, (agent_name, model, prompt_tokens, completion_tokens, total_tokens, estimated_cost, conversation_id))
        conn.commit()
    return estimated_cost

def get_latest_conversation_log():
    """Tìm kiếm file log transcript mới nhất đang hoạt động."""
    brain_dir = os.path.expanduser("~/.gemini/antigravity/brain")
    if not os.path.exists(brain_dir):
        return None, None
    subdirs = [os.path.join(brain_dir, d) for d in os.listdir(brain_dir) if os.path.isdir(os.path.join(brain_dir, d))]
    if not subdirs:
        return None, None
        
    latest_log_file = None
    latest_mtime = 0
    latest_conv_id = None
    
    for sd in subdirs:
        log_path = os.path.join(sd, ".system_generated", "logs", "transcript_full.jsonl")
        if os.path.exists(log_path):
            mtime = os.path.getmtime(log_path)
            if mtime > latest_mtime:
                latest_mtime = mtime
                latest_log_file = log_path
                latest_conv_id = os.path.basename(sd)
                
    return latest_conv_id, latest_log_file

def parse_antigravity_transcript(file_path: str):
    if not os.path.exists(file_path):
        return "gemini-3.5-flash", 0, 0, 0, 0, 0, 0
        
    model_name = "gemini-3.5-flash"
    lines_data = []
    
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                lines_data.append(json.loads(line))
            except Exception:
                continue

    # Tìm vị trí của USER_INPUT cuối cùng để tính lượt chat vừa xong (Latest Turn)
    last_user_input_idx = -1
    for i in range(len(lines_data) - 1, -1, -1):
        if lines_data[i].get("type") == "USER_INPUT":
            last_user_input_idx = i
            break

    def calculate_tokens_for_slice(data_slice):
        nonlocal model_name
        p_tokens = 0
        c_tokens = 0
        t_calls = 0
        for data in data_slice:
            source = data.get("source")
            content = data.get("content", "")
            
            if content and "Model Selection" in content:
                match = re.search(r"Model\s+Selection\s+from\s+\S+\s+to\s+([^\.\n\(\)]+)", content)
                if match:
                    model_name = match.group(1).strip().lower().replace(" ", "-")
            
            if source == "MODEL":
                model_output_text = ""
                if content:
                    model_output_text += content
                thinking = data.get("thinking")
                if thinking:
                    model_output_text += "\n" + thinking
                tool_calls = data.get("tool_calls", [])
                if tool_calls:
                    t_calls += len(tool_calls)
                    model_output_text += "\n" + json.dumps(tool_calls)
                c_tokens += count_tokens(model_output_text, model_name)
            else:
                input_text = ""
                if content:
                    input_text += content
                p_tokens += count_tokens(input_text, model_name)
        return p_tokens, c_tokens, t_calls

    # Tính toán cho toàn bộ session
    total_prompt, total_completion, total_tool_calls = calculate_tokens_for_slice(lines_data)
    
    # Tính toán cho lượt chat cuối cùng
    if last_user_input_idx != -1:
        turn_prompt, turn_completion, turn_tool_calls = calculate_tokens_for_slice(lines_data[last_user_input_idx:])
    else:
        turn_prompt, turn_completion, turn_tool_calls = total_prompt, total_completion, total_tool_calls

    if "gemini-3.5-flash" in model_name:
        model_name = "gemini-3.5-flash"
    elif "gemini-3.1-pro" in model_name:
        model_name = "gemini-3.1-pro"
        
    return model_name, total_prompt, total_completion, total_tool_calls, turn_prompt, turn_completion, turn_tool_calls

def generate_report(agent_name, model, total_prompt, total_completion, total_tool_calls, turn_prompt, turn_completion, turn_tool_calls, conv_id, total_cost):
    input_rate, output_rate = get_pricing(model)
    turn_cost = (turn_prompt * input_rate + turn_completion * output_rate) / 1_000_000.0
    
    report = (
        "\n"
        "============================================================\n"
        "                BÁO CÁO ĐÁNH GIÁ SỬ DỤNG TOKEN\n"
        "============================================================\n"
        f"Agent:               {agent_name.upper()}\n"
        f"Model:               {model}\n"
        f"ID Hội thoại:        {conv_id}\n"
        "------------------------------------------------------------\n"
        " 📊 LƯỢT VỪA XONG (LATEST TURN):\n"
        f"  - Prompt (Input):    {turn_prompt:,} tokens\n"
        f"  - Completion (Out):  {turn_completion:,} tokens\n"
        f"  - Tổng số Token:     {turn_prompt + turn_completion:,}\n"
        f"  - Số Tool đã gọi:    {turn_tool_calls}\n"
        f"  - Chi phí lượt này:  ${turn_cost:.6f} USD\n"
        "------------------------------------------------------------\n"
        " 📈 TỔNG CẢ PHIÊN (TOTAL SESSION):\n"
        f"  - Prompt (Input):    {total_prompt:,} tokens\n"
        f"  - Completion (Out):  {total_completion:,} tokens\n"
        f"  - Tổng số Token:     {total_prompt + total_completion:,}\n"
        f"  - Số Tool đã gọi:    {total_tool_calls}\n"
        f"  - Tổng chi phí:      ${total_cost:.6f} USD\n"
        "============================================================\n"
    )
    return report

def evaluate_latest_session():
    """Chạy đánh giá và tổng kết token cho phiên hiện tại."""
    try:
        init_db()
        conv_id, log_file = get_latest_conversation_log()
        if not log_file:
            return "\n[AgentTokenMeter] Không tìm thấy lịch sử hội thoại hoạt động."
            
        model, total_prompt, total_completion, total_tool_calls, turn_prompt, turn_completion, turn_tool_calls = parse_antigravity_transcript(log_file)
        
        # Ghi nhận tổng cả phiên vào DB
        total_cost = log_tokens("antigravity", model, total_prompt, total_completion, conv_id)
        
        return generate_report("antigravity", model, total_prompt, total_completion, total_tool_calls, turn_prompt, turn_completion, turn_tool_calls, conv_id, total_cost)
    except Exception as e:
        return f"\n[AgentTokenMeter] Lỗi khi tổng kết token: {str(e)}"
