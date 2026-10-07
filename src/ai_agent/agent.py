"""agent.py: PydanticAI-powered agent for querying openBIS.

Supports CSCS, Google Gemini, and OpenAI LLM providers with robust, read-only
tools and persistent message history.
"""

import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from src import utils
from . import tools
from . import openbis_client
from .tracer import LocalTracer


try:
    import nest_asyncio
    nest_asyncio.apply()
except Exception:
    pass


def get_current_time() -> str:
    now = datetime.now(ZoneInfo("Europe/Zurich"))
    return now.strftime("%A, %B %d, %Y at %H:%M (Europe/Zurich)")


def load_schema_documentation() -> str:
    """Dynamically read the openBIS schema documentation from docs/openBIS_schema_documentation.md."""
    possible_paths = [
        Path("docs/openBIS_schema_documentation.md"),
        Path("/home/jovyan/apps/aiidalab-openbis/docs/openBIS_schema_documentation.md"),
        Path("../docs/openBIS_schema_documentation.md"),
    ]
    for p in possible_paths:
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except Exception as e:
                print(f"Warning reading schema documentation from {p}: {e}")
    return ""


def load_system_prompt() -> str:
    possible_paths = [
        Path("data/system_prompt.txt"),
        Path("/home/jovyan/apps/aiidalab-openbis/data/system_prompt.txt"),
        Path("ai_agent/data/system_prompt.txt"),
    ]
    prompt_text = ""
    for p in possible_paths:
        if p.exists():
            prompt_text = p.read_text(encoding="utf-8")
            break

    if not prompt_text:
        prompt_text = (
            "You are NanoSurfaces Prime, an expert AI scientific assistant for openBIS. "
            "You provide strictly read-only information about materials, samples, instruments, and experiments."
        )

    prompt_text += f"\n\nCURRENT DATE & TIME: {get_current_time()}."

    # Dynamically inject the active openBIS user and home space if available
    try:
        from src.ai_agent import openbis_client
        user_info = openbis_client.get_current_user()
        if user_info and user_info.get("username"):
            prompt_text += (
                f"\n\n### Current Active User & Session Context:\n"
                f"- **Logged-in Username**: `{user_info['username']}`\n"
                f"- **Home Space**: `{user_info['home_space']}`\n"
                f"When the user asks 'who am I?', 'what is my username?', 'my projects', or 'my space', "
                f"refer to this user and their home space directly.\n"
            )
    except Exception as e:
        print(f"Could not load user context: {e}")

    # Always dynamically append the latest openBIS schema documentation from the markdown file
    schema_doc = load_schema_documentation()
    if schema_doc:
        prompt_text += (
            f"\n\n### OpenBIS Data Model & Schema Documentation (loaded from docs/openBIS_schema_documentation.md):\n\n"
            f"{schema_doc}"
        )

    return prompt_text


KNOWN_ACTION_TYPES = {
    "DEPOSITION", "ANNEALING", "SPUTTERING", "DOSING", "COOLDOWN",
    "HEATING", "TRANSFER", "MEASUREMENT", "GROWTH", "CLEANING", "EVAPORATION"
}


def fix_table_alignment(text: str) -> str:
    """Ensure every row in Markdown tables has the correct number of columns and aligns multi-action rows."""
    lines = text.split("\n")
    fixed_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Check if line looks like a table header
        if (
            line.strip().startswith("|")
            and line.strip().endswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\s*\|?\s*:?-+:?\s*\|", lines[i + 1])
        ):
            header_line = line
            sep_line = lines[i + 1]
            header_cells = [c.strip() for c in header_line.strip().strip("|").split("|")]
            expected_cols = len(header_cells)

            fixed_lines.append(header_line)
            fixed_lines.append(sep_line)
            i += 2

            # Process table body rows
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                row = lines[i].strip()
                row_cells = [c.strip() for c in row.strip("|").split("|")]

                if len(row_cells) < expected_cols:
                    diff = expected_cols - len(row_cells)
                    # Check if the first cell is an Action type or matches column 3
                    first_cell_upper = row_cells[0].upper().strip("`* ")
                    if first_cell_upper in KNOWN_ACTION_TYPES or any(act in first_cell_upper for act in KNOWN_ACTION_TYPES):
                        # Prepend empty cells to align with Action / Details / Duration
                        row_cells = [""] * diff + row_cells
                    else:
                        # Append empty cells
                        row_cells = row_cells + [""] * diff
                elif len(row_cells) > expected_cols:
                    if row_cells[-1] == "":
                        row_cells = row_cells[:expected_cols]

                fixed_lines.append("| " + " | ".join(row_cells) + " |")
                i += 1
            continue
        else:
            fixed_lines.append(line)
            i += 1

    return "\n".join(fixed_lines)


def replace_latex_arrows(text: str) -> str:
    """Replace LaTeX arrow macros with clean Unicode arrows."""
    replacements = [
        (r'\\longrightarrow', '→'),
        (r'\\longleftarrow', '←'),
        (r'\\rightarrow', '→'),
        (r'\\leftarrow', '←'),
        (r'\\to\b', '→'),
        (r'\\leftrightarrow', '↔'),
        (r'\\Longrightarrow', '⇒'),
        (r'\\Longleftarrow', '⇐'),
        (r'\\Rightarrow', '⇒'),
        (r'\\Leftarrow', '⇐'),
        (r'\\Leftrightarrow', '⇔'),
    ]
    for pat, rep in replacements:
        text = re.sub(pat, rep, text)
    return text


def standardize_markdown(text: str) -> str:
    """Normalize markdown formatting:
    - Downscale # and ## headings to ### to maintain compact chat typography
    - Replace LaTeX arrow macros with clean Unicode arrows (e.g. \rightarrow -> →)
    - Fix single-line table rows concatenated with ||
    - Align multi-action rows in Markdown tables so sub-actions match column headers
    - Clean up raw LaTeX math syntax for chemical formulas (e.g. $\text{C}_{64}...$)
    """
    if not text:
        return ""
    # Replace LaTeX arrow macros
    text = replace_latex_arrows(text)
    # Fix tables concatenated without newlines
    text = re.sub(r'\|\s*\|', '|\n|', text)
    # Fix table column alignment for multi-action rows
    text = fix_table_alignment(text)
    # Downscale top-level h1 and h2 markdown headers to ###
    text = re.sub(r'^(#{1,2})\s+(.+)$', r'### \2', text, flags=re.MULTILINE)
    # Normalize LaTeX formulas: $\text{C}_{64}\text{H}_{51}\text{Br}$ -> C64H51Br
    text = re.sub(r'\\text\{([A-Za-z0-9]+)\}', r'\1', text)
    text = re.sub(r'\_\{([A-Za-z0-9]+)\}', r'\1', text)
    text = re.sub(r'\^\{([A-Za-z0-9\+\-]+)\}', r'\1', text)
    text = text.replace('$', '')
    return text


def resolve_openbis_previews(text: str) -> str:
    """Find and replace openbis-preview:<permid> references with inline base64 image URIs."""
    if not text or "openbis-preview:" not in text:
        return text

    pattern = re.compile(r'openbis-preview:([a-zA-Z0-9\-_]+)')
    matches = set(pattern.findall(text))
    for pid in matches:
        b64_uri = openbis_client.get_preview_image_base64(pid)
        if b64_uri:
            text = text.replace(f"openbis-preview:{pid}", b64_uri)
        else:
            # If preview cannot be fetched, remove the preview line cleanly
            text = re.sub(rf'- \*\*Structure Preview\*\*:\s*!\[[^\]]*\]\(openbis-preview:{re.escape(pid)}\)\n?', '', text)
            text = text.replace(f"openbis-preview:{pid}", "")
    return text


def ensure_permid_links(text: str) -> str:
    """Ensure any unlinked openBIS permIDs in text are converted to markdown links without double-wrapping."""
    base_url = openbis_client.get_eln_url()
    if not base_url:
        return text

    # Tokenize: preserve existing markdown links [label](url), HTML tags <...>, or full URLs
    token_pattern = re.compile(r'(\[[^\]]*\]\([^\)]*\)|<[^>]*>|https?://[^\s\)]+)')
    parts = token_pattern.split(text)
    permid_re = re.compile(r'`?(\d{17}-\d+)`?')

    for i in range(0, len(parts), 2):  # even indices are plain text
        def replace_pid(m):
            pid = m.group(1)
            url = f"{base_url}?viewName=showViewSamplePageFromPermId&viewData=%7B%22permIdOrIdentifier%22:%22{pid}%22%7D"
            return f"[{pid}]({url})"

        parts[i] = permid_re.sub(replace_pid, parts[i])

    return "".join(parts)


class OpenBISAgent:
    """Read-only AI Agent for openBIS using PydanticAI."""

    def __init__(self, config_path: str = "/home/jovyan/api_keys/llm_config.json"):
        self.config_path = config_path
        self.message_history: List[Any] = []
        self.tracer = LocalTracer()
        self.model_name = ""
        self.provider_name = ""
        self._init_agent()

    def _init_agent(self):
        llm_cfg = {}
        if Path(self.config_path).exists():
            try:
                llm_cfg = utils.read_json(self.config_path)
            except Exception as e:
                print(f"Warning reading config from {self.config_path}: {e}")

        self.provider_name = os.environ.get("LLM_PROVIDER") or llm_cfg.get("llm_provider", "CSCS")
        self.model_name = os.environ.get("LLM_MODEL") or llm_cfg.get("llm_model", "google/gemma-4-31B-it")
        api_key = os.environ.get("LLM_API_KEY") or llm_cfg.get("llm_api_key", "")

        if self.provider_name == "CSCS":
            provider = OpenAIProvider(
                base_url="https://api.inference.cscs.ch/v1",
                api_key=api_key,
            )
            model = OpenAIChatModel(model_name=self.model_name, provider=provider)
        elif self.provider_name == "Google Gemini":
            provider = GoogleProvider(api_key=api_key)
            model = GoogleModel(model_name=self.model_name, provider=provider)
        elif self.provider_name == "OpenAI":
            provider = OpenAIProvider(api_key=api_key)
            model = OpenAIChatModel(model_name=self.model_name, provider=provider)
        else:
            # Fallback to CSCS
            provider = OpenAIProvider(
                base_url="https://api.inference.cscs.ch/v1",
                api_key=api_key,
            )
            model = OpenAIChatModel(model_name=self.model_name, provider=provider)

        self.system_prompt = load_system_prompt()

        # Build PydanticAI Agent with read-only tools
        self.agent = Agent(
            model=model,
            system_prompt=self.system_prompt,
            tools=[
                tools.get_current_user_info,
                tools.list_spaces,
                tools.list_projects,
                tools.get_inventory_summary,
                tools.search_inventory,
                tools.get_sample_details,
                tools.get_instrument_components,
                tools.get_tools_in_room,
                tools.get_sample_preparation,
                tools.get_experiments_in_project,
                tools.get_experiment_details,
                tools.get_sample_measurements,
                tools.get_publications,
                tools.get_process_templates,
                tools.get_openbis_object,
                tools.get_schema_documentation,
            ],
        )

    def ask_question(self, user_prompt: str) -> str:
        """Run the agent on a user query and return the markdown response with openBIS links."""
        t0 = time.time()
        result = None
        err = None
        try:
            result = self.agent.run_sync(
                user_prompt,
                message_history=self.message_history if self.message_history else None,
            )
            # Update history
            self.message_history = result.all_messages()
            response_text = result.output
            response_text = standardize_markdown(response_text)
            response_text = resolve_openbis_previews(response_text)

            # Post-process to ensure all openBIS permIDs are hyperlinked
            return ensure_permid_links(response_text)
        except Exception as e:
            err = str(e)
            return f"Error executing request: {err}"
        finally:
            elapsed = time.time() - t0
            try:
                self.tracer.log_run(
                    user_prompt=user_prompt,
                    result=result,
                    elapsed_seconds=elapsed,
                    model_name=self.model_name,
                    provider_name=self.provider_name,
                    error=err,
                )
            except Exception:
                pass

    def get_last_trace(self) -> Optional[Dict[str, Any]]:
        """Return the latest execution trace."""
        return self.tracer.get_last_trace()

    def get_recent_traces(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent execution traces."""
        return self.tracer.get_recent_traces(limit=limit)

    def clear_history(self):
        """Reset conversation memory."""
        self.message_history = []

