"""Process settings used outside deterministic Workflow code."""

import hashlib
import math
import os
from pathlib import Path


def load_env_file() -> None:
    """Load KEY=VALUE lines from .env into the environment if not already set.

    Kept dependency free on purpose. Values already in the environment win, so an
    explicit export always overrides the file. Call this from process entry
    points (the Worker and the CLI), never from deterministic Workflow code.
    """

    path = Path(os.getenv("DOTENV_PATH", ".env"))
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def temporal_address() -> str:
    return os.getenv("TEMPORAL_ADDRESS", "localhost:7233")


def temporal_namespace() -> str:
    return os.getenv("TEMPORAL_NAMESPACE", "default")


def task_queue() -> str:
    return os.getenv("TEMPORAL_TASK_QUEUE", "refund-demo")


def state_dir() -> Path:
    return Path(os.getenv("DEMO_STATE_DIR", ".demo-state"))


def worker_pid_file() -> Path:
    return state_dir() / "worker.pid"


def agent_view_path(workflow_id: str) -> Path:
    """Return a filesystem-safe path for one Workflow's presentation mirror."""

    digest = hashlib.sha256(workflow_id.encode("utf-8")).hexdigest()[:24]
    return state_dir() / f"agent-view-{digest}.json"


def effect_restart_window_seconds() -> float:
    raw_value = os.getenv("EFFECT_RESTART_WINDOW_SECONDS", "0")
    try:
        value = float(raw_value)
    except ValueError as error:
        raise RuntimeError(
            "EFFECT_RESTART_WINDOW_SECONDS must be a finite number"
        ) from error
    if not math.isfinite(value) or value < 0:
        raise RuntimeError(
            "EFFECT_RESTART_WINDOW_SECONDS must be a finite number, zero or greater"
        )
    return value


def validate_stripe_key(key: str | None, *, required: bool) -> str | None:
    """Accept test credentials only and reject live credentials loudly."""

    if not key:
        if required:
            raise RuntimeError("STRIPE_API_KEY is required for a real refund")
        return None
    if key.startswith(("sk_live_", "rk_live_")):
        raise RuntimeError("A live Stripe key was detected and has been rejected")
    if not key.startswith(("sk_test_", "rk_test_")):
        raise RuntimeError("STRIPE_API_KEY must be a Stripe test mode key")
    return key
