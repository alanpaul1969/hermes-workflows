"""
P7 — GitHub webhook → workflow trigger.

Listens for GitHub webhook events on localhost and triggers
configured Hermes workflows with extracted variables.

Usage (CLI):
  hermes workflow webhook [--port 9001]

Uses Python stdlib only: http.server, json, hmac, hashlib.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import os
import subprocess
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.hermes/workflows/webhook.yaml")
DEFAULT_PORT = 9001

# Default route map (event → workflow)
DEFAULT_ROUTES = {
    "push": {"workflow": "codebase-audit"},
    "pull_request": {"workflow": "pre-commit-review"},
    "issues": {"workflow": "branch-review"},  # triage-like workflow
}

# GitHub event header
GITHUB_EVENT_HEADER = "X-GitHub-Event"
GITHUB_SIGNATURE_HEADER = "X-Hub-Signature-256"


def _load_yaml(path: str) -> dict:
    """Load a YAML config file. Falls back to defaults if not found."""
    try:
        import yaml
    except ImportError:
        return {}

    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    """Load webhook config with sensible defaults."""
    raw = _load_yaml(config_path)

    config: dict = {
        "port": raw.get("port", DEFAULT_PORT),
        "secret": raw.get("secret", ""),
        "routes": {},
    }

    # Merge custom routes over defaults
    merged_routes = dict(DEFAULT_ROUTES)
    for event, route in raw.get("routes", {}).items():
        merged_routes[event] = route

    config["routes"] = merged_routes
    return config


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------

class GitHubWebhookHandler(BaseHTTPRequestHandler):
    """HTTP handler for GitHub webhook events."""

    # Class-level config injected by the server launcher
    config: dict = {}
    _run_counter: int = 0

    def log_message(self, format: str, *args):
        """Suppress default stderr logging — we use our own."""
        pass

    def do_POST(self):
        """Route POST requests."""
        if self.path == "/webhook/github":
            self._handle_github_webhook()
        else:
            self._send_json(404, {"error": "not found", "path": self.path})

    def _send_json(self, status: int, data: dict) -> None:
        """Send a JSON response."""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _verify_signature(self, body: bytes) -> bool:
        """Validate X-Hub-Signature-256 against the configured secret."""
        secret = self.config.get("secret", "")
        if not secret:
            # No secret configured — accept all (dev mode)
            return True

        sig_header = self.headers.get(GITHUB_SIGNATURE_HEADER, "")
        if not sig_header:
            print(f"[webhook] WARNING: missing {GITHUB_SIGNATURE_HEADER} header")
            return False

        # Expected: "sha256=<hex>"
        if not sig_header.startswith("sha256="):
            print(f"[webhook] WARNING: malformed signature header: {sig_header[:20]}")
            return False

        expected = sig_header[7:]  # strip "sha256="

        computed = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, computed):
            print("[webhook] WARNING: signature mismatch")
            return False

        return True

    def _extract_variables(self, event_type: str, payload: dict) -> dict:
        """Extract workflow variables from the GitHub payload."""
        variables: dict = {
            "event_type": event_type,
            "sender": payload.get("sender", {}).get("login", "unknown"),
        }

        repo = payload.get("repository", {})
        variables["repository"] = repo.get("full_name", repo.get("name", "unknown"))

        # Push event
        if event_type == "push":
            head_commit = payload.get("head_commit", {}) or {}
            ref = payload.get("ref", "")
            variables["commit_sha"] = (
                payload.get("after") or head_commit.get("id") or ""
            )[:8]
            variables["branch"] = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
            variables["commit_message"] = head_commit.get("message", "")[:200]

        # Pull request event
        elif event_type == "pull_request":
            pr = payload.get("pull_request", {}) or {}
            variables["pr_number"] = str(pr.get("number", ""))
            variables["pr_title"] = pr.get("title", "")
            variables["pr_action"] = payload.get("action", "")
            variables["commit_sha"] = (pr.get("head", {}).get("sha") or "")[:8]

        # Issues event
        elif event_type == "issues":
            issue = payload.get("issue", {}) or {}
            variables["issue_number"] = str(issue.get("number", ""))
            variables["issue_title"] = issue.get("title", "")
            variables["issue_action"] = payload.get("action", "")

        return variables

    def _resolve_workflow(self, event_type: str) -> str | None:
        """Look up which workflow to trigger for this event type."""
        routes = self.config.get("routes", DEFAULT_ROUTES)
        route = routes.get(event_type)
        if route:
            return route.get("workflow")
        return None

    def _build_workflow_vars(self, variables: dict) -> dict:
        """Build the variables dict that the workflow can reference as $variables.X."""
        result = {}
        for k, v in variables.items():
            if v:
                result[k] = str(v)
        return result

    def _handle_github_webhook(self):
        """Process a GitHub webhook event."""
        # Read body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"error": "empty body"})
            return
        if content_length > 1_000_000:
            # 1MB cap
            self._send_json(413, {"error": "payload too large", "max_bytes": 1_000_000})
            return

        body = self.rfile.read(content_length)

        # Verify signature
        if not self._verify_signature(body):
            self._send_json(403, {"error": "invalid signature"})
            return

        # Parse JSON
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        # Determine event type
        event_type = self.headers.get(GITHUB_EVENT_HEADER, "push").lower()

        # Look up matching workflow
        workflow_name = self._resolve_workflow(event_type)
        if not workflow_name:
            self._send_json(
                200,
                {
                    "status": "ignored",
                    "reason": f"no workflow mapped for event '{event_type}'",
                },
            )
            return

        # Extract variables from payload
        variables = self._extract_variables(event_type, payload)
        workflow_vars = self._build_workflow_vars(variables)

        # Generate a run ID
        run_id = str(uuid.uuid4())[:8]
        GitHubWebhookHandler._run_counter += 1

        print(
            f"[webhook] #{GitHubWebhookHandler._run_counter} "
            f"event={event_type} "
            f"repo={variables.get('repository', '?')} "
            f"→ workflow={workflow_name} "
            f"run_id={run_id}"
        )

        # Fire workflow in background (non-blocking)
        env = os.environ.copy()
        for k, v in workflow_vars.items():
            env[f"HERMES_VAR_{k}"] = v

        try:
            subprocess.Popen(
                ["hermes", "workflow", "run", workflow_name, "--native"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            print("[webhook] ERROR: 'hermes' command not found — workflow not launched")
            self._send_json(
                500,
                {
                    "status": "error",
                    "error": "hermes binary not found",
                    "workflow": workflow_name,
                    "run_id": run_id,
                },
            )
            return

        self._send_json(
            202,
            {
                "status": "accepted",
                "workflow": workflow_name,
                "run_id": run_id,
                "event": event_type,
                "variables": workflow_vars,
            },
        )


# ---------------------------------------------------------------------------
# Server launcher
# ---------------------------------------------------------------------------

def start_webhook_server(port: int = DEFAULT_PORT,
                         config_path: str = DEFAULT_CONFIG_PATH) -> None:
    """Start the GitHub webhook HTTP server on localhost.

    This is a blocking call — runs until KeyboardInterrupt.
    """
    config = load_config(config_path)

    # Allow CLI --port to override config file
    effective_port = port if port != DEFAULT_PORT else config.get("port", DEFAULT_PORT)

    # Inject config into handler
    GitHubWebhookHandler.config = config

    server = HTTPServer(("127.0.0.1", effective_port), GitHubWebhookHandler)

    print(f"🔌 GitHub webhook server listening on http://127.0.0.1:{effective_port}")
    print(f"   Config: {config_path}")
    print(f"   Secret: {'configured' if config.get('secret') else 'NONE (dev mode — all accepted)'}")
    print(f"   Routes:")
    for event, route in config.get("routes", DEFAULT_ROUTES).items():
        print(f"     {event:<20} → {route.get('workflow', '?')}")
    print()
    print("   Endpoint: POST /webhook/github")
    print("   Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down webhook server...")
        server.shutdown()
