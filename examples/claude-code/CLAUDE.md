<!-- agent-handover:begin -->
## Session handover (agent-handover)

At the start of every session, before other work, run:

```bash
agent-handover check --checkpoint .agent-handover/checkpoint.json
```

- Exit `1`: a previous handover was interrupted. Finish it before starting new work.
- Exit `0` or `2`: read `memory/layer2/current-state.md` to recover context, then proceed.

At the end of the session, run the end-of-session handover from
`examples/claude-code/end_of_session.py`.
<!-- agent-handover:end -->
