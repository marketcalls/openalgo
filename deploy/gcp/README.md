# GCP code deployment

The deployment target is a Linux Compute Engine VM with two sibling checkouts:

```text
/opt/Lean
/opt/lean-strategies
```

The VM must have a clean checkout of `lean-strategies` at the configured path.
The deploy script fetches and fast-forwards that checkout, validates JSON
configuration, and stops there. It does not build Lean, start or restart a
strategy, install a service, or copy credentials. OpenAlgo remains responsible
for running the strategy.

From the laptop, deploy directly over SSH while preserving the existing Lean
installation:

```bash
DEPLOY_SSH_KEY=$HOME/.ssh/your-key.pem \
REMOTE_APP_ROOT=/opt/lean-strategies \
REMOTE_LEAN_ROOT=/opt/Lean \
scripts/deploy-to-server.sh user@server
```

To deploy and immediately launch a strategy through the existing Lean launcher
using the OpenAlgo runner, append the strategy path and class name:

```bash
scripts/deploy-to-server.sh user@server \
  strategies/python/your_strategy/Strategy.py Strategy
```

The laptop command uses `rsync` for code transfer, then remotely verifies the
Lean launcher DLL under `LEAN_ROOT` or a `lean` CLI on `PATH`. It never updates
or rebuilds the Lean checkout. Set `STRATEGY_RUNNER` remotely when a different
runner is required.

Set `UPDATE_LEAN=true` only when the VM also has a clean Lean checkout and you
want the script to fast-forward and build it. It defaults to `false`.

Configure these GitHub repository secrets for the workflow:
`GCP_SSH_HOST`, `GCP_SSH_USER`, `GCP_SSH_PRIVATE_KEY`, and
`GCP_DEPLOY_PATH`. `GCP_SSH_PORT` is optional and defaults to `22`.
