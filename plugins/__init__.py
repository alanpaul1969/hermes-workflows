"""
hermes-workflow plugin — declarative multi-agent workflow orchestration.

Translates Claude Code Workflow's idea into Hermes: YAML-defined workflows
that execute via delegate_task + skills + terminal, with automatic dependency
resolution and parallel execution waves.

Commands:
  hermes workflow run <file>    Execute a workflow YAML
  hermes workflow list          List all workflows
  hermes workflow show <file>   Show execution plan
  hermes workflow validate <file>  Validate YAML
  hermes workflow create <name> Create from template
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """Register CLI commands AND slash command with the Hermes plugin system."""
    from plugins.workflow.cli import handle_workflow as _handle_workflow
    from plugins.workflow.cli import register_cli as _register_workflow_cli
    from plugins.workflow.cli import handle_workflow_slash

    ctx.register_cli_command(
        name="workflow",
        help="Multi-agent workflow orchestration (YAML-defined pipelines)",
        setup_fn=_register_workflow_cli,
        handler_fn=_handle_workflow,
        description=(
            "Define and execute multi-agent workflows using YAML. "
            "Workflows orchestrate delegate_task subagents in waves, "
            "with automatic dependency resolution and parallel execution.\n\n"
            "Quick start:\n"
            "  hermes workflow create audit    # Create a new workflow\n"
            "  hermes workflow run audit.yaml  # Execute it\n"
            "  hermes workflow list            # List all workflows"
        ),
    )

    # Register /workflow as an in-session slash command (CLI + Telegram)
    ctx.register_command(
        name="workflow",
        handler=handle_workflow_slash,
        description="Run/list/show/validate multi-agent workflows defined in YAML",
        args_hint="run <name> | list | show <name> | validate <name>",
    )

    logger.info("workflow plugin registered (hermes workflow ... + /workflow)")
