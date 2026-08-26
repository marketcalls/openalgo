#!/usr/bin/env bash
set -euo pipefail

LEAN_ROOT="${LEAN_ROOT:-/opt/Lean}"
PYTHON_ENV_PREFIX="${PYTHON_ENV_PREFIX:-$LEAN_ROOT/.conda/lean-py311}"
CONDA_BIN="${CONDA_BIN:-conda}"

die() { echo "setup-python: $*" >&2; exit 1; }

[[ -f "$LEAN_ROOT/environment.python311.yml" ]] || \
  die "Lean Python manifest not found: $LEAN_ROOT/environment.python311.yml"

if ! command -v "$CONDA_BIN" >/dev/null 2>&1; then
  for candidate in /opt/miniconda3/bin/conda "$HOME/miniconda3/bin/conda"; do
    if [[ -x "$candidate" ]]; then
      CONDA_BIN="$candidate"
      break
    fi
  done
fi
command -v "$CONDA_BIN" >/dev/null 2>&1 || \
  die "conda was not found; install Miniconda/Conda on the server first or set CONDA_BIN"

CONDA_ROOT="$(cd "$(dirname "$(command -v "$CONDA_BIN")")/.." && pwd)"
export PATH="$CONDA_ROOT/bin:$PATH"

if ! conda env list | awk '$1 == "lean-py311" { found = 1 } END { exit !found }'; then
  conda env create -f "$LEAN_ROOT/environment.python311.yml"
else
  conda env update -n lean-py311 -f "$LEAN_ROOT/environment.python311.yml" --prune
fi

if [[ -d "$PYTHON_ENV_PREFIX" ]]; then
  conda env update --prefix "$PYTHON_ENV_PREFIX" -f "$LEAN_ROOT/environment.python311.yml" --prune
else
  conda create --prefix "$PYTHON_ENV_PREFIX" --clone lean-py311 --yes
fi

PYTHON_BIN="$PYTHON_ENV_PREFIX/bin/python"
PYTHONNET_PYDLL="${PYTHONNET_PYDLL:-$PYTHON_ENV_PREFIX/lib/libpython3.11.so}"
[[ -x "$PYTHON_BIN" ]] || die "Python executable was not created: $PYTHON_BIN"
[[ -f "$PYTHONNET_PYDLL" ]] || die "Python shared library was not created: $PYTHONNET_PYDLL"

"$PYTHON_BIN" -c 'import sys, numpy, pandas, scipy, clr_loader, pythonnet; print(sys.version); print("pythonnet", pythonnet.__version__)'

echo
echo "Lean Python environment is ready."
echo "PYTHON_VENV=$PYTHON_ENV_PREFIX"
echo "PYTHONNET_PYDLL=$PYTHONNET_PYDLL"
