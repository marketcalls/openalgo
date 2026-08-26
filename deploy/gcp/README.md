# GCP deployment

The deployment target is a Linux Compute Engine VM with two sibling checkouts:

```text
/opt/Lean
/opt/lean-strategies
```

The VM must have the .NET SDK, Python runtime required by Lean, `jq`, and the
brokerage runtime already installed. The deploy script only fast-forwards clean
checkouts, builds Lean, validates JSON configuration, and restarts an existing
systemd service. It does not copy credentials or create a live-trading config.

For the first install, create a `lean` service account, install the unit as root,
and copy `lean-strategy.env.example` to
`/etc/lean-strategy/lean-strategy.env`. Set `STRATEGY_RUNNER` to the appropriate
runner for the strategy and keep `LIVE_CONFIRM=true` with paper trading until
the deployment has been verified.

```bash
sudo install -d -m 0750 /etc/lean-strategy
sudo install -m 0644 deploy/gcp/lean-strategy.service /etc/systemd/system/lean-strategy.service
sudo install -m 0600 deploy/gcp/lean-strategy.env.example /etc/lean-strategy/lean-strategy.env
sudo systemctl daemon-reload
sudo systemctl enable lean-strategy
```

Configure these GitHub repository or environment secrets for the workflow:
`GCP_SSH_HOST`, `GCP_SSH_USER`, `GCP_SSH_PRIVATE_KEY`, and
`GCP_DEPLOY_PATH`. `GCP_SSH_PORT` is optional and defaults to `22`.
