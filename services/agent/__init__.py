"""The `/agent` module: an LLM agent over OpenAlgo's internal service layer.

Nothing is re-exported here on purpose. Importing this package must not pull in
agno, LiteLLM, the database or a broker, so a submodule with narrow needs (the
wire contract in :mod:`services.agent.frames`, the provider vocabulary in
:mod:`services.agent.providers`) stays importable on its own.

The build contract is `docs/design/55-agent/README.md`. Where that document and
this code disagree, the code is right.
"""
