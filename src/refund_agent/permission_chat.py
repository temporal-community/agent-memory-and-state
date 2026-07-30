"""Alternative demo: where a push permission lives (authorization state).

The same fact, "you may push to my repo," behaves differently depending on
whether it lives in context, in memory, or in authorization state. Authorization
state answers "may this agent act," and its system of record is the auth system
(an OAuth token, a policy engine, a grants table), not the durable-execution
platform. This is the authorization companion to the execution-state demos: the
same memory-and-state layers, a different system of record. The push is simulated
so nothing touches GitHub, and the agent logic is a plain rule so the layers stay
crisp.

Two views:
  permission-chat            a plain REPL, dependency free, colors on a terminal
  permission-chat --panes    a two-pane view (needs the tui extra): the layers
                             and a live CAN PUSH answer on the left, the chat on
                             the right

Presenter commands (either view):
  :new           fresh session: clear the chat and this session's context
  :remember on   turn the memory layer on (facts persist across sessions)
  :remember off  turn the memory layer off
  :state on      record the authorization in the auth system (authoritative)
  :state off     stop recording in the auth system
  :authorize     set the authorization active (allowed) in the real world
  :revoke        revoke push access in the real world (out of band)
  :reset         clear the chat and all layers, start over
  :layers        print the layers now (plain view only)
  :help          show the commands
  :quit          exit
"""

from __future__ import annotations

import argparse
import sys

# Color only when writing to a real terminal, so piped output stays clean.
_COLOR = sys.stdout.isatty()

_CODES = {
    "bold": "1",
    "dim": "2",
    "context": "33",  # yellow, volatile
    "memory": "34",  # blue, a recollection
    "state": "32",  # green, authoritative
    "danger": "31",  # red
}


def paint(text: str, name: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{_CODES[name]}m{text}\033[0m"


class World:
    """Everything the little agent can draw on, split by layer."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.context_grant = False  # permission seen this session (volatile)
        self.memory_enabled = False
        self.memory_grant = False  # permission remembered across sessions
        self.state_enabled = False
        self.state_status = "none"  # none | active | revoked (the real world)

    def new_session(self) -> None:
        # CONTEXT is volatile: a fresh session starts with an empty window.
        self.context_grant = False


def decide_push(world: World) -> tuple[bool, str, bool, str]:
    """Return (will_push, source, danger, note). A plain, manufactured rule."""

    # The auth system, when tracked, is the authority and overrides recollection.
    if world.state_enabled:
        if world.state_status == "active":
            return True, "AUTH STATE", False, "authorization on record is active"
        if world.state_status == "revoked":
            return False, "AUTH STATE", False, "authorization on record is revoked"
        return False, "AUTH STATE", False, "no authorization on record"
    # MEMORY persists across sessions, but it is only a recollection.
    if world.memory_enabled and world.memory_grant:
        danger = world.state_status == "revoked"
        if danger:
            note = (
                "access was revoked in the real world; memory is a recollection, "
                "not a control"
            )
        else:
            note = "recalled from memory"
        return True, "MEMORY", danger, note
    # CONTEXT is the only other place the grant could be, and only this session.
    if world.context_grant:
        return True, "CONTEXT", False, "grant is in this session's window only"
    return False, "NONE", False, "no grant the agent can act on"


def handle_grant(world: World) -> str:
    world.context_grant = True
    tail = ""
    if world.memory_enabled:
        world.memory_grant = True
        tail = " I will remember that."
    if world.state_enabled and not world.state_status == "revoked":
        world.state_status = "active"
    will, _source, _danger, _note = decide_push(world)
    if will:
        return f"Understood. I can push to your repo.{tail}"
    # The auth system is authoritative and still refuses (for example revoked).
    return "Noted, but the auth system is authoritative and still says I cannot push."


def handle_push(world: World) -> str:
    will, source, danger, note = decide_push(world)
    if not will:
        return f"I do not have permission to push. ({note})"
    line = f"Pushing to your repo... done (simulated). [used {source}]"
    if danger:
        line += f"  WARNING: {note}"
    return line


def handle_message(line: str, world: World) -> str:
    low = line.lower()
    grant_words = ("can push", "may push", "permission", "allow", "grant")
    if any(word in low for word in grant_words):
        return handle_grant(world)
    if "push" in low:
        return handle_push(world)
    return "Okay."


def apply_command(line: str, world: World) -> tuple[bool, str]:
    """Apply a presenter command. Return (keep_going, note_for_transcript)."""

    cmd = line.lower()
    if cmd in (":quit", ":q", ":exit"):
        return False, ""
    if cmd == ":new":
        world.new_session()
        return True, "new session, context cleared"
    if cmd == ":remember on":
        world.memory_enabled = True
        return True, "memory layer on"
    if cmd == ":remember off":
        world.memory_enabled = False
        return True, "memory layer off"
    if cmd == ":state on":
        world.state_enabled = True
        if world.state_status == "none" and (world.context_grant or world.memory_grant):
            world.state_status = "active"
        return True, "authorization now recorded in the auth system (AUTH STATE)"
    if cmd == ":revoke":
        world.state_status = "revoked"
        return True, "push access revoked in the real world (out of band)"
    if cmd == ":authorize":
        world.state_status = "active"
        return True, "push access authorized in the real world"
    if cmd == ":state off":
        world.state_enabled = False
        return True, "state tracking off"
    if cmd == ":reset":
        world.reset()
        return True, "reset to a clean slate"
    if cmd == ":layers":
        return True, ""
    if cmd == ":help":
        return True, (
            "say 'you can push' to grant, 'push' to act; then :new, "
            ":remember on/off, :state on/off, :authorize, :revoke, :reset, :quit"
        )
    return True, "unknown command, :help for the list"


def _layer_lines(world: World) -> tuple[str, str, str, str]:
    """The four lines shared by both views: context, memory, state, can-push."""

    context = "sees push access" if world.context_grant else "empty"
    if not world.memory_enabled:
        memory = "off"
    elif world.memory_grant:
        memory = "recalls push access (a recollection)"
    else:
        memory = "on, nothing recalled"
    if not world.state_enabled:
        state = "off"
    elif world.state_status == "revoked":
        state = "authorized to push: NO (grant#1 revoked)"
    elif world.state_status == "active":
        state = "authorized to push: YES (grant#1 active)"
    else:
        state = "authorized to push: NO (no grant on record)"
    will, source, danger, note = decide_push(world)
    if will and danger:
        can = f"YES via {source}, but {note}"
    elif will:
        can = f"YES via {source}"
    else:
        can = "NO"
    return context, memory, state, can


# ---------------------------------------------------------------------------
# Plain REPL view.
# ---------------------------------------------------------------------------


def render_layers(world: World) -> None:
    context, memory, state, can = _layer_lines(world)
    state_style = "danger" if state.startswith("authorized to push: NO") else "state"
    can_style = "danger" if can == "NO" or "but" in can else "state"
    print(f"  {paint('CONTEXT', 'context')} this session    {context}")
    print(f"  {paint('MEMORY', 'memory')}  across sessions  {memory}")
    print(f"  {paint('AUTH STATE', 'state')} authoritative {paint(state, state_style)}")
    print(f"  {paint('CAN PUSH NOW', 'bold')}     {paint(can, can_style)}")


def run_plain() -> None:
    world = World()
    print(paint("GitHub push permission", "bold"))
    print(
        paint("CONTEXT", "context")
        + " this turn   "
        + paint("MEMORY", "memory")
        + " across turns   "
        + paint("AUTH STATE", "state")
        + " authoritative"
    )
    print(paint("type :help for presenter commands", "dim"))
    print()
    while True:
        try:
            line = input(paint("you>", "bold") + " ")
        except EOFError:
            break
        if not _COLOR:
            print(line)
        line = line.strip()
        if not line:
            continue
        if line.startswith(":"):
            keep, note = apply_command(line, world)
            if not keep:
                break
            if line.lower() == ":layers":
                render_layers(world)
            elif note:
                print(paint("-- " + note + " --", "dim"))
            continue
        print(paint("agent>", "dim") + " " + handle_message(line, world))
        render_layers(world)


# ---------------------------------------------------------------------------
# Two-pane view (rich).
# ---------------------------------------------------------------------------


def _panes_frame(world: World, transcript: list[tuple[str, str]]):
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text

    context, memory, state, can = _layer_lines(world)
    layers = Text()
    layers.append("CONTEXT ", style="bold yellow")
    layers.append("this session\n")
    layers.append(f"  {context}\n\n")
    layers.append("MEMORY ", style="bold blue")
    layers.append("across sessions\n")
    layers.append(f"  {memory}\n\n")
    layers.append("AUTH STATE ", style="bold green")
    layers.append("authoritative\n")
    state_style = "red" if state.startswith("authorized to push: NO") else "green"
    layers.append(f"  {state}\n\n", style="" if state == "off" else state_style)
    layers.append("CAN PUSH NOW\n", style="bold")
    can_style = "red" if can == "NO" or "but" in can else "green"
    layers.append(f"  {can}\n", style=can_style)

    chat = Text()
    for who, message in transcript[-16:]:
        if who == "you":
            chat.append("you>  ", style="bold")
            chat.append(message + "\n")
        elif who == "agent":
            chat.append("agent> ", style="dim")
            chat.append(message + "\n")
        else:
            chat.append("  (" + message + ")\n", style="dim")

    layout = Layout()
    layout.split_column(
        Layout(name="head", size=3),
        Layout(name="body"),
        Layout(name="foot", size=3),
    )
    layout["head"].update(
        Panel(
            "Alternative Demo: GitHub Push Permission",
            border_style="cyan",
        )
    )
    layout["body"].split_row(
        Layout(Panel(layers, title="THE LAYERS", border_style="cyan"), name="layers"),
        Layout(Panel(chat, title="THE CHAT", border_style="white"), name="chat"),
    )
    layout["foot"].update(
        Panel(
            "say 'you can push' to grant, 'push' to act    "
            ":remember on/off  :state on/off  :authorize  :revoke  :reset  :quit",
            border_style="dim",
        )
    )
    return layout


def run_panes() -> None:
    try:
        from rich.console import Console
    except ModuleNotFoundError:
        print("The --panes view needs rich. Install it with: uv sync --extra tui")
        return
    console = Console()
    world = World()
    transcript: list[tuple[str, str]] = []
    while True:
        console.clear()
        console.print(_panes_frame(world, transcript))
        try:
            line = input("you>  ").strip()
        except EOFError:
            break
        if not line:
            continue
        if line.startswith(":"):
            keep, note = apply_command(line, world)
            if not keep:
                break
            if line.lower() in (":reset", ":new"):
                # Reset and new both clear the chat (a fresh window), not just
                # the layers.
                transcript.clear()
            if note:
                transcript.append(("system", note))
            continue
        transcript.append(("you", line))
        transcript.append(("agent", handle_message(line, world)))


def main() -> None:
    parser = argparse.ArgumentParser(prog="permission-chat")
    parser.add_argument(
        "--panes",
        action="store_true",
        help="two-pane view: layers and can-push on the left, chat on the right",
    )
    args = parser.parse_args()
    try:
        if args.panes:
            run_panes()
        else:
            run_plain()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
