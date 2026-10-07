import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ai_agent.tracer")

DEFAULT_LOG_DIR = Path("logs/chatbot")


class LocalTracer:
    """Local file-based observability and tracing for OpenBIS AI Agent.
    
    Provides offline tracing of LLM prompts, tool executions, arguments, returns,
    token usage, and latency without requiring external services like Langfuse.
    """

    def __init__(self, log_dir: Optional[Path] = None):
        self.log_dir = Path(log_dir or DEFAULT_LOG_DIR)
        self.traces_file = self.log_dir / "traces.jsonl"
        self.history_file = self.log_dir / "chat_history.log"
        self._ensure_log_dir()

    def _ensure_log_dir(self):
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create trace log dir {self.log_dir}: {e}")

    def log_run(
        self,
        user_prompt: str,
        result: Any,
        elapsed_seconds: float,
        model_name: str = "",
        provider_name: str = "",
        session_id: str = "",
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record an agent execution run with tool calls and usage metrics."""
        self._ensure_log_dir()
        now = datetime.now(timezone.utc).isoformat()
        run_id = getattr(result, "run_id", None) or str(uuid.uuid4())

        # Extract usage
        usage_info = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "requests": 0}
        if hasattr(result, "usage") and result.usage is not None:
            u = result.usage
            in_tok = getattr(u, "input_tokens", 0) or 0
            out_tok = getattr(u, "output_tokens", 0) or 0
            usage_info = {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
                "requests": getattr(u, "requests", 1) or 1,
            }

        # Extract tool calls and returns
        tool_calls: List[Dict[str, Any]] = []
        if hasattr(result, "new_messages"):
            try:
                for m in result.new_messages():
                    for p in getattr(m, "parts", []):
                        pkind = getattr(p, "part_kind", None)
                        if pkind == "tool-call":
                            tool_calls.append({
                                "tool_name": getattr(p, "tool_name", ""),
                                "args": getattr(p, "args", {}),
                                "tool_call_id": getattr(p, "tool_call_id", None),
                                "return_value": None,
                            })
                        elif pkind == "tool-return":
                            tcid = getattr(p, "tool_call_id", None)
                            ret_content = getattr(p, "content", "")
                            for tc in tool_calls:
                                if tc.get("tool_call_id") == tcid or (tcid is None and tc["return_value"] is None):
                                    # Preview or full content (truncate if extremely large)
                                    str_val = str(ret_content)
                                    if len(str_val) > 4000:
                                        tc["return_value"] = str_val[:4000] + "... [truncated in trace]"
                                    else:
                                        tc["return_value"] = ret_content
                                    break
            except Exception as e:
                logger.warning(f"Error parsing tool calls from run result: {e}")

        final_output = getattr(result, "output", "") if result is not None else ""
        if error:
            final_output = f"ERROR: {error}"

        trace_entry = {
            "timestamp": now,
            "run_id": run_id,
            "session_id": session_id,
            "model": model_name,
            "provider": provider_name,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "usage": usage_info,
            "user_prompt": user_prompt,
            "tool_calls": tool_calls,
            "final_output": final_output,
            "error": error,
        }

        # 1. Append to traces.jsonl
        try:
            with open(self.traces_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(trace_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write to {self.traces_file}: {e}")

        # 2. Append to human-readable chat_history.log
        try:
            readable_lines = [
                f"\n{'='*70}",
                f"[{now}] RUN: {run_id[:8]} | Model: {model_name} ({provider_name}) | Time: {elapsed_seconds:.2f}s | Tokens: {usage_info['total_tokens']}",
                f"USER: {user_prompt}",
            ]
            if tool_calls:
                readable_lines.append(f"TOOL CALLS ({len(tool_calls)}):")
                for i, tc in enumerate(tool_calls, 1):
                    readable_lines.append(f"  [{i}] {tc['tool_name']}({json.dumps(tc['args'], ensure_ascii=False)})")
                    ret = str(tc.get("return_value") or "")
                    ret_preview = ret[:200].replace("\n", " ") + ("..." if len(ret) > 200 else "")
                    readable_lines.append(f"      -> {ret_preview}")
            else:
                readable_lines.append("TOOL CALLS: None (Direct LLM response)")

            readable_lines.append(f"RESPONSE:\n{final_output}")
            readable_lines.append(f"{'='*70}\n")

            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write("\n".join(readable_lines))
        except Exception as e:
            logger.warning(f"Failed to write to {self.history_file}: {e}")

        return trace_entry

    def get_recent_traces(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the most recent traces from traces.jsonl."""
        if not self.traces_file.exists():
            return []
        traces = []
        try:
            with open(self.traces_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        traces.append(json.loads(line))
        except Exception as e:
            logger.warning(f"Failed to read {self.traces_file}: {e}")
        return traces[-limit:]

    def get_last_trace(self) -> Optional[Dict[str, Any]]:
        """Return the very last trace entry."""
        recent = self.get_recent_traces(limit=1)
        return recent[-1] if recent else None
