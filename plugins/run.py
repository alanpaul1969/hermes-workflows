#!/usr/bin/env python3
"""
Standalone workflow runner for Hermes workflows.

Usage:
  python3 ~/.hermes/plugins/workflow/run.py audit.yaml          # Generate prompt
  python3 ~/.hermes/plugins/workflow/run.py audit.yaml --run     # Execute via hermes
  python3 ~/.hermes/plugins/workflow/run.py --list               # List workflows
  python3 ~/.hermes/plugins/workflow/run.py --create my-workflow # Create template
"""

import os
import subprocess
import sys

# Add hermes-agent AND workflow plugin to path
HERMES_HOME = os.path.expanduser("~/.hermes/hermes-agent")
PLUGINS_HOME = os.path.expanduser("~/.hermes")
sys.path.insert(0, HERMES_HOME)
sys.path.insert(0, PLUGINS_HOME)

from plugins.workflow.engine import (
    build_workflow_prompt,
    list_workflows,
    load_workflow,
    resolve_execution_order,
)

WORKFLOWS_DIR = os.path.expanduser("~/.hermes/workflows")


def _find_workflow(name: str) -> str:
    """Find a workflow file by name (with or without .yaml extension)."""
    if os.path.exists(name):
        return name
    
    wdir = WORKFLOWS_DIR
    candidates = [
        os.path.join(wdir, name),
        os.path.join(wdir, f"{name}.yaml"),
        os.path.join(wdir, f"{name}.yml"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    
    print(f"Error: workflow '{name}' not found in {wdir}/")
    print("Available workflows:")
    for w in list_workflows():
        print(f"  {w['filename']:<30} {w['name']}")
    sys.exit(1)


def cmd_run(args):
    """Execute a workflow."""
    filepath = _find_workflow(args[0]) if args else None
    
    if not filepath:
        print("Usage: run.py <workflow.yaml> [--run]")
        print("       run.py --list")
        print("       run.py --create <name>")
        sys.exit(1)
    
    workflow = load_workflow(filepath)
    prompt = build_workflow_prompt(workflow)
    
    if "--run" in args:
        print(f"🚀 Executing: {workflow['name']}")
        print(f"   Steps: {len(workflow.get('steps', []))}")
        waves = resolve_execution_order(workflow.get("steps", []))
        print(f"   Waves: {len(waves)}")
        print()
        
        try:
            subprocess.run(["hermes", "-p", prompt])
        except FileNotFoundError:
            print("Error: 'hermes' not found. Copy the prompt below:")
            print()
            print(prompt)
    else:
        print(f"Workflow: {workflow['name']}")
        if workflow.get("description"):
            print(f"  {workflow['description']}")
        print()
        waves = resolve_execution_order(workflow.get("steps", []))
        for i, wave in enumerate(waves):
            parallel = "⚡ parallel" if len(wave) > 1 else ""
            print(f"Wave {i+1} {parallel}:")
            for sid in wave:
                step = next((s for s in workflow["steps"] if s["id"] == sid), {})
                stype = step.get("type", "subagent")
                name = step.get("name", sid)
                print(f"  [{stype}] {sid}: {name}")
            print()
        
        print(f"Generated prompt ({len(prompt)} chars)")
        print()
        print("To execute: python3 ~/.hermes/plugins/workflow/run.py {filepath} --run")
        print("Or copy the prompt into Hermes manually.")


def cmd_list():
    """List all workflows."""
    workflows = list_workflows()
    
    if not workflows:
        print(f"No workflows found in {WORKFLOWS_DIR}/")
        return
    
    print(f"{'WORKFLOW':<30} {'STEPS':<8} {'FILE'}")
    print("-" * 70)
    for w in workflows:
        print(f"{w['name']:<30} {w['steps']:<8} {w['filename']}")
    print(f"\n{len(workflows)} workflow(s) in {WORKFLOWS_DIR}/")


def cmd_create(args):
    """Create a new workflow from template."""
    if not args:
        print("Usage: run.py --create <name> [--description <text>]")
        sys.exit(1)
    
    name = args[0]
    description = ""
    
    if "--description" in args:
        idx = args.index("--description")
        if idx + 1 < len(args):
            description = args[idx + 1]
    
    safe_name = name.lower().replace(" ", "-").replace("/", "-")
    filename = f"{safe_name}.yaml"
    filepath = os.path.join(WORKFLOWS_DIR, filename)
    
    os.makedirs(WORKFLOWS_DIR, exist_ok=True)
    
    if os.path.exists(filepath):
        print(f"Error: {filepath} already exists")
        sys.exit(1)
    
    template = f"""# {name}
name: "{name}"
description: "{description or f'Workflow: {name}'}"
version: "1.0"

steps:
  # Step 1: Inspect (subagent)
  - id: inspect
    name: "Inspect codebase"
    type: subagent
    context: |
      Inspect the codebase. Count files, LOC, languages, dependencies.
      Return a structured report.
    toolsets: [terminal, file]

  # Step 2: Review (skill) — uncomment when ready
  # - id: review
  #   name: "Code quality review"
  #   type: skill
  #   skill: requesting-code-review
  #   depends_on: inspect
  #   input:
  #     files: $inspect.output

  # Step 3: Report (subagent) — uncomment when ready
  # - id: report
  #   name: "Compile final report"
  #   type: subagent
  #   depends_on: [inspect, review]
  #   context: |
  #     Compile a final report using results from previous steps.
  #   toolsets: [terminal, file]

# Tips:
# - type: subagent | skill | command
# - depends_on: step_id or [step_id1, step_id2]
# - Steps without depends_on run in parallel in the first wave
# - Use $step-id.output to reference a previous step's output
"""
    
    with open(filepath, "w") as f:
        f.write(template)
    
    print(f"✅ Created: {filepath}")
    print(f"   Run: python3 ~/.hermes/plugins/workflow/run.py {filename}")


def main():
    if len(sys.argv) < 2:
        print("Hermes Workflow Runner")
        print()
        cmd_list()
        print()
        print("Usage:")
        print("  run.py <workflow.yaml>         Show execution plan")
        print("  run.py <workflow.yaml> --run   Execute workflow")
        print("  run.py --list                  List all workflows")
        print("  run.py --create <name>         Create a new workflow")
        return
    
    if sys.argv[1] == "--list":
        cmd_list()
    elif sys.argv[1] == "--create":
        cmd_create(sys.argv[2:])
    else:
        cmd_run(sys.argv[1:])


if __name__ == "__main__":
    main()
