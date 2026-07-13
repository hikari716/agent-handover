<!-- agent-handover:begin -->
## Session handover (agent-handover)

At the START of every session, before anything else, run:

```bash
agent-handover check --checkpoint .agent-handover/checkpoint.json
```

- exit `1` -> a previous handover was interrupted; finish it (re-run the end-of-session handover) before starting new work.
- exit `0`/`2` -> clean; read `memory/layer2/current-state.md` to recover context, then proceed.

At the END of the session, run the end-of-session handover (see `examples/codex-cli/end_of_session.py`).
<!-- agent-handover:end -->
