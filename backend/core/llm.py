"""Claude inference over the `claude` CLI.

Mirrors the transport bitsy uses on this machine (bitsy/llm/llm_client.py):
Claude Code is driven as a pure INFERENCE PROVIDER, not as an agent. The agent's
tools run in Python; the CLI only turns a prompt into text.

Three properties carried over deliberately:

1. The prompt goes over stdin, not argv, avoiding Windows command-line length
   limits and quoting hazards with multi-line financial context.
2. ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN are stripped from the child env so
   the CLI authenticates with the user's own Claude login.
3. Every built-in tool is denied and permission mode stays `default`, never
   `bypassPermissions`. With bypass, any tool missing from the deny list would
   execute silently; without it, an unlisted tool needs an approval this
   non-interactive run cannot give, so it fails closed. That matters here
   because the prompt contains user-supplied financial data -- a prompt
   injection hidden in it must not reach a shell or the filesystem.
"""

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field

import requests

import config

_CLAUDE_BIN = None


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    duration_s: float
    cost_usd: float = 0.0
    permission_denials: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StreamUsage:
    """Yielded last by stream(), after every text chunk."""
    model: str
    duration_s: float
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


def find_claude_bin() -> str:
    global _CLAUDE_BIN
    if _CLAUDE_BIN:
        return _CLAUDE_BIN
    found = (shutil.which("claude") or shutil.which("claude.exe")
             or shutil.which("claude.cmd"))
    if not found:
        raise LLMError(
            "`claude` CLI not found on PATH. Install Claude Code and sign in, "
            "or set PATH so `claude` resolves.")
    _CLAUDE_BIN = found
    return found


def complete(prompt: str, model: str | None = None,
             timeout: int | None = None) -> LLMResult:
    """One stateless inference call. Returns the model's text.

    Routed to the claude CLI or Azure OpenAI by config.LLM_PROVIDER (set from
    backend/.env). Both sides keep the same contract -- the agent keeps
    conversation state itself and resends it each turn, so no session is
    reused on either transport; each call is independent and reproducible.
    """
    timeout = timeout or config.CLAUDE_CLI_TIMEOUT
    if config.LLM_PROVIDER == "azure":
        return _complete_azure(prompt, model, timeout)
    return _complete_cli(prompt, model or config.CLAUDE_CLI_MODEL, timeout)


def _complete_azure(prompt: str, model: str | None, timeout: int) -> LLMResult:
    """One stateless call to an Azure OpenAI-compatible chat endpoint.

    The whole prompt (system rules, benchmark context, conversation so far)
    is sent as a single user message, exactly as it is sent to the CLI over
    stdin -- callers (core/agent.py, core/mapper.py) build one flat string
    and don't need to know which transport is live.

    Azure doesn't report a dollar cost in the response the way the CLI's
    `total_cost_usd` does, so cost_usd is always 0 on this path: the
    session/turn cost shown in the UI won't reflect Azure spend.
    """
    endpoint = config.AZURE_OPENAI_ENDPOINT
    deployment = model or config.AZURE_OPENAI_DEPLOYMENT
    key = config.AZURE_OPENAI_API_KEY
    if not (endpoint and deployment):
        raise LLMError("Azure OpenAI is not configured: set "
                       "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT in "
                       "backend/.env.")
    if not key:
        raise LLMError("AZURE_OPENAI_API_KEY is not set in backend/.env.")

    url = f"{endpoint.rstrip('/')}/chat/completions"
    started = time.time()
    try:
        resp = requests.post(
            url,
            headers={"api-key": key, "Content-Type": "application/json"},
            json={"model": deployment,
                 "messages": [{"role": "user", "content": prompt}],
                 "temperature": 0.2},
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise LLMError(f"Azure OpenAI request failed: {e}") from e
    duration = time.time() - started

    if resp.status_code != 200:
        raise LLMError(f"Azure OpenAI returned {resp.status_code}: "
                       f"{resp.text[:400]}")

    # requests guesses response encoding from the Content-Type header, and
    # Azure's JSON responses don't always declare a charset -- that guess can
    # land on latin-1 and mangle every em dash and curly quote the model
    # writes. Decoding the raw bytes as UTF-8 ourselves sidesteps the guess.
    try:
        payload = json.loads(resp.content.decode("utf-8"))
        text = payload["choices"][0]["message"]["content"] or ""
    except (UnicodeDecodeError, ValueError, KeyError, IndexError) as e:
        raise LLMError("Azure OpenAI returned an unexpected payload: "
                       f"{resp.text[:300]}") from e

    return LLMResult(text=text, model=deployment, duration_s=duration,
                     cost_usd=0.0)


def _complete_cli(prompt: str, model: str, timeout: int) -> LLMResult:
    """One stateless inference call over the claude CLI. Returns the model's
    text.

    The agent keeps conversation state itself and resends it each turn, so no
    CLI session is reused -- each call is independent and reproducible.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)

    cmd = [
        find_claude_bin(),
        "-p",
        "--model", model,
        "--output-format", "json",
        "--disallowedTools", ",".join(config.CLAUDE_CLI_DISALLOWED_TOOLS),
        "--permission-mode", "default",
    ]

    started = time.time()
    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"claude CLI timed out after {timeout}s") from e
    duration = time.time() - started

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-400:]
        raise LLMError(f"claude CLI exited {proc.returncode}: {tail}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise LLMError(
            f"claude CLI returned non-JSON output: {proc.stdout[:300]}") from e

    if payload.get("is_error"):
        raise LLMError(f"claude CLI reported an error: "
                       f"{payload.get('result') or payload}")

    # If the model tried to use a tool, it was refused -- but record it. A
    # denial here means something in the prompt steered toward a tool, which
    # is worth knowing about when the prompt carries uploaded data.
    denials = payload.get("permission_denials") or []

    used = payload.get("modelUsage") or {}
    reported = next((m for m in used if m.startswith(model.split("[")[0])),
                    model)

    return LLMResult(
        text=payload.get("result") or "",
        model=reported,
        duration_s=duration,
        cost_usd=float(payload.get("total_cost_usd") or 0.0),
        permission_denials=denials,
    )


# --- streaming -----------------------------------------------------------------

def stream(prompt: str, model: str | None = None, timeout: int | None = None):
    """Yield text as the model writes it, then one StreamUsage.

    Same transport contract as complete(), but over `--output-format
    stream-json`, so a caller can show the reply forming instead of waiting for
    the whole turn. Only the CLI streams natively; Azure has no streaming path
    here, so it yields its finished text in one chunk and the caller's code
    stays identical either way.

    The subprocess plumbing follows bitsy: stdin is written on its own thread
    and stderr drained on another. Writing a large prompt inline while nothing
    reads stdout deadlocks as soon as either pipe buffer fills -- and these
    prompts carry the whole benchmark context, so they are comfortably large
    enough to do it.
    """
    if config.LLM_PROVIDER == "azure":
        res = _complete_azure(prompt, model, timeout or config.CLAUDE_CLI_TIMEOUT)
        if res.text:
            yield res.text
        yield StreamUsage(model=res.model, duration_s=res.duration_s,
                          cost_usd=res.cost_usd)
        return

    import threading

    model = model or config.CLAUDE_CLI_MODEL
    timeout = timeout or config.CLAUDE_CLI_TIMEOUT

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)

    cmd = [
        find_claude_bin(),
        "-p",
        "--model", model,
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--disallowedTools", ",".join(config.CLAUDE_CLI_DISALLOWED_TOOLS),
        "--permission-mode", "default",
    ]

    started = time.time()
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env, text=True, encoding="utf-8",
        errors="replace", bufsize=1,
    )

    def _feed():
        try:
            if proc.stdin:
                proc.stdin.write(prompt)
                proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    threading.Thread(target=_feed, daemon=True).start()

    stderr_chunks: list = []

    def _drain():
        try:
            if proc.stderr:
                stderr_chunks.extend(iter(proc.stderr.readline, ""))
        except Exception:
            pass

    stderr_thread = threading.Thread(target=_drain, daemon=True)
    stderr_thread.start()

    # A run that never terminates would otherwise hang the request thread; the
    # blocking complete() path gets this from subprocess.run(timeout=).
    killer = threading.Timer(timeout, proc.kill)
    killer.start()

    usage_in = usage_out = 0
    cost = 0.0
    actual_model = model
    last_err = None

    try:
        if proc.stdout:
            for raw in iter(proc.stdout.readline, ""):
                line = raw.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue

                t = obj.get("type")
                if t == "system" and obj.get("subtype") == "init":
                    actual_model = obj.get("model") or actual_model
                elif t == "stream_event":
                    ev = obj.get("event", {})
                    if ev.get("type") == "content_block_delta":
                        delta = ev.get("delta", {})
                        if delta.get("type") == "text_delta":
                            txt = delta.get("text", "")
                            if txt:
                                yield txt
                    elif ev.get("type") == "message_start":
                        u = (ev.get("message", {}) or {}).get("usage", {}) or {}
                        usage_in = u.get("input_tokens", usage_in)
                elif t == "result":
                    if obj.get("is_error"):
                        last_err = obj.get("result") or str(obj)
                    u = obj.get("usage", {}) or {}
                    usage_in = u.get("input_tokens", usage_in)
                    usage_out = u.get("output_tokens", usage_out)
                    cost = float(obj.get("total_cost_usd") or 0.0)
    finally:
        killer.cancel()

    rc = proc.wait()
    if rc != 0 or last_err:
        stderr_thread.join(timeout=1.0)
        tail = ("".join(stderr_chunks))[-400:]
        raise LLMError(f"claude CLI exited {rc}: {last_err or tail}")

    yield StreamUsage(model=actual_model, duration_s=time.time() - started,
                      cost_usd=cost, input_tokens=usage_in,
                      output_tokens=usage_out)
