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

Set `UPDATE_LEAN=true` only when the VM also has a clean Lean checkout and you
want the script to fast-forward and build it. It defaults to `false`.

Configure these GitHub repository secrets for the workflow:
`GCP_SSH_HOST`, `GCP_SSH_USER`, `GCP_SSH_PRIVATE_KEY`, and
`GCP_DEPLOY_PATH`. `GCP_SSH_PORT` is optional and defaults to `22`.
