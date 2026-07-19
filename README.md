# Hermes Workflows

Community marketplace and plugin for Hermes Agent workflow orchestration.

## Install

```bash
# Plugin (engine + CLI + webhook)
mkdir -p ~/.hermes/plugins/workflow
cp plugins/*.py ~/.hermes/plugins/workflow/

# Community workflows
cp -r community ~/.hermes/workflows/community

# Webhook config
cp webhook.yaml ~/.hermes/workflows/webhook.yaml
```

## Marketplace

Shareable workflow YAMLs in `community/`:

| Workflow | Type | Description |
|----------|------|-------------|
| `system-health-check` | Monitoring | Daily disk, memory, bridge endpoint liveness |
| `alaya-build` | CI/CD | Flutter APK build pipeline: audit → build → ship |
| `pre-commit-review` | Code Review | Pre-commit gate with auto-fix + [verified] commit |
| `branch-review` | Code Review | Pre-merge: diff analysis + churn + conflict check |
| `hermes-tweet-signal-brief` | Monitoring | Read-only X/Twitter signal brief using Hermes Tweet routes |

### Usage

```bash
hermes workflow run community/system-health-check --native
hermes workflow run community/alaya-build --native
```

## Webhook

GitHub events trigger workflows automatically:

```bash
hermes workflow webhook --port 9001
```

| GitHub Event | → Workflow |
|-------------|-----------|
| `push` | `codebase-audit` |
| `pull_request` | `pre-commit-review` |
| `issues` | `branch-review` |

Configure routes in `webhook.yaml`.

## Plugin Structure

```
plugins/workflow/
├── __init__.py      # Plugin registration + /workflow slash command
├── engine.py        # YAML parser, native execution, classify_task()
├── cli.py           # CLI: hermes workflow {run,list,show,create,stats,webhook}
├── webhook.py       # Webhook HTTP server (GitHub → workflow trigger)
└── run.py           # Standalone runner

community/
├── README.md
├── system-health-check.yaml
├── alaya-build.yaml
├── pre-commit-review.yaml
├── branch-review.yaml
└── hermes-tweet-signal-brief.yaml

webhook.yaml         # Webhook route configuration
```

## License

MIT

## Trademark Notice

Xquik is an independent third-party service. Not affiliated with X Corp. "Twitter" and "X" are trademarks of X Corp.

## Related

- **[yflow](https://github.com/alanpaul1969/yflow)** — Standalone pip-installable workflow engine (`pip install yflow`). Same YAML schema, runs anywhere without Hermes. The `hermes-workflows` plugin is the Hermes-native counterpart; `yflow` is the provider-agnostic standalone.
