# Shortcuts for the commands in README.md. Each recipe is the raw command the
# README shows beside it; `make -n <target>` prints it without running it.

.PHONY: help setup run run-real failure reset test lint usage

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  make %-9s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Install the project with the dev and tui extras
	uv sync --extra dev --extra tui

run: ## Offline stage run: no keys, no model calls
	uv run refund-demo stage

run-real: ## Stage run against Stripe test mode (needs a test key)
	uv run refund-demo stage --real

failure: ## Kill the Worker while the refund Activity is in flight
	uv run refund-demo stage --simulate-stripe-timeout

reset: ## Refund leftover Stripe test charges; print the manual steps
	@echo "Stripe test mode cleanup. Offline, a missing STRIPE_API_KEY is expected."
	uv run refund-demo cleanup
	@echo ""
	@echo "Nothing was deleted or stopped. To reset further, by hand:"
	@echo "  Running Workflow from an aborted take: uv run refund-demo stop <workflow-id>"
	@echo "  Empty Temporal Web list: Ctrl+C your own temporal server start-dev, then"
	@echo "    start it again. Never restart a server someone else is using."
	@echo "  Local files: stop any dev server using .demo-state/temporal.db, then"
	@echo "    run rm -rf .demo-state (logs, usage logs, ledgers, stage server data)."

test: ## Offline test suite
	uv run --extra dev pytest -q

lint: ## Ruff lint and format check
	uv run --extra dev ruff check .
	uv run --extra dev ruff format --check .

usage: ## Sum model tokens and dollars logged with LOG_MODEL_USAGE=1
	uv run refund-demo usage
