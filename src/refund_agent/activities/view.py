"""Display helpers: what the agent holds in process, printed and mirrored to disk.

The Activities call these to print each step and to mirror the agent's
in-process view for the stage screen. This is display code, not Activity
logic, and none of it is part of Event History.
"""

from __future__ import annotations

import json
import os

from refund_agent.settings import agent_view_path, state_dir

# THE AGENT: these caches deliberately live only in this Worker process, keyed
# by Workflow ID so concurrent runs never clobber one another. Temporal never
# reads them. A restart erases them, which is the whole point on stage.
_agent_views: dict[str, dict[str, object]] = {}


def _view_for(workflow_id: str | None) -> dict[str, object]:
    return _agent_views.setdefault(workflow_id or "unknown", {})


def _line(label: str, value: object) -> None:
    if isinstance(value, str):
        rendered = value
    else:
        rendered = json.dumps(value, indent=2, sort_keys=True)
    print(f"{label} | {rendered}", flush=True)


def show_empty_agent_view() -> None:
    _agent_views.clear()
    # A new Worker process holds no agent memory, so wipe the on-disk mirror the
    # TUI reads. After a restart this is what makes THE AGENT panel
    # read empty while THE SYSTEM OF RECORD panel resumes.
    for path in state_dir().glob("agent-view-*.json"):
        path.unlink(missing_ok=True)
    _line("THE AGENT", "new process, in-process view is empty")


def _mirror_agent_view(workflow_id: str | None, view: dict[str, object]) -> None:
    # Mirror the in-process view to disk so the TUI can render THE AGENT panel.
    # The TUI trusts this file only while the Worker PID is alive, so the view
    # still reads as lost the moment the Worker is killed.
    if not workflow_id:
        return
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = agent_view_path(workflow_id)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(view, indent=2, sort_keys=True), encoding="utf-8"
    )
    os.replace(temporary_path, path)


def _agent_summary(view: dict[str, object]) -> str:
    # A concise, stage-legible view of what the agent holds in process.
    parts: list[str] = []
    context = view.get("context")
    if isinstance(context, dict):
        parts.append(f"context({context.get('request_id')})")
    observations = view.get("observations")
    if isinstance(observations, list) and observations:
        tools = ", ".join(str(obs.get("tool")) for obs in observations)
        parts.append(f"memory({tools})")
    decision = view.get("decision")
    if isinstance(decision, dict):
        parts.append(f"decision({decision.get('recommendation')})")
    return " + ".join(parts) if parts else "empty"
