# Contributing

Bug reports and small, focused PRs are welcome.

## Dev setup

```bash
pip install -e . pytest
pytest -q
```

## Ground rules

- Plain files first: nothing in core may require a network or a database.
- Every behavior change needs a test.
- Keep the core dependency-free (stdlib only).
