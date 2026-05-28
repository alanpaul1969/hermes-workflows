"""
CLI commands for the workflow plugin.

Wires ``hermes workflow <subcommand>``:
  run <file>    — Execute a workflow YAML file
  list          — List all workflow YAML files in ~/.hermes/workflows/
  create        — Interactive workflow creation wizard (TODO)
  validate <file> — Validate a workflow YAML file without running
  show <file>   — Print the execution plan without running
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from plugins.workflow.engine import (
    build_workflow_prompt,
    classify_task,
    execute_workflow,
    get_available_templates,
    instantiate_template,
    load_template,
    list_workflows,
    load_workflow,
    resolve_execution_order,
)


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def register_cli(subparser: argparse.ArgumentParser) -> None:
    """Build the ``hermes workflow`` argparse tree."""
    subs = subparser.add_subparsers(dest="workflow_command")

    # --- run ---
    run_p = subs.add_parser("run", help="Execute a workflow YAML file")
    run_p.add_argument("file", help="Path to workflow YAML file")
    run_p.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Print the generated prompt without executing",
    )
    run_p.add_argument(
        "--model", "-m",
        help="Model to use for execution (e.g. 'deepseek-v4-pro')",
    )
    run_p.add_argument(
        "--native", action="store_true",
        help="Use native execution (run command/reasonix/opencode steps locally)",
    )

    # --- list ---
    subs.add_parser("list", help="List all workflow YAML files")

    # --- stats ---
    subs.add_parser("stats", help="Show workflow run analytics")

    # --- show ---
    show_p = subs.add_parser("show", help="Show execution plan for a workflow")
    show_p.add_argument("file", help="Path to workflow YAML file")

    # --- validate ---
    val_p = subs.add_parser("validate", help="Validate a workflow YAML file")
    val_p.add_argument("file", help="Path to workflow YAML file")

    # --- create ---
    create_p = subs.add_parser("create", help="Create a new workflow from a template")
    create_p.add_argument("name", help="Workflow name (used as filename)")
    create_p.add_argument(
        "--description", "-d", default="",
        help="Workflow description",
    )
    create_p.add_argument("--from", "-f", dest="template", help="Template name (e.g. backend-bug-fix)")
    create_p.add_argument("--set", "-s", action="append", dest="vars", help="Set variable: key=value")

    # --- webhook ---
    webhook_p = subs.add_parser("webhook", help="Start GitHub webhook server for triggering workflows")
    webhook_p.add_argument(
        "--port", "-p", type=int, default=9001,
        help="Port to listen on (default: 9001)",
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def handle_workflow(args: argparse.Namespace) -> int:
    """Dispatch to the appropriate subcommand handler."""
    command = getattr(args, "workflow_command", None)
    
    if command == "run":
        return _cmd_run(args)
    elif command == "list":
        return _cmd_list(args)
    elif command == "stats":
        return _cmd_stats(args)
    elif command == "show":
        return _cmd_show(args)
    elif command == "validate":
        return _cmd_validate(args)
    elif command == "create":
        return _cmd_create(args)
    elif command == "webhook":
        return _cmd_webhook(args)
    else:
        print("Usage: hermes workflow {run|list|show|validate|create|webhook} ...")
        print("Try 'hermes workflow run --help' for more information.")
        return 1


def _resolve_workflow_path(name: str) -> str:
    """Resolve a workflow name to a full path.
    
    Checks in order:
    1. Exact path (with expanduser)
    2. ~/.hermes/workflows/<name>
    3. ~/.hermes/workflows/<name>.yaml
    """
    path = os.path.expanduser(name)
    if os.path.exists(path):
        return path
    
    wdir = Path(os.path.expanduser("~/.hermes/workflows"))
    candidates = [
        wdir / name,
        wdir / f"{name}.yaml",
        wdir / f"{name}.yml",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    
    return path  # Return original so error message shows what was tried


def _record_run(workflow: dict, local_steps: int, deferred_steps: int,
                start_time: float, success: bool) -> None:
    """Append a run record to .run_history.jsonl for analytics (P10)."""
    import json
    import time as _time
    from datetime import datetime, timezone

    history_file = os.path.expanduser("~/.hermes/workflows/.run_history.jsonl")
    os.makedirs(os.path.dirname(history_file), exist_ok=True)

    elapsed = round(_time.time() - start_time, 1)
    record = {
        "workflow": workflow.get("name", "?"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "success": success,
        "local_steps": local_steps,
        "deferred_steps": deferred_steps,
        "elapsed_sec": elapsed,
    }
    with open(history_file, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _cmd_run(args: argparse.Namespace) -> int:
    """Execute a workflow."""
    filepath = _resolve_workflow_path(args.file)
    
    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}")
        return 1
    
    try:
        workflow = load_workflow(filepath)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # Track run start time
    import time as _time
    start_time = _time.time()

    # Try native execution first (auto or --native flag)
    native = getattr(args, "native", False)
    use_native = native

    if native:
        print(f"⚡ Native mode: executing locally...")
        result = execute_workflow(workflow)
        local_count = len(result["local_outputs"])
        deferred_count = len(result.get("deferred_steps", []))
        print(f"   Local steps: {local_count} completed")
        print(f"   Deferred steps: {deferred_count}")

        if result["prompt"]:
            # Has deferred subagent/skill steps — feed to Hermes
            tmpfile = f"/tmp/hermes_workflow_{os.getpid()}.txt"
            with open(tmpfile, "w") as f:
                f.write(result["prompt"])
            print(f"   Feeding deferred steps to Hermes...")
            cmd = ["hermes"]
            if args.model:
                cmd.extend(["--model", args.model])
            cmd.extend(["-p", result["prompt"]])
            sub_result = subprocess.run(cmd, text=True)
            # Track deferred execution result
            _record_run(
                workflow, local_count, deferred_count,
                start_time, success=(sub_result.returncode == 0)
            )
            return sub_result.returncode
        else:
            # All done natively
            print("   ✅ All steps executed natively!")
            _record_run(workflow, local_count, 0, start_time, success=True)
            return 0

    # Standard prompt-based execution
    prompt = build_workflow_prompt(workflow)
    
    if args.dry_run:
        print("=" * 60)
        print(f"DRY RUN — Generated prompt for workflow: {workflow['name']}")
        print("=" * 60)
        print()
        print(prompt)
        print()
        print("=" * 60)
        print("To execute, remove --dry-run flag.")
        return 0
    
    # Write prompt to temp file and pipe into hermes
    tmpfile = f"/tmp/hermes_workflow_{os.getpid()}.txt"
    with open(tmpfile, "w") as f:
        f.write(prompt)
    
    print(f"🚀 Executing workflow: {workflow['name']}")
    print(f"   Steps: {len(workflow.get('steps', []))}")
    print(f"   Prompt saved to: {tmpfile}")
    print()
    print("Starting Hermes with workflow prompt...")
    print("(You can also copy the prompt from the temp file)")
    print()
    
    # Build hermes command
    cmd = ["hermes"]
    if args.model:
        cmd.extend(["--model", args.model])
    cmd.extend(["-p", prompt])
    
    try:
        result = subprocess.run(cmd, text=True)
        return result.returncode
    except FileNotFoundError:
        print("Error: 'hermes' command not found. Is Hermes installed?")
        print(f"\nYou can manually run the workflow by copying the prompt from:")
        print(f"  {tmpfile}")
        return 1
    except KeyboardInterrupt:
        print("\nWorkflow cancelled.")
        return 130
    finally:
        # Keep the temp file for 24h in case user wants to reuse
        pass


def _cmd_list(args: argparse.Namespace) -> int:
    """List all workflow files."""
    workflows = list_workflows()
    
    if not workflows:
        print("No workflows found in ~/.hermes/workflows/")
        print("\nCreate one with: hermes workflow create <name>")
        return 0
    
    print(f"{'WORKFLOW':<30} {'STEPS':<8} {'FILE'}")
    print("-" * 70)
    for w in workflows:
        print(f"{w['name']:<30} {w['steps']:<8} {w['filename']}")
    
    print(f"\n{len(workflows)} workflow(s) found.")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    """Show workflow run analytics from .run_history.jsonl."""
    import json
    from collections import Counter
    from datetime import datetime, timezone, timedelta

    history_file = os.path.expanduser("~/.hermes/workflows/.run_history.jsonl")

    if not os.path.exists(history_file):
        print("No workflow runs recorded yet.")
        print("Run a workflow to start tracking: hermes workflow run <name> --native")
        return 0

    runs = []
    with open(history_file) as f:
        for line in f:
            try:
                runs.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                continue

    if not runs:
        print("No valid run records found.")
        return 0

    # Counts
    total = len(runs)
    successes = sum(1 for r in runs if r.get("success"))
    workflow_counts = Counter(r["workflow"] for r in runs)

    # Time range
    timestamps = [r["timestamp"] for r in runs if "timestamp" in r]
    first_ts = timestamps[0][:10] if timestamps else "?"
    last_ts = timestamps[-1][:10] if timestamps else "?"

    print(f"📊 **Workflow Analytics**")
    print(f"   {first_ts} → {last_ts}  |  {total} runs, {successes} succeeded ({successes*100//total if total else 0}%)")
    print()
    print(f"{'Workflow':<30} {'Runs':<8} {'Success %'}")
    print("-" * 50)
    for wf, count in workflow_counts.most_common():
        wf_runs = [r for r in runs if r["workflow"] == wf]
        wf_ok = sum(1 for r in wf_runs if r.get("success"))
        pct = f"{wf_ok*100//count}%" if count else "0%"
        print(f"{wf:<30} {count:<8} {pct}")
    print()

    # Recent runs
    print("Recent runs:")
    for r in runs[-5:]:
        ts = r.get("timestamp", "?")[:19]
        wf = r.get("workflow", "?")
        ok = "✅" if r.get("success") else "⚠️"
        steps = f"local={r.get('local_steps',0)} def={r.get('deferred_steps',0)}"
        print(f"  {ts}  {ok}  {wf}  ({steps})")

    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    """Show execution plan for a workflow."""
    filepath = _resolve_workflow_path(args.file)
    
    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}")
        return 1
    
    try:
        workflow = load_workflow(filepath)
    except ValueError as e:
        print(f"Error: {e}")
        return 1
    
    waves = resolve_execution_order(workflow.get("steps", []))
    
    print(f"Workflow: {workflow['name']}")
    if workflow.get("description"):
        print(f"  {workflow['description']}")
    print()
    
    for i, wave in enumerate(waves):
        parallel = "⚡ parallel" if len(wave) > 1 else ""
        print(f"Wave {i+1} {parallel}:")
        for sid in wave:
            step = next((s for s in workflow["steps"] if s["id"] == sid), {})
            stype = step.get("type", "subagent")
            name = step.get("name", sid)
            deps = step.get("depends_on", [])
            if isinstance(deps, str):
                deps = [deps]
            dep_str = f" ← {' '.join(deps)}" if deps else ""
            print(f"  [{stype}] {sid}: {name}{dep_str}")
        print()
    
    # Print full prompt
    prompt = build_workflow_prompt(workflow)
    print(f"Generated prompt ({len(prompt)} chars)")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate a workflow YAML file."""
    filepath = _resolve_workflow_path(args.file)
    
    if not os.path.exists(filepath):
        print(f"Error: file not found: {filepath}")
        return 1
    
    try:
        workflow = load_workflow(filepath)
        print(f"✅ Valid: {workflow['name']}")
        print(f"   Steps: {len(workflow.get('steps', []))}")
        waves = resolve_execution_order(workflow.get("steps", []))
        print(f"   Waves: {len(waves)}")
        return 0
    except ValueError as e:
        print(f"❌ Invalid: {e}")
        return 1
    except Exception as e:
        print(f"❌ Parse error: {e}")
        return 1


def _cmd_create(args: argparse.Namespace) -> int:
    """Create a new workflow from template."""
    name = args.name
    description = args.description or f"Workflow: {name}"
    
    # Sanitize filename
    safe_name = name.lower().replace(" ", "-").replace("/", "-")
    filename = f"{safe_name}.yaml"
    
    workflows_dir = Path(os.path.expanduser("~/.hermes/workflows"))
    workflows_dir.mkdir(parents=True, exist_ok=True)
    
    filepath = workflows_dir / filename
    
    if filepath.exists():
        print(f"Error: {filepath} already exists")
        return 1
    
    # Parse --set variables
    vars_dict = {}
    if args.vars:
        for var_arg in args.vars:
            if "=" not in var_arg:
                print(f"Warning: skipping invalid variable '{var_arg}' (expected key=value)")
                continue
            k, v = var_arg.split("=", 1)
            vars_dict[k] = v
    
    if args.template:
        # Load template and instantiate
        try:
            template_data = load_template(args.template)
        except FileNotFoundError as e:
            print(f"Error: {e}")
            return 1
        
        variables = dict(vars_dict)
        if "TASK_DESCRIPTION" not in variables:
            variables["TASK_DESCRIPTION"] = description
        
        generated = instantiate_template(template_data, variables)
        filepath.write_text(generated)
        
        print(f"✅ Created: {filepath} (from template '{args.template}')")
    else:
        # Original behavior — default template
        default_template = f"""# {name}
name: "{name}"
description: "{description}"
version: "1.0"

# Optional: define variables used across steps
# variables:
#   repo_path: "~/project"

steps:
  # Step 1: Inspect codebase (subagent)
  - id: inspect
    name: "Inspect codebase"
    type: subagent
    context: |
      Inspect the codebase at [path].
      Count files, LOC, languages, dependencies.
      Return a structured report.
    toolsets: [terminal, file]

  # Step 2: Review quality (skill)
  # - id: review
  #   name: "Code quality review"
  #   type: skill
  #   skill: requesting-code-review
  #   depends_on: inspect
  #   input:
  #     files: $inspect.output

  # Step 3: Generate report (subagent)
  # - id: report
  #   name: "Compile final report"
  #   type: subagent
  #   depends_on: [inspect, review]
  #   context: |
  #     Compile a final report from:
  #     - Inspection: $inspect.output
  #     - Review: $review.output
  #   toolsets: [terminal, file]

# Tips:
# - type: subagent | skill | command
# - depends_on: step_id or [step_id1, step_id2]
# - Steps without depends_on run in the first wave (can be parallel)
# - Use $variables.xxx to reference global variables
# - Use $step-id.output to reference a previous step's output
"""
        
        filepath.write_text(default_template)
        print(f"✅ Created: {filepath}")
    
    print(f"   Edit this file to define your workflow steps.")
    print(f"   Run with: hermes workflow run {filepath}")
    
    return 0


def _cmd_webhook(args: argparse.Namespace) -> int:
    """Start the GitHub webhook HTTP server."""
    from plugins.workflow.webhook import start_webhook_server

    port = getattr(args, "port", 9001)
    start_webhook_server(port=port)
    return 0


# ---------------------------------------------------------------------------
# Slash command handler for /workflow (CLI + Gateway)
# ---------------------------------------------------------------------------

def handle_workflow_slash(raw_args: str) -> str | None:
    """Handle /workflow slash command from CLI or gateway sessions.
    
    Parses raw_args for subcommands:
      /workflow run <name>     — Execute a workflow via hermes chat -q
      /workflow list           — List all workflows
      /workflow show <name>    — Show execution plan
      /workflow validate <name> — Validate a YAML file
    """
    from plugins.workflow.engine import (
        build_workflow_prompt,
        list_workflows,
        load_workflow,
        resolve_execution_order,
    )
    
    args = raw_args.strip()
    if not args:
        return (
            "**Workflow — multi-agent orchestration**\\n\\n"
            "Usage:\\n"
            "  `/workflow run <name>` — Execute a workflow\\n"
            "  `/workflow list` — List all workflows\\n"
            "  `/workflow show <name>` — Show execution plan\\n"
            "  `/workflow validate <name>` — Validate YAML\\n\\n"
            "Workflows are YAML files in `~/.hermes/workflows/`.\\n"
            "Create new: `hermes workflow create <name>`"
        )
    
    parts = args.split(maxsplit=1)
    subcommand = parts[0].lower()
    sub_args = parts[1] if len(parts) > 1 else ""
    
    # --- list ---
    if subcommand == "list":
        workflows = list_workflows()
        if not workflows:
            return "No workflows found in `~/.hermes/workflows/`.\\nCreate one: `hermes workflow create <name>`"
        
        lines = ["**Workflows**\\n"]
        for w in workflows:
            lines.append(f"• **{w['name']}** — {w['steps']} step(s) (`{w['filename']}`)")
        return "\\n".join(lines)
    
    # --- run / show / validate (need a workflow name) ---
    if not sub_args:
        return f"⚠️ Missing workflow name. Usage: `/workflow {subcommand} <name>`"
    
    # Resolve path
    wdir = Path(os.path.expanduser("~/.hermes/workflows"))
    candidates = [
        wdir / sub_args,
        wdir / f"{sub_args}.yaml",
        wdir / f"{sub_args}.yml",
    ]
    filepath = None
    for c in candidates:
        if c.exists():
            filepath = str(c)
            break
    
    if filepath is None:
        return f"❌ Workflow not found: `{sub_args}`\\nLooked in: `{sub_args}`, `{sub_args}.yaml`, `{sub_args}.yml`"
    
    try:
        workflow = load_workflow(filepath)
    except ValueError as e:
        return f"❌ Invalid workflow: {e}"
    
    # --- show ---
    if subcommand == "show":
        waves = resolve_execution_order(workflow.get("steps", []))
        lines = [
            f"**{workflow['name']}**",
            f"_{workflow.get('description', '')}_",
            "",
        ]
        for i, wave in enumerate(waves):
            parallel = "⚡ parallel" if len(wave) > 1 else ""
            lines.append(f"**Wave {i+1}** {parallel}:")
            for sid in wave:
                step = next((s for s in workflow["steps"] if s["id"] == sid), {})
                stype = step.get("type", "subagent")
                name = step.get("name", sid)
                deps = step.get("depends_on", [])
                if isinstance(deps, str):
                    deps = [deps]
                dep_str = f" ← {' '.join(deps)}" if deps else ""
                lines.append(f"  `[{stype}]` {sid}: {name}{dep_str}")
            lines.append("")
        return "\\n".join(lines)
    
    # --- validate ---
    if subcommand == "validate":
        return f"✅ **{workflow['name']}**\\n   Steps: {len(workflow.get('steps', []))}\\n   Waves: {len(resolve_execution_order(workflow.get('steps', [])))}"
    
    # --- run ---
    if subcommand == "run":
        prompt = build_workflow_prompt(workflow)
        
        # Execute via hermes chat -q (one-shot, non-interactive)
        try:
            result = subprocess.run(
                ["hermes", "chat", "-q", prompt],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode != 0:
                return f"❌ Workflow execution failed (exit {result.returncode}):\\n```\\n{result.stderr[-500:]}\\n```"
            
            # Trim spinner/banner noise from output
            output = result.stdout.strip()
            # Return the last meaningful chunk (skip spinner lines)
            lines_out = [l for l in output.split("\\n") if l.strip() and "⠋" not in l and "⠙" not in l and "⠹" not in l and "⠸" not in l]
            clean = "\\n".join(lines_out[-100:])  # Last 100 meaningful lines
            
            return f"✅ **Workflow complete: {workflow['name']}**\\n\\n{clean}"
        except subprocess.TimeoutExpired:
            return f"⏰ Workflow timed out after 10 minutes: **{workflow['name']}**"
        except FileNotFoundError:
            return "❌ `hermes` command not found. Is Hermes installed?"
    
    return f"❓ Unknown subcommand: `{subcommand}`. Use: `run`, `list`, `show`, `validate`"
