"""Runtime configuration."""

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    """Minimal `KEY=VALUE` loader for backend/.env -- no interpolation, no
    quoting rules. A real environment variable set before the process starts
    always wins over the file, so `FOO=x python -m uvicorn ...` still works.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


_load_dotenv(BACKEND_DIR / ".env")

BENCHMARKS_PATH = Path(os.environ.get(
    "BENCHMARKS_PATH", PROJECT_DIR / "data" / "benchmarks.csv"))

# Biotechnology / Pharmaceutical membership by CIK (build_industry_map.py).
INDUSTRY_MAP_PATH = Path(os.environ.get(
    "INDUSTRY_MAP_PATH", PROJECT_DIR / "data" / "industry_map.csv"))

# Damodaran's US margins by industry (build_damodaran.py): the Insights peer
# figures for the SG&A ratios.
DAMODARAN_PATH = Path(os.environ.get(
    "DAMODARAN_PATH", PROJECT_DIR / "data" / "damodaran_margins.csv"))

# Saved diagnostics and uploaded P&Ls (core/history.py), one JSON file each.
# Delete the folder to clear every saved conversation.
HISTORY_DIR = Path(os.environ.get("HISTORY_DIR", PROJECT_DIR / "chat_history"))

# Asserted at load so a truncated rebuild fails at boot, not mid-demo.
EXPECTED_MIN_ROWS = 40_000
EXPECTED_MIN_FILERS = 8_000
EXPECTED_MIN_INDUSTRY_FILERS = 250   # biotech + pharma peers after filtering

# Peers need real revenue. Most listed biotechs are pre-commercial: below $10M
# of (often collaboration) revenue, G&A runs at a median 64% of revenue and R&D
# at 61%, ratios that say nothing about a commercial business's cost structure.
PEER_MIN_REVENUE = 10_000_000

# Smallest peer set a percentile is quoted over. Size bands within two
# industries are thin (pharma $1-5B: 8 filers), so peers widen and the
# confidence level says how far.
MIN_PEERS = 20

# Benchmarks pool the most recent fiscal years; single years are too thin.
POOL_YEARS = 3

# --- LLM transport: the `claude` CLI, used purely for inference -------------

CLAUDE_CLI_MODEL = os.environ.get("CLAUDE_CLI_MODEL", "claude-sonnet-5")
CLAUDE_CLI_TIMEOUT = int(os.environ.get("CLAUDE_CLI_TIMEOUT", "180"))

# Every built-in Claude Code tool is denied. The agent's tools run in Python;
# the CLI supplies inference only. This matters more than usual here because
# the agent reads user-supplied financials, so a prompt injection hidden in that
# data must not be able to reach a shell, the filesystem or the network.
#
# Mirrors bitsy/config.py CLAUDE_CLI_DISALLOWED_TOOLS, including its two
# hard-won entries: PowerShell (omitting it once let an agent Remove-Item a
# report) and the delegation tools, which can spawn agents not bound by this
# list and so reopen every hole above.
CLAUDE_CLI_DISALLOWED_TOOLS = [
    "Bash", "PowerShell", "KillShell", "BashOutput",
    "Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Glob", "Grep",
    "WebFetch", "WebSearch",
    "Task", "Agent", "Workflow", "Skill", "SlashCommand",
    "ScheduleWakeup", "CronCreate", "CronDelete", "CronList",
    "Artifact", "Monitor", "EndConversation",
]

# Upper bound on model calls per user message, so a confused loop cannot run up
# cost. Each call is roughly $0.05 on the CLI route.
MAX_AGENT_STEPS = 4

# --- LLM transport, alternative: Azure OpenAI-compatible inference ----------
# Same inference-only contract as the CLI path (core/llm.py): one prompt in,
# one text reply out, no tools. Auto-selected once all three are set in
# backend/.env; set LLM_PROVIDER=cli explicitly to force the claude CLI even
# with Azure configured.
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")

LLM_PROVIDER = os.environ.get("LLM_PROVIDER") or (
    "azure" if (AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT
               and AZURE_OPENAI_API_KEY) else "cli")

# Org-context retrieval. PINECONE_APIKEY is the spelling already in use in
# backend/.env; PINECONE_API_KEY is accepted too so either reads correctly.
PINECONE_API_KEY = (os.environ.get("PINECONE_APIKEY")
                    or os.environ.get("PINECONE_API_KEY", ""))
PINECONE_INDEX = os.environ.get("PINECONE_INDEX", "ebitda-org-context")

# How many document excerpts ride along with each agent turn. Every one costs
# prompt tokens on a model that already carries the benchmark context.
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "5"))

# A document pack with at most this many chunks goes into the prompt whole
# instead of being retrieved by query; see rag.render_context for why. Sixty
# chunks is roughly 40,000 characters, about 10,000 tokens.
RAG_FULL_CONTEXT_MAX = int(os.environ.get("RAG_FULL_CONTEXT_MAX", "60"))

CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:5180,http://127.0.0.1:5180").split(",")

# Default dev port. 8000 is taken by the pharma-bench app on this machine.
API_PORT = int(os.environ.get("API_PORT", "8010"))
