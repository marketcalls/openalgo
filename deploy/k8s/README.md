# OpenAlgo on Kubernetes (Kustomize)

First-class Kubernetes deployment for OpenAlgo: base manifests + Kustomize
overlays, one instance per broker account, with every OpenAlgo feature working
unchanged in the official container image. Design rationale:
[issue #1641](https://github.com/marketcalls/openalgo/issues/1641).

## The model

> **One broker account = one OpenAlgo instance = one single-replica
> `StatefulSet`, with its own `Secret`, one `PersistentVolumeClaim`, two
> `Service`s (`http:5000`, `ws:8765`), and one edge route (Ingress or
> HTTPRoute) on its own subdomain.**

OpenAlgo is architecturally single-user / single-broker / single-process: six
SQLite DBs, in-process SocketIO, one shared broker WebSocket feed, a
loopback-only ZeroMQ bus, and `gunicorn -w 1` under eventlet. One instance
cannot serve two brokers, and one instance must not run more than one replica.
Multi-broker therefore means N instances — one overlay each — and any
cross-broker orchestration stays in a client-side fan-out layer, not inside
OpenAlgo.

Each instance runs the unmodified image (`marketcalls/openalgo`) whose
`start.sh` starts the whole process group in one container: gunicorn
(eventlet, 1 worker) + the out-of-process WebSocket proxy (8765) + the ZeroMQ
binder (5555). They share a network namespace because the ZMQ bus is
loopback-only and the proxy is a child of the gunicorn process.

```
deploy/k8s/
├── base/            library: StatefulSet, two Services, ConfigMap (no Secret)
├── edge/
│   ├── ingress/     Ingress API variant (default; k3s Traefik works as-is)
│   └── gateway/     Gateway API variant (Standard channel; opt-in)
└── overlays/
    ├── _template/   copy-me reference for a new instance
    └── <broker>/    zerodha, groww, angel, dhan, fyers, fivepaisa,
                     kotak, motilal, paytm, upstox
```

## Invariants — do not violate

| Rule | Why |
| --- | --- |
| `replicas: 1`, never more | SQLite corruption, double broker login, ZMQ bus races, shared-feed teardown churn |
| Never split flask / ws-proxy / zmq into sidecars or separate Pods | breaks the loopback ZMQ bus and the SUB-binds/PUBs-connect invariant |
| Never expose port 5555 as a container port or Service | leaks the raw tick feed; ZMQ stays loopback (`ZMQ_HOST=127.0.0.1`) |
| Subdomain routing only; never path-prefix rewriting | OpenAlgo serves absolute paths and a strict CSP with a derived `wss://host` |
| Unique `APP_KEY` / `API_KEY_PEPPER` / `FERNET_SALT` / cookie names per instance | shared values destroy session and encryption isolation |
| `TRUST_PROXY_HEADERS=TRUE` with the edge as the sole route | otherwise IP bans and rate limits see the proxy IP (or are spoofable) |
| `StatefulSet`, never a `Deployment` | stable PVC re-attachment for SQLite, stable identity |
| Never set the `PORT` env var | `start.sh` prefers it over `FLASK_PORT` for the gunicorn bind |
| No pod restarts 02:30-03:30 IST | broker tokens refresh at ~03:00 IST (`SESSION_EXPIRY_TIME`) |

## Prerequisites

- kustomize >= 5.3 — the `labels:` field the base uses needs it. Check the
  version your kubectl bundles with `kubectl version --client` (older kubectl
  releases ship kustomize 5.0.x-5.2.x, which reject the base); if it is older,
  install a standalone kustomize v5.3+ and apply with
  `kustomize build deploy/k8s/overlays/<broker> | kubectl apply -f -`.
- A namespace: `kubectl create namespace openalgo` (the manifests set
  `namespace: openalgo` but do not create it — one namespace per instance is
  the recommended isolation; see "Multiple instances" below).
- An ingress controller. The manifests default to `ingressClassName: traefik`.
- Optional: cert-manager for TLS, kubeconform for offline validation.

### k3s notes

- The Traefik bundled with k3s serves the **Ingress** variant out of the box
  (`local-path` is also the default StorageClass, which the base assumes).
- The **Gateway** variant needs extra setup: k3s's Traefik ships its Gateway
  provider disabled. Either enable it with a `HelmChartConfig` patch
  (`providers.kubernetesGateway.enabled: true`; production-ready since
  Traefik v3.1) and install the Standard-channel Gateway API CRDs, or run
  `k3s ... --disable=traefik` and install a standalone controller (Envoy
  Gateway, NGINX Gateway Fabric, Cilium).
- GatewayClass is cluster-scoped and controller-owned: install it once per
  cluster, never per instance (a namePrefix would mint one per broker).

## Quickstart

```bash
# 1. Namespace
kubectl create namespace openalgo

# 2. Instance dir (copy the template to a NEW directory; overlays/zerodha
#    already exists as the worked example)
cp -r deploy/k8s/overlays/_template deploy/k8s/overlays/<broker>

# 3. Secrets: copy the shared example to secret.env and fill it in
cd deploy/k8s/overlays/<broker>
cp ../_template/secret.env.example secret.env
python3 -c "import secrets; print(secrets.token_hex(32))"   # APP_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"   # API_KEY_PEPPER
python3 -c "import secrets; print(secrets.token_hex(16))"   # FERNET_SALT

# 4. Point patches at your domain (patches/config.yaml, patches/edge-host-ingress.yaml)

# 5. Apply
kubectl apply -k deploy/k8s/overlays/zerodha

# 6. Watch
kubectl -n openalgo get pods,pvc,ingress -w
```

DNS: point the instance's subdomain (`zerodha.example.com`) at your cluster
edge (node IP / LoadBalancer), or use a wildcard `*.example.com` record when
running several instances. TLS: uncomment the cert-manager annotation in
`edge/ingress/ingress.yaml` (via the overlay), or supply the TLS Secret
yourself — a wildcard certificate covers all instances.

## Per-instance checklist

Everything below MUST be unique per instance — this is the k8s equivalent of
`install/install-multi.sh`'s per-instance keys, cookies and paths:

1. `namePrefix: <broker>-` in the overlay kustomization.
2. `app.kubernetes.io/instance: <broker>` label.
3. `APP_KEY`, `API_KEY_PEPPER`, `FERNET_SALT` — generated once, **before the
   first boot**, backed up. Pinning is not optional in Kubernetes:
   `/app/.env` lives in the ephemeral container layer and
   `utils/env_check.py` auto-rotates a placeholder `FERNET_SALT` there on
   first boot. An unpinned salt is re-rotated on every pod restart, which
   makes the Fernet-encrypted broker tokens in the persistent database
   undecryptable. (Requires an image whose `start.sh` persists `FERNET_SALT`
   into the generated `.env` — included in this PR; older images re-rotate
   the salt on every restart even when pinned in the Secret.)
4. Broker credentials (`BROKER_API_KEY`, `BROKER_API_SECRET`, and the
   `_MARKET` pair for XTS brokers).
5. `VALID_BROKERS: <broker>` (single slug — faster startup, one broker per
   instance). Slugs must match the `VALID_BROKERS` list in `.sample.env`.
6. `HOST_SERVER`, `REDIRECT_URL` (register exactly this URL in the broker's
   developer app), edge hostname, TLS secret name.
7. `SESSION_COOKIE_NAME` / `CSRF_COOKIE_NAME` (the app adds `__Secure-` at
   runtime under https).

## Secrets

### Plain Secret (default)

The overlay's `secretGenerator` builds the Secret from `secret.env` and
appends a content hash to its name. Consequences:

- Any change to `secret.env` creates a new Secret and **rolls the pod on the
  next apply** — apply secret changes off-hours, never inside the 02:30-03:30
  IST window.
- The old hashed Secret is **not pruned** by `kubectl apply -k`; rotated
  Secrets accumulate in the namespace. After the pod is up on the new Secret,
  delete the previous one:
  `kubectl -n openalgo get secrets --sort-by=.metadata.creationTimestamp`
  (the second-newest `<broker>-openalgo-env-<hash>` once the newest is live).
- `kubectl kustomize` output contains the base64 secret values. Never paste
  build output into issues or PRs.

### SealedSecret (git-friendly, optional)

Install [Bitnami Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets)
in the cluster, then seal per instance:

```bash
kubeseal --scope namespace-wide \
  -n openalgo \
  < <(kubectl create secret generic openalgo-env \
      --from-env-file=secret.env --dry-run=client -o json) \
  > sealed-secret.yaml
```

Commit `sealed-secret.yaml`, delete the overlay's `secretGenerator` block, and
add `sealed-secret.yaml` to the overlay resources instead. Two hard rules:

- **Seal with `--scope namespace-wide` (or `cluster-wide`).** The default
  strict scope embeds the Secret name and namespace — and this package's
  `namePrefix` renames the resource (`zerodha-openalgo-env`), so a
  strict-scope blob would fail to decrypt.
- SealedSecrets carry no content hash: secret changes need a manual
  `kubectl -n openalgo rollout restart statefulset/<instance>-openalgo`.

ExternalSecrets support is deliberately deferred to a follow-up.

## Storage

One PVC (`data`, default 10Gi on the `local-path` StorageClass) is mounted
with `subPath`s:

| subPath | Mount | Contents |
| --- | --- | --- |
| `db` | `/app/db` | six SQLite DBs + Historify DuckDB (critical) |
| `log` | `/app/log` | application and strategy logs |
| `strategies` | `/app/strategies` | Python strategy host scripts |
| `keys` | `/app/keys` | MCP OAuth keys (chmod 700) |

`/app/tmp` (numba/matplotlib caches) is an `emptyDir` and `/dev/shm` is a
memory-backed `emptyDir` (the compose `shm_size` equivalent) — both are wiped
on restart, so expect a multi-minute numba JIT cold start after any pod
restart.

Swapping the StorageClass or size (e.g. Longhorn):

```yaml
# overlay kustomization, BEFORE the first apply:
patches:
- path: patches/storage.yaml   # copy it from ../_template/patches/
```

`volumeClaimTemplates` are **immutable**: `storageClassName` and `storage` can
only be set on first apply. Resize afterwards with `kubectl patch pvc` (needs
a StorageClass with `allowVolumeExpansion`), or use the JSON6902
`storage-default-class` patch to drop `storageClassName` and inherit the
cluster default.

Note: k3s `local-path` ties each PVC to the node it was created on.

## Egress / SEBI static-IP

The SEBI static-IP mandate (effective April 1, 2026; Delta Exchange enforces
the same) constrains broker **egress** — a separate concern from ingress, and
neither Ingress nor Gateway API pins egress IPs. The v1 approach for
bare-metal k3s is node affinity:

1. Label the node whose IP is whitelisted at your broker:
   `kubectl label node <node> openalgo/egress=whitelisted`
   (optionally also taint it, so only OpenAlgo schedules there).
2. Enable `patches/node-egress.yaml` in the overlay (copy it from
   `../_template/patches/` first) and whitelist that node's IP at the broker.

`local-path` conveniently keeps the instance's PVC on the same node, so
instance and data move together. Per-broker distinct egress IPs (Cilium
Egress Gateway / Istio / Calico) are documented alternatives, out of scope
here.

## Gateway API variant

Swap the edge in the overlay kustomization:

```yaml
resources:
- ../../base
- ../../edge/gateway            # instead of ../../edge/ingress

patches:
- path: patches/edge-host-gateway.yaml   # instead of patches/edge-host-ingress.yaml
```

`edge/gateway/kustomizeconfig.yaml` carries the `nameReference` rules that
make `namePrefix` rewrite the Gateway API references kustomize's built-in
table misses entirely (`HTTPRoute.backendRefs`, `HTTPRoute.parentRefs`). The
Gateway's TLS `certificateRefs` are **not** rewritten by any rule — the
referenced Secret is operator-provided and never a build resource — so the
overlay's `patches/edge-host-gateway.yaml` sets the per-instance certificate
name explicitly. Skipping that patch leaves the base default `openalgo-tls`
in place, and the listener never becomes ready; verify your build:

```bash
kubectl kustomize deploy/k8s/overlays/<broker> | grep -A2 'backendRefs:\|parentRefs:'
# names must carry the instance prefix, e.g. zerodha-openalgo-ws
kubectl kustomize deploy/k8s/overlays/<broker> | grep -B1 -A1 'certificateRefs:' 
# name must match the TLS Secret you provisioned, e.g. zerodha-openalgo-tls
```

Each overlay creates its own namespaced Gateway (its own LoadBalancer). To
share one cluster-level Gateway across instances, see
`overlays/_template/patches/drop-gateway.yaml` — cross-namespace `parentRef`s
need the shared Gateway's `allowedRoutes.namespaces.from: All` (no
`ReferenceGrant` is needed for parentRefs; this package never uses
cross-namespace backendRefs).

## Upgrades / maintenance

- Pin the image tag per tested release (`images:` in the overlay
  kustomization); `latest` moves under your feet.
- ConfigMap changes do not auto-roll (no hash on the base ConfigMap):
  `kubectl -n openalgo rollout restart statefulset/<instance>-openalgo`.
- A restart always means a short outage (single replica) plus a numba JIT
  cold start. Verify no open orders, then restart **outside market hours and
  outside the ~03:00 IST token-refresh window**.
- Migrations run inside the pod on every boot (`start.sh` runs
  `upgrade/migrate_all.py` and aborts on failure) — the startup probe allows
  300s for this plus JIT warm-up.

## Multiple instances

The ten provided overlays are ready-made starting points. Two isolation rules:

- Prefer **one namespace per instance** (`namespace:` in the overlay).
- If you co-locate instances in one namespace, the `instance` label with
  `includeSelectors: true` already keeps each Service on its own pod — do not
  remove it.

Each instance needs its own subdomain, its own broker OAuth callback
registration, and its own secrets — see the checklist above.

## Verification (no cluster required)

```bash
kubectl kustomize deploy/k8s/base > /dev/null           # base is a library; a
                                                        # dangling Secret ref is expected
for o in zerodha groww angel dhan fyers fivepaisa kotak motilal paytm upstox; do
  kubectl kustomize deploy/k8s/overlays/$o > /dev/null || echo "FAIL $o"
done
```

Structural checks worth running after any manifest change: exactly one
StatefulSet and no Deployment per build; `replicas: 1`; `ZMQ_HOST=127.0.0.1`;
no 5555 outside the env var; no `PORT` env var; Ingress backends and `envFrom`
refs carry the instance prefix (the Secret also a content hash). For the
gateway variant also check `parentRefs`/`backendRefs`/`certificateRefs` per
the section above.

## Smoke-test findings (k3s, 2026-09-04)

The package was exercised end to end on a k3s cluster (Gateway API variant,
arm64 image, hostPath instead of a PVC). Three findings worth knowing:

1. `ENV_CONFIG_VERSION` — `start.sh` wrote `1.0.4` into the generated `.env`
   while the image's `.sample.env` said `1.0.7`; `env_check.py` treats the
   generated env as outdated and prompts interactively, which cancels startup
   under Kubernetes (no stdin). Fixed by bumping the `start.sh` default; if
   you pin an older image, set `ENV_CONFIG_VERSION` in the overlay ConfigMap
   to that image's bundled `.sample.env` version.
2. `FERNET_SALT` rotation — older `start.sh` templates never wrote
   `FERNET_SALT` into the generated `.env`, and `env_check.py` consults only
   the file, so the salt re-rotated on every restart even when pinned in the
   Secret. Fixed in `start.sh` in this PR; the restart drill passes on images
   built after that commit.
3. Gateway listener port — a controller only accepts listeners whose port
   matches one of its entryPoints. A stock k3s Traefik serves 443 directly,
   but Helm-style installs often map 443 (service) to 8443 (container). If
   the Gateway stays `Accepted=False` with `PortUnavailable`, patch the
   listener port to the controller's entryPoint port — external access
   typically still uses 443.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Pod `Pending` | StorageClass missing (or nodeSelector from `node-egress.yaml` on an unlabeled node) |
| `CrashLoopBackOff` with "STARTUP BLOCKED" banner | placeholder or leaked `APP_KEY`/`API_KEY_PEPPER` (`start.sh` preflight) — set real values in `secret.env` |
| `Permission denied: .env.tmp` in logs | `/app` not writable; check you did not enable `readOnlyRootFilesystem` |
| Broker tokens undecryptable after a restart | `FERNET_SALT` not pinned in `secret.env` — the salt re-rotated on the ephemeral layer |
| Readiness flapping | probe interval vs in-app limits (`/health/check` allows 60/min, `/health/status` 300/min) — keep intervals >= 15s |
| WS connects then times out at the edge | missing `/ws` route, or an edge idle timeout below the feed cadence — set the timeout >= 86400s or add a client heartbeat |
| 503 from the edge | readiness failing — check both the 8765 listener and `/health/check` from inside the pod |
| Chart export OOM | raise the `/dev/shm` sizeLimit or the memory limit (headless Chromium) |
| `EACCES` on PVC paths | `fsGroup` not honored by the provisioner — check `fsGroup: 1000` / `fsGroupChangePolicy` |
| Gateway route 404s after rename | `edge/gateway/kustomizeconfig.yaml` not wired (`configurations:`) — grep the build for prefixed refs |
| SealedSecret fails to decrypt | sealed with strict scope — re-seal with `--scope namespace-wide` or `cluster-wide` |
