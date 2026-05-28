# Hermes Workflow Marketplace

Share and discover reusable workflow YAMLs. Community workflows can be used with:

```bash
hermes workflow run community/<name>.yaml --native
```

## Contributing

1. Create a `<name>.yaml` in this directory
2. Add a description comment at the top
3. Test with `hermes workflow run community/<name>.yaml --native`
4. Share on GitHub / Discord

## Available Workflows

| Workflow | Description | Type |
|----------|-------------|------|
| system-health-check.yaml | Daily system health: disk, memory, bridge endpoint liveness. Universal monitoring — everyone should run this. | Monitoring |
| alaya-build.yaml | Flutter APK build pipeline (Gates 4-6): audit → git push → flutter build → scp delivery. Multi-machine Flutter CI/CD pattern. | Build / CI-CD |
| pre-commit-review.yaml | Pre-commit gate: auto-detect changes → unified code review → auto-fix (2 cycles max) → [verified] commit. ~30-60s. | Code Review |
| branch-review.yaml | Pre-merge gate: full branch diff vs main → commit quality + churn analysis + merge conflict check. | Code Review |

## Template Reference

See `~/.hermes/workflows/_templates/` for starter templates:
- `backend-bug-fix.yaml` — Diagnose → Fix → Restart → Verify
- `backend-feature.yaml` — Plan → Implement → Test → Restart
- `flutter-bug-fix.yaml` — Diagnose → Sync → Fix → Audit → Build → Ship
- `flutter-feature.yaml` — Plan → Sync → Implement → Audit → Build → Ship → Doc
