"""Render deterministic HTML frames for the README screenshots and demo reel."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from rich.console import Console
from rich.panel import Panel
from rich.terminal_theme import MONOKAI
from rich.text import Text

from refund_agent import tui
from refund_agent.naive_refund import _demo_frame
from refund_agent.settings import agent_view_path

WORKFLOW_ID = "demo-recovery"


def _export(renderable: object, destination: Path, *, title: str) -> None:
    console = Console(
        color_system="truecolor",
        file=io.StringIO(),
        force_terminal=True,
        height=34,
        record=True,
        width=128,
    )
    console.print(renderable)
    html = console.export_html(inline_styles=True, theme=MONOKAI)
    html = html.replace("<title>Rich</title>", f"<title>{title}</title>")
    html = html.replace(
        "<body>",
        '<body style="background:#0d1117;color:#f8f8f2;margin:0;'
        'padding:24px;overflow:hidden">',
    )
    destination.write_text(html, encoding="utf-8")


def _system_panel(
    *,
    status: str,
    phase: str,
    calls: int | None,
    attempt: int | None = None,
) -> Panel:
    body = Text()
    body.append("EXECUTION STATE — owner: Temporal\n", style="bold green")
    body.append(f"  status  {status}\n")
    body.append(f"  phase   {phase}\n\n")
    body.append("  recorded progress\n", style="bold green")
    body.append("  agent tools     2 recorded\n")
    body.append("  human approval  not needed (auto)\n")
    body.append(
        f"  refund issued   {'done' if status == 'COMPLETED' else 'pending'}\n\n"
    )
    body.append("  pending activity\n", style="bold green")
    if attempt is None:
        body.append("  none\n\n")
    else:
        body.append(f"  issue_refund attempt {attempt}\n\n")
    body.append("EFFECT STATE — owner: demo ledger\n", style="bold green")
    if calls is None:
        body.append("  none yet\n", style="dim")
    else:
        body.append(
            "  refund id  re_dry_8f31b465af82c0d1\n"
            "  status     succeeded\n"
            f"  calls {calls}  |  unique refunds 1\n"
        )
        if calls > 1:
            body.append(
                "  same key reused; same refund returned\n",
                style="green",
            )
        else:
            body.append(
                "  effect accepted; completion unrecorded\n",
                style="yellow",
            )
    return Panel(
        body,
        title="STATE (durable systems of record)",
        border_style="green",
    )


def _waiting_system_panel() -> Panel:
    body = Text()
    body.append("waiting for workflow\n\n", style="dim")
    body.append(f"no execution named {WORKFLOW_ID} yet", style="dim")
    return Panel(
        body,
        title="STATE (durable owners)",
        border_style="green",
    )


def _render_naive_frames(output_dir: Path) -> None:
    first_refund = {
        "refund_id": "re_naive_4f31a3c1",
        "order": "1234",
        "amount": 8000,
    }
    second_refund = {
        "refund_id": "re_naive_95b8d412",
        "order": "1234",
        "amount": 8000,
    }
    active_agent = {
        "context": {"order": "1234", "amount": 8000, "customer": "42"},
        "memory": {"tenure_days": 824, "prior_refunds": 1},
        "recorded": True,
        "note": "issued re_naive_4f31a3c1, then wrote a separate done marker",
    }
    duplicate_agent = {
        **active_agent,
        "note": "issued re_naive_95b8d412, then wrote a separate done marker",
    }
    frames = [
        ("01-naive-start.html", _demo_frame({}, []), "Naive demo — ready"),
        (
            "02-naive-refunded.html",
            _demo_frame(active_agent, [first_refund]),
            "Naive demo — one refund",
        ),
        (
            "03-naive-restarted.html",
            _demo_frame({"_restarted": True}, [first_refund]),
            "Naive demo — Worker restarted",
        ),
        (
            "04-naive-duplicate.html",
            _demo_frame(duplicate_agent, [first_refund, second_refund]),
            "Naive demo — duplicate refund",
        ),
    ]
    for filename, renderable, title in frames:
        _export(renderable, output_dir / filename, title=title)


def _render_durable_frames(output_dir: Path) -> None:
    original_worker_alive = tui._worker_alive
    original_state_dir = os.environ.get("DEMO_STATE_DIR")
    try:
        with TemporaryDirectory(prefix="memory-demo-media-") as temporary_dir:
            os.environ["DEMO_STATE_DIR"] = temporary_dir
            tui._worker_alive = lambda: (True, 4242)
            idle_agent = tui._agent_panel(WORKFLOW_ID)
            _export(
                tui._build(WORKFLOW_ID, idle_agent, _waiting_system_panel()),
                output_dir / "05-durable-start.html",
                title="Durable demo — ready",
            )

            view = {
                "context": {
                    "request_id": WORKFLOW_ID,
                    "order_id": "order-1234",
                    "customer_id": "cus_demo_42",
                    "amount_cents": 8000,
                },
                "observations": [
                    {"tool": "lookup_order"},
                    {"tool": "lookup_customer_history"},
                ],
                "decision": {"recommendation": "approve", "source": "canned"},
            }
            path = agent_view_path(WORKFLOW_ID)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(view), encoding="utf-8")

            tui._worker_alive = lambda: (False, 4242)
            lost_agent = tui._agent_panel(WORKFLOW_ID)
            _export(
                tui._build(
                    WORKFLOW_ID,
                    lost_agent,
                    _system_panel(
                        status="RUNNING",
                        phase="refund effect in flight",
                        calls=1,
                        attempt=1,
                    ),
                ),
                output_dir / "06-durable-lost.html",
                title="Durable demo — Worker lost",
            )

            tui._worker_alive = lambda: (True, 5252)
            recovered_agent = tui._agent_panel(WORKFLOW_ID)
            _export(
                tui._build(
                    WORKFLOW_ID,
                    recovered_agent,
                    _system_panel(
                        status="COMPLETED",
                        phase="completed",
                        calls=2,
                    ),
                ),
                output_dir / "07-durable-recovered.html",
                title="Durable demo — recovered to one refund",
            )
    finally:
        tui._worker_alive = original_worker_alive
        if original_state_dir is None:
            os.environ.pop("DEMO_STATE_DIR", None)
        else:
            os.environ["DEMO_STATE_DIR"] = original_state_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".demo-media/frames"),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _render_naive_frames(args.output_dir)
    _render_durable_frames(args.output_dir)
    print(f"rendered 7 frames to {args.output_dir}")


if __name__ == "__main__":
    main()
