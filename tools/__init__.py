"""Development harnesses. ⛔ Not part of the service and not packaged.

`pyproject.toml`'s `[tool.setuptools.packages.find]` includes `narrate*` only,
so nothing here ships. It is in the repository because a negative-control
harness that gates a verdict is part of the deliverable: a reviewer must be
able to confirm the repair, not only the disclosure.
"""
