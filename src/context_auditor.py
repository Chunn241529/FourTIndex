import json
import os
import re
from typing import Any, Dict, List, Set, Tuple
from src.token_meter import count_tokens, get_pricing, get_latest_conversation_log, discover_antigravity_sessions, discover_claude_sessions, discover_codex_sessions
from src.llm import LLMClient
from src.config import Config

def parse_tool_calls_and_files(record: dict) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extracts tool calls, files read, and other tool outputs from a transcript record."""
    tool_calls = []
    files_read = []
    tool_outputs = []
    
    # Check for tool call definitions
    calls = record.get("tool_calls") or []
    for call in calls:
        name = call.get("name") or ""
        tool_calls.append(name)
        
    rec_type = record.get("type") or ""
    content = record.get("content") or ""
    
    # Classify tool outputs
    if rec_type not in ("USER_INPUT", "PLANNER_RESPONSE", "CONVERSATION_HISTORY", "SYSTEM_MESSAGE"):
        # This is a tool execution output
        tool_name = record.get("toolAction") or record.get("toolSummary") or rec_type
        # Estimate size
        tokens = count_tokens(content, "gemini-3.5-flash")
        
        # Check if it's a file reading tool
        is_file = False
        file_path = ""
        
        if rec_type in ("VIEW_FILE", "VIEW_RESOURCE") or "view_file" in rec_type.lower() or "read_code" in rec_type.lower():
            is_file = True
            # Try to extract path from content
            match = re.search(r"File Path:\s*`?file:///([^`\n\r]+)`?", content)
            if match:
                file_path = os.path.basename(match.group(1))
            else:
                file_path = "Viewed File"
        elif "read_url" in rec_type.lower() or "read_browser" in rec_type.lower():
            is_file = True
            file_path = "Web URL Content"
            
        if is_file:
            files_read.append({
                "name": file_path,
                "tokens": tokens,
                "type": rec_type
            })
        else:
            tool_outputs.append({
                "name": tool_name,
                "tokens": tokens,
                "type": rec_type
            })
            
    return tool_calls, files_read, tool_outputs

def audit_antigravity_session(file_path: str, conversation_id: str) -> dict:
    """Audits an Antigravity transcript session turn-by-turn."""
    if not os.path.exists(file_path):
        return {}
        
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
                    
    # Group records into turns
    turns_records = []
    current_turn = []
    for r in records:
        if r.get("type") == "USER_INPUT":
            if current_turn:
                turns_records.append(current_turn)
            current_turn = [r]
        else:
            current_turn.append(r)
    if current_turn:
        turns_records.append(current_turn)
        
    turns = []
    model = "gemini-3.5-flash"
    
    # Running accumulators for history
    acc_user_tokens = 0
    acc_completion_tokens = 0
    acc_file_tokens = 0
    acc_tool_tokens = 0
    
    # Detect modifications
    modified_files: Set[str] = set()
    user_prompts: List[str] = []
    
    # Process turn by turn
    for idx, turn_recs in enumerate(turns_records, 1):
        user_input_rec = next((r for r in turn_recs if r.get("type") == "USER_INPUT"), None)
        if not user_input_rec:
            continue
            
        user_query = user_input_rec.get("content", "")
        # Remove tag wrappers for display
        clean_query = re.sub(r"<USER_REQUEST>([\s\S]*?)</USER_REQUEST>", r"\1", user_query).strip()
        user_prompts.append(clean_query)
        
        timestamp = user_input_rec.get("created_at", "")
        
        # Calculate turn details
        turn_user_tokens = count_tokens(user_query, model)
        
        turn_tool_calls = []
        turn_files_read = []
        turn_tool_outputs = []
        turn_completion_text = ""
        
        for r in turn_recs:
            rec_type = r.get("type") or ""
            if rec_type == "USER_INPUT":
                # Look for model selection changes
                content = r.get("content", "")
                if "Model Selection" in content:
                    match = re.search(r"Model\s+Selection\s+from\s+\S+\s+to\s+([^\.\n]+)", content)
                    if match:
                        model = match.group(1).strip().lower().replace(" ", "-")
                        
            elif rec_type == "PLANNER_RESPONSE":
                turn_completion_text += r.get("content") or ""
                if r.get("thinking"):
                    turn_completion_text += "\n" + r["thinking"]
                # Track modifications in tool calls
                calls = r.get("tool_calls") or []
                for call in calls:
                    c_name = call.get("name") or ""
                    turn_tool_calls.append(c_name)
                    # Extract target files from edits/writes
                    args = call.get("args") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    target = args.get("TargetFile") or args.get("TargetPath") or args.get("path")
                    if target:
                        modified_files.add(os.path.basename(target))
            elif rec_type not in ("CONVERSATION_HISTORY", "SYSTEM_MESSAGE"):
                # Extract file reading and tool outputs
                t_calls, f_read, t_out = parse_tool_calls_and_files(r)
                turn_files_read.extend(f_read)
                turn_tool_outputs.extend(t_out)
                
        turn_completion_tokens = count_tokens(turn_completion_text, model)
        
        # Breakdown sizes for current turn
        turn_files_tokens = sum(f["tokens"] for f in turn_files_read)
        turn_tool_tokens = sum(t["tokens"] for t in turn_tool_outputs)
        
        # System instructions estimate
        system_tokens = 2000 if idx == 1 else 0
        
        # Total prompt context at start of turn
        prompt_tokens = system_tokens + acc_user_tokens + acc_completion_tokens + acc_file_tokens + acc_tool_tokens + turn_user_tokens
        
        # Build breakdown for the UI
        breakdown = {
            "system": 2000,
            "chat_history": acc_user_tokens + acc_completion_tokens,
            "files": acc_file_tokens + turn_files_tokens,
            "tool_outputs": acc_tool_tokens + turn_tool_tokens,
            "user_input": turn_user_tokens
        }
        
        input_rate, output_rate = get_pricing(model)
        cost = (prompt_tokens * input_rate + turn_completion_tokens * output_rate) / 1_000_000.0
        
        turns.append({
            "turn_index": idx,
            "user_query": clean_query[:100] + ("..." if len(clean_query) > 100 else ""),
            "full_query": clean_query,
            "timestamp": timestamp,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": turn_completion_tokens,
            "cost": cost,
            "tool_calls": list(set(turn_tool_calls)),
            "breakdown": breakdown,
            "files_read": turn_files_read,
            "tool_details": turn_tool_outputs
        })
        
        # Accumulate for next turn
        acc_user_tokens += turn_user_tokens
        acc_completion_tokens += turn_completion_tokens
        acc_file_tokens += turn_files_tokens
        acc_tool_tokens += turn_tool_tokens
        
    return {
        "agent": "antigravity",
        "model": model,
        "conversation_id": conversation_id,
        "turns": turns,
        "modified_files": list(modified_files),
        "user_prompts": user_prompts
    }

def audit_claude_session(file_path: str, conversation_id: str) -> dict:
    """Audits a Claude session turn-by-turn using native usage stats."""
    if not os.path.exists(file_path):
        return {}
        
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
                    
    turns = []
    model = "unknown"
    modified_files: Set[str] = set()
    user_prompts: List[str] = []
    
    # Claude records assistant message usage
    idx = 1
    acc_chat_tokens = 0
    
    for r in records:
        if r.get("type") == "user":
            # Track user query
            text = (r.get("message") or {}).get("content", "")
            if isinstance(text, list):
                text = " ".join(block.get("text", "") for block in text if isinstance(block, dict))
            user_prompts.append(text)
            
        elif r.get("type") == "assistant":
            message = r.get("message") or {}
            usage = message.get("usage") or {}
            model = message.get("model") or model
            
            prompt_tokens = sum(
                int(usage.get(key) or 0)
                for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
            )
            completion_tokens = int(usage.get("output_tokens") or 0)
            
            # Extract tool calls & modifications
            tool_calls = []
            contents = message.get("content") or []
            for block in contents:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    t_name = block.get("name") or ""
                    tool_calls.append(t_name)
                    # Detect modifications
                    input_args = block.get("input") or {}
                    target = input_args.get("path") or input_args.get("TargetFile") or input_args.get("filePath")
                    if target:
                        modified_files.add(os.path.basename(target))
                        
            # Query display
            clean_query = user_prompts[-1] if user_prompts else "Assistant Turn"
            
            input_rate, output_rate = get_pricing(model)
            cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000.0
            
            # Build breakdown estimates
            user_tokens = count_tokens(clean_query, model)
            system_files = max(0, prompt_tokens - acc_chat_tokens - user_tokens)
            
            breakdown = {
                "system": 1500,
                "chat_history": acc_chat_tokens,
                "files": system_files,
                "tool_outputs": 0,
                "user_input": user_tokens
            }
            
            turns.append({
                "turn_index": idx,
                "user_query": clean_query[:100] + ("..." if len(clean_query) > 100 else ""),
                "full_query": clean_query,
                "timestamp": "",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost": cost,
                "tool_calls": tool_calls,
                "breakdown": breakdown,
                "files_read": [],
                "tool_details": []
            })
            
            acc_chat_tokens += user_tokens + completion_tokens
            idx += 1
            
    return {
        "agent": "claude",
        "model": model,
        "conversation_id": conversation_id,
        "turns": turns,
        "modified_files": list(modified_files),
        "user_prompts": user_prompts
    }

def audit_codex_session(file_path: str, conversation_id: str) -> dict:
    """Audits a Codex session turn-by-turn using log token counts."""
    if not os.path.exists(file_path):
        return {}
        
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
                    
    turns = []
    model = "unknown"
    modified_files: Set[str] = set()
    user_prompts: List[str] = []
    
    idx = 1
    acc_chat_tokens = 0
    
    for r in records:
        payload = r.get("payload") or {}
        rec_type = r.get("type") or ""
        
        if rec_type == "turn_context":
            model = payload.get("model") or model
            query = payload.get("user_query") or ""
            if query:
                user_prompts.append(query)
                
        elif rec_type == "event_msg" and payload.get("type") == "token_count" and payload.get("info"):
            info = payload["info"]
            turn_usage = info.get("last_token_usage") or {}
            
            prompt_tokens = int(turn_usage.get("input_tokens") or 0)
            completion_tokens = int(turn_usage.get("output_tokens") or 0)
            
            # Reconstruct query
            clean_query = user_prompts[-1] if user_prompts else "Codex Turn"
            
            input_rate, output_rate = get_pricing(model)
            cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000.0
            
            user_tokens = count_tokens(clean_query, model)
            system_files = max(0, prompt_tokens - acc_chat_tokens - user_tokens)
            
            breakdown = {
                "system": 2000,
                "chat_history": acc_chat_tokens,
                "files": system_files,
                "tool_outputs": 0,
                "user_input": user_tokens
            }
            
            turns.append({
                "turn_index": idx,
                "user_query": clean_query[:100] + ("..." if len(clean_query) > 100 else ""),
                "full_query": clean_query,
                "timestamp": "",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost": cost,
                "tool_calls": [],
                "breakdown": breakdown,
                "files_read": [],
                "tool_details": []
            })
            
            acc_chat_tokens += user_tokens + completion_tokens
            idx += 1
            
    return {
        "agent": "codex",
        "model": model,
        "conversation_id": conversation_id,
        "turns": turns,
        "modified_files": list(modified_files),
        "user_prompts": user_prompts
    }

def get_recommendations(turns: List[dict]) -> List[dict]:
    """Generates context pruning & token optimization advice based on turn metrics."""
    recommendations = []
    if not turns:
        return recommendations
        
    latest_turn = turns[-1]
    total_prompt = latest_turn.get("prompt_tokens", 0)
    
    # 1. Total context size warnings
    if total_prompt > 40000:
        recommendations.append({
            "type": "warning",
            "message": f"Your active prompt context is very large ({total_prompt:,} tokens). "
                       f"This makes each response slower and costs ${latest_turn['cost']:.4f} USD per turn. "
                       f"Recommendation: Start a new clean chat session to prune the chat history."
        })
    elif total_prompt > 20000:
        recommendations.append({
            "type": "info",
            "message": f"Context size is growing ({total_prompt:,} tokens). Consider resolving ongoing topics "
                       f"and starting a new chat session to keep reasoning sharp."
        })
        
    # 2. Check for stale large files read
    file_sizes: Dict[str, int] = {}
    file_first_seen: Dict[str, int] = {}
    file_last_seen: Dict[str, int] = {}
    
    for t in turns:
        t_idx = t["turn_index"]
        for f in t.get("files_read", []):
            fname = f["name"]
            ftokens = f["tokens"]
            file_sizes[fname] = max(file_sizes.get(fname, 0), ftokens)
            if fname not in file_first_seen:
                file_first_seen[fname] = t_idx
            file_last_seen[fname] = t_idx
            
    for fname, fsize in file_sizes.items():
        if fsize > 8000:
            first_idx = file_first_seen[fname]
            last_idx = file_last_seen[fname]
            turns_active = len(turns) - first_idx + 1
            
            # Add warning about large file size in context
            recommendations.append({
                "type": "warning",
                "message": f"Large file '{fname}' ({fsize:,} tokens) is in context. Reading large files repeatedly consumes significant tokens. Consider reading narrow range or using outlines."
            })
            
            # If a large file was read early and has been carried over for >3 turns
            if turns_active >= 3:
                recommendations.append({
                    "type": "warning",
                    "message": f"Large file '{fname}' ({fsize:,} tokens) has been carried in context for {turns_active} turns. "
                               f"This adds ${fsize * get_pricing(latest_turn.get('model', 'gemini-3.5-flash'))[0] / 1_000_000.0:.5f} USD "
                               f"to every single prompt. Suggestion: Start a new chat session, or ask the agent to un-reference this file."
                })
                
    # 3. Check for massive tool outputs (e.g. build logs, massive directory listings)
    for t in turns:
        for tool in t.get("tool_details", []):
            if tool["tokens"] > 10000:
                recommendations.append({
                    "type": "warning",
                    "message": f"Tool '{tool['name']}' returned a massive output ({tool['tokens']:,} tokens) in turn {t['turn_index']}. "
                               f"Starting a new chat will prune this output and reclaim 90% of context space."
                })
                
    return recommendations

def generate_local_bridge(audit_data: dict, config: Config, use_llm: bool = False) -> str:
    """Generates a structured context summary to bridge to a new session."""
    agent = audit_data.get("agent", "unknown").upper()
    model = audit_data.get("model", "unknown")
    modified = audit_data.get("modified_files", [])
    prompts = audit_data.get("user_prompts", [])
    
    # 1. Fallback Rule-Based Bridging
    last_goal = prompts[-1] if prompts else "No target goal specified."
    
    bridge = (
        f"### 🤝 CONTEXT BRIDGE SUMMARY (Resuming active session from {agent})\n"
        f"**Source Agent/Model**: {agent} ({model})\n"
        f"**Latest Goal/Request**: \"{last_goal}\"\n"
    )
    
    if modified:
        bridge += "**Modified Code Files**:\n"
        for f in modified:
            bridge += f"  - `{f}`\n"
    else:
        bridge += "**Modified Code Files**: None detected.\n"
        
    if len(prompts) > 1:
        bridge += "\n**Session Development Path**:\n"
        # Take up to last 4 prompts
        for p in prompts[-4:-1]:
            bridge += f"  - User asked: \"{p[:80]}...\"\n"
            
    # 2. Smart LLM-Based Bridging if Ollama is running and requested
    if use_llm:
        try:
            llm = LLMClient(config)
            # Create compressed transcript representation to avoid context overflow in local Ollama
            history_summary = []
            for p in prompts[-5:]:
                history_summary.append(f"User: {p}")
            history_text = "\n".join(history_summary)
            
            prompt = (
                f"You are a development session summarizer. Review the user prompts and modified files in the active session "
                f"and write a short, highly professional transition summary (under 4 bullet points, Vietnamese or English matching user language) "
                f"to be copied into a fresh coding chat to resume development immediately.\n\n"
                f"--- SESSION INFORMATION ---\n"
                f"Modified files: {', '.join(modified) if modified else 'None'}\n"
                f"Recent Chat History:\n{history_text}\n\n"
                f"--- INSTRUCTIONS ---\n"
                f"Keep it under 100 words. Focus strictly on: 1. What was done, 2. Current status, 3. Immediate next step."
            )
            
            summary_content = llm.client.chat(
                model=llm.model,
                messages=[{"role": "user", "content": prompt}]
            )
            llm_summary = summary_content.get("message", {}).get("content", "").strip()
            if llm_summary and not llm_summary.startswith("Error"):
                bridge += f"\n**AI Generated Transition Summary**:\n{llm_summary}\n"
        except Exception as e:
            # Silent fallback to rule-based on LLM errors
            pass
            
    return bridge
