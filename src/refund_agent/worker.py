"""Run the Temporal Worker that hosts the Workflow and Activities."""

import asyncio
import concurrent.futures
import logging
import os

from temporalio import workflow
from temporalio.client import Client
from temporalio.worker import Worker

from refund_agent.activities import (
    agent_step,
    check_refund_policy,
    issue_refund,
    lookup_customer_history,
    lookup_order,
    show_empty_agent_view,
)
from refund_agent.settings import (
    load_env_file,
    task_queue,
    temporal_address,
    temporal_namespace,
    validate_stripe_key,
    worker_pid_file,
)
from refund_agent.workflow import RefundWorkflow


async def run_worker() -> None:
    load_env_file()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Stage legibility: keep the EXECUTION STATE lines clean by not appending
    # the workflow info dict (run id, attempt, task queue) to every log message.
    workflow.logger.workflow_info_on_message = False
    validate_stripe_key(os.getenv("STRIPE_API_KEY"), required=False)

    pid_path = worker_pid_file()
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    show_empty_agent_view()
    print(
        "EXECUTION STATE | Worker connected to "
        f"{temporal_address()} on task queue {task_queue()}",
        flush=True,
    )

    client = await Client.connect(
        temporal_address(),
        namespace=temporal_namespace(),
    )
    try:
        # The Activities use blocking SDKs, so the Temporal skill recommends
        # synchronous Activities with an explicit thread executor.
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            worker = Worker(
                client,
                task_queue=task_queue(),
                workflows=[RefundWorkflow],
                activities=[
                    agent_step,
                    lookup_order,
                    lookup_customer_history,
                    check_refund_policy,
                    issue_refund,
                ],
                activity_executor=executor,
            )
            await worker.run()
    finally:
        if pid_path.exists():
            recorded_pid = pid_path.read_text(encoding="utf-8").strip()
            if recorded_pid == str(os.getpid()):
                pid_path.unlink()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        print("EXECUTION STATE | Worker stopped", flush=True)


if __name__ == "__main__":
    main()
