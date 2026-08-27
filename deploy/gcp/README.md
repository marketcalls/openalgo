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

By default this also copies the local `Lean/Launcher/bin/Debug` artifacts,
including `QuantConnect.Brokerages.OpenAlgo.dll` and `OpenAlgo.NET.dll`, into
the matching server directory. The copy does not delete existing server files.
Set `COPY_LEAN_ARTIFACTS=false` to skip it, or set `LOCAL_LEAN_ARTIFACT_DIR`
when the artifacts are in a different local configuration directory.

Set up the server’s Python 3.11 environment once with the laptop SSH helper:

```bash
DEPLOY_SSH_KEY=$HOME/.ssh/your-key.pem \
REMOTE_LEAN_ROOT=/opt/Lean \
scripts/setup-server-python.sh user@server
```

This uses the server copy of `Lean/environment.python311.yml`, creates
`/opt/Lean/.conda/lean-py311`, installs the pinned Python packages plus
`pythonnet`/`clr-loader`, and verifies `libpython3.11.so`. It does not copy the
macOS environment, modify strategy credentials, or alter the Lean source tree.
The existing runners automatically use this environment and its native Python
library on Linux.

To deploy and immediately launch a strategy through the existing Lean launcher
using the OpenAlgo runner, append the strategy path and class name:

```bash
scripts/deploy-to-server.sh user@server \
  strategies/python/your_strategy/Strategy.py Strategy
```

The laptop command uses `rsync` for code and Lean artifact transfer, then remotely verifies the
Lean launcher DLL under `LEAN_ROOT` or a `lean` CLI on `PATH`. It never updates
or rebuilds the Lean checkout by default. To regenerate Lean artifacts on the
server from its existing source checkout, use:

```bash
REMOTE_BUILD_LEAN=true scripts/deploy-to-server.sh user@server
```

This is useful when the required managed DLLs are already present in the local
launcher output. Set `STRATEGY_RUNNER` remotely when a different runner is
required.

Set `UPDATE_LEAN=true` only when the VM also has a clean Lean checkout and you
want the script to fast-forward and build it. It defaults to `false`.

The GitHub Actions workflow deploys the private repository contents from the
Actions runner over SSH; the VM does not need GitHub credentials or a GitHub
checkout. Configure these GitHub repository secrets:

* `GCP_SSH_HOST`: VM address, for example `34.14.217.110`
* `GCP_SSH_USER`: VM user, for example `arifkhan`
* `GCP_SSH_PRIVATE_KEY`: the complete private SSH key accepted by the VM
* `GCP_DEPLOY_PATH`: application path, for example `/home/arifkhan/lean-strategies`
* `GCP_LEAN_PATH`: optional existing Lean path, for example `/home/arifkhan/Lean`
* `GCP_SSH_PORT`: optional SSH port, defaults to `22`

The workflow excludes `.env`, runtime output, and the existing Lean artifacts
from the transfer. This preserves server credentials and the existing Lean
installation while updating strategy code and deployment scripts.
