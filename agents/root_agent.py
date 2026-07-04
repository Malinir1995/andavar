import json
import re
import logging
from typing import Dict, Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.schema_designer import schema_designer
from agents.sql_generator import sql_generator
from agents.explainer import explainer
from agents.mock_data_generator import mock_data_generator
from tools.memory_store import save_version, get_latest_version
from tools.schema_diff import diff_schemas, format_diff_markdown

logger = logging.getLogger("andavar.root_agent")

# ── Per-session chat runners (maintained for conversation memory) ─────────────
_chat_runners: Dict[str, Runner] = {}


def _extract_json(text: str) -> str:
    """Strip markdown code fences and extract the first JSON object/array."""
    fenced = re.sub(r"```(?:json)?\s*", "", text)
    fenced = fenced.replace("```", "").strip()
    match = re.search(r"(\{.*\}|\[.*\])", fenced, re.DOTALL)
    return match.group(1).strip() if match else fenced


async def _run_with_retry(runner: Runner, session_id: str, prompt: str) -> str:
    """Run a Runner with automatic retry on 429/503 errors.

    After a successful invocation that returns no text (model silently stopped
    after tool calls), a single nudge message is sent on the same session so
    the model summarises the tool results it already has in context.
    """
    import asyncio
    import google.adk.models.google_llm as _gllm

    max_retries = 3
    base_delay = 2.0

    async def _stream_once(msg: str) -> tuple[str, object]:
        """Run one runner.run_async pass; return (text, structured_output)."""
        text = ""
        structured = None
        async for event in runner.run_async(
            user_id="default_user",
            session_id=session_id,
            new_message=types.Content(
                role="user", parts=[types.Part(text=msg)]
            ),
        ):
            if event.output is not None:
                structured = event.output
            # Only aggregate text from model-authored events; skip function_response parts
            if (
                event.content
                and event.content.role == "model"
                and event.content.parts
            ):
                chunk = "".join(p.text for p in event.content.parts if p.text)
                if chunk:
                    text += chunk
        return text, structured

    last_text = ""
    structured_output = None

    for attempt in range(max_retries + 1):
        try:
            last_text, structured_output = await _stream_once(prompt)
            break  # API call succeeded

        except Exception as e:
            error_msg = str(e)
            is_429 = (
                "429" in error_msg
                or "RESOURCE_EXHAUSTED" in error_msg
                or isinstance(e, _gllm._ResourceExhaustedError)
            )
            is_503 = "503" in error_msg or "UNAVAILABLE" in error_msg
            if (is_429 or is_503) and attempt < max_retries:
                if is_429:
                    m = re.search(r"Please retry in ([\d\.]+)s", error_msg)
                    delay = float(m.group(1)) + 1.5 if m else base_delay * (2 ** attempt)
                    logger.warning("Quota hit. Retry %d/%d in %.1fs", attempt + 1, max_retries, delay)
                else:
                    delay = 5.0 * (attempt + 1)
                    logger.warning("503 Unavailable. Retry %d/%d in %.1fs", attempt + 1, max_retries, delay)
                await asyncio.sleep(delay)
                continue
            if isinstance(e, _gllm._ResourceExhaustedError):
                raise RuntimeError(
                    "Gemini quota exhausted (429). Free-tier daily limit reached. "
                    "Please wait for reset or upgrade at https://ai.dev/rate-limit"
                ) from e
            raise RuntimeError(f"Model call failed ({type(e).__name__}): {e}") from e

    # ── Structured output takes priority ────────────────────────────────────
    if structured_output is not None:
        if hasattr(structured_output, "model_dump_json"):
            return structured_output.model_dump_json()
        if isinstance(structured_output, (dict, list)):
            return json.dumps(structured_output)
        return str(structured_output)

    # ── Empty-text recovery (model stopped silently after tool calls) ────────
    # gemini-2.5-flash-lite sometimes finishes a turn with empty content after
    # executing tools. Send a one-shot nudge on the same session; the model
    # already has the tool results in its context, so it will summarise them.
    if not last_text.strip():
        logger.warning(
            "Empty model text for session %s – sending nudge to surface tool results",
            session_id,
        )
        try:
            nudge_text, nudge_structured = await _stream_once(
                "Please summarise the results from your previous tool calls in a clear, helpful reply."
            )
            if nudge_structured is not None:
                if hasattr(nudge_structured, "model_dump_json"):
                    return nudge_structured.model_dump_json()
                if isinstance(nudge_structured, (dict, list)):
                    return json.dumps(nudge_structured)
                return str(nudge_structured)
            if nudge_text.strip():
                return nudge_text
        except Exception as nudge_err:
            logger.warning("Nudge request failed: %s", nudge_err)

    return last_text


async def run_agent_async(agent, prompt: str, session_id: str) -> str:
    """One-shot agent run (used by schema workflow). Creates a fresh session each call."""
    from tools.memory_store import AGENT_RUNS
    AGENT_RUNS[agent.name] = AGENT_RUNS.get(agent.name, 0) + 1

    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        session_service=session_service,
        app_name=agent.name,
        auto_create_session=True,
    )
    return await _run_with_retry(runner, session_id, prompt)


async def run_chat_async(message: str, session_id: str) -> str:
    """
    Run the conversational chat agent with persistent per-session memory.
    The same runner is reused for the same session_id so conversation history
    is maintained across multiple calls.
    """
    from agents.chat_agent import chat_agent
    from tools.memory_store import AGENT_RUNS
    AGENT_RUNS["andavar_chat"] = AGENT_RUNS.get("andavar_chat", 0) + 1

    if session_id not in _chat_runners:
        session_service = InMemorySessionService()
        _chat_runners[session_id] = Runner(
            agent=chat_agent,
            session_service=session_service,
            app_name="andavar_chat",
            auto_create_session=True,
        )

    return await _run_with_retry(_chat_runners[session_id], session_id, message)


async def generate_schema_workflow(
    prompt: str, session_id: str, label: str = None
) -> Dict[str, Any]:
    """
    Four-agent schema pipeline:
    Schema Designer → SQL Generator → Explainer → Mock Data Generator → Save to history
    """
    latest_ver = get_latest_version(session_id)
    if latest_ver:
        designer_prompt = (
            f"Existing schema:\n{json.dumps(latest_ver['schema_json'], indent=2)}\n\n"
            f"Modify based on user request: {prompt}"
        )
    else:
        designer_prompt = prompt

    designer_output = await run_agent_async(schema_designer, designer_prompt, session_id)
    raw = designer_output.strip()
    if not raw:
        raise ValueError("Schema designer returned an empty response.")

    extracted = _extract_json(raw)
    try:
        schema_json = json.loads(extracted)
    except json.JSONDecodeError as e:
        raise ValueError(f"Schema designer produced invalid JSON: {e}")

    if latest_ver:
        sql_prompt = (
            "Generate PostgreSQL migration DDL to migrate from the Old Schema to the New Schema.\n\n"
            f"Old Schema:\n{json.dumps(latest_ver['schema_json'], indent=2)}\n\n"
            f"New Schema:\n{json.dumps(schema_json, indent=2)}"
        )
    else:
        sql_prompt = f"Convert this JSON schema into PostgreSQL DDL:\n{json.dumps(schema_json, indent=2)}"
    sql_output = await run_agent_async(sql_generator, sql_prompt, session_id)

    explainer_prompt = (
        f"Explain this schema:\nJSON:\n{json.dumps(schema_json, indent=2)}\n\nSQL:\n{sql_output}"
    )
    explanation = await run_agent_async(explainer, explainer_prompt, session_id)

    # Run Mock Data Generator
    mock_prompt = f"Generate realistic SQL INSERT statements for this schema:\n{sql_output}"
    mock_data_sql = await run_agent_async(mock_data_generator, mock_prompt, session_id)

    from tools.memory_store import active_project_id
    version_num = save_version(
        session_id=session_id,
        schema_json=schema_json,
        sql_output=sql_output,
        explanation=explanation,
        label=label,
        project_id=active_project_id.get(),
        mock_data_sql=mock_data_sql,
    )

    diff_markdown = ""
    if latest_ver:
        diff_data = diff_schemas(latest_ver["schema_json"], schema_json)
        diff_markdown = format_diff_markdown(diff_data)

    return {
        "session_id": session_id,
        "version": version_num,
        "schema_design": schema_json,
        "sql": sql_output,
        "explanation": explanation,
        "mock_data_sql": mock_data_sql,
        "diff_markdown": diff_markdown,
        "timestamp": None,
    }
