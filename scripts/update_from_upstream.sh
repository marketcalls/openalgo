#!/usr/bin/env bash
set -euo pipefail

# update_from_upstream.sh
# Safely fetch and update local branch from a fork remote (default: upstream/main)
# Usage examples:
#   ./scripts/update_from_upstream.sh                 # merge upstream/main into main
#   ./scripts/update_from_upstream.sh --remote origin --branch main --strategy rebase
#   ./scripts/update_from_upstream.sh --auto-theirs   # accept upstream for conflicts
#   ./scripts/update_from_upstream.sh --push         # push updated branch to origin after merge

REMOTE="upstream"
BRANCH="main"
STRATEGY="merge"   # merge or rebase
AUTO_THEIRS=0
NO_BACKUP=0
PUSH_AFTER=0
STASH_IF_DIRTY=0

usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  -r, --remote <name>      Remote name to pull from (default: upstream)
  -b, --branch <name>      Branch to update (default: main)
  -s, --strategy <merge|rebase>  Use merge (default) or rebase
      --auto-theirs        On conflicts accept upstream changes for conflicting files
      --no-backup          Don't create a backup branch
      --push               Push updated branch to 'origin' after successful merge
      --stash-if-dirty     Auto-stash local changes before updating and pop after
  -h, --help               Show this help and exit

Examples:
  $0
  $0 --remote upstream --branch main --strategy rebase --auto-theirs --push
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--remote)
      REMOTE="$2"; shift 2;;
    -b|--branch)
      BRANCH="$2"; shift 2;;
    -s|--strategy)
      STRATEGY="$2"; shift 2;;
    --auto-theirs)
      AUTO_THEIRS=1; shift;;
    --no-backup)
      NO_BACKUP=1; shift;;
    --push)
      PUSH_AFTER=1; shift;;
    --stash-if-dirty)
      STASH_IF_DIRTY=1; shift;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "Unknown option: $1"; usage; exit 2;;
  esac
done

echo "Update from remote '${REMOTE}' branch '${BRANCH}' (strategy=${STRATEGY})"

ROOT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || true)
if [[ -z "$ROOT_DIR" ]]; then
  echo "Not inside a git repository. Run this script from within the repository." >&2
  exit 1
fi
cd "$ROOT_DIR"

# ensure remote exists
if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  echo "Remote '$REMOTE' not found. Available remotes:" >&2
  git remote -v
  exit 1
fi

# check working tree cleanliness
if [[ -n "$(git status --porcelain)" ]]; then
  if [[ "$STASH_IF_DIRTY" -eq 1 ]]; then
    echo "Working tree has local changes; stashing them..."
    git stash push -u -m "update_from_upstream auto-stash"
    STASHED=1
  else
    echo "Working tree is not clean. Commit or stash changes, or run with --stash-if-dirty." >&2
    git status --porcelain
    exit 1
  fi
fi

echo "Fetching all remotes (with prune)..."
git fetch --all --prune

TS=$(date +%Y%m%d-%H%M%S)
BACKUP_BRANCH="backup/${BRANCH}-${TS}"
if [[ "$NO_BACKUP" -ne 1 ]]; then
  echo "Creating backup branch: $BACKUP_BRANCH"
  git branch "$BACKUP_BRANCH" || true
fi

echo "Checking out ${BRANCH}..."
git checkout "$BRANCH"

if [[ "$STRATEGY" == "merge" ]]; then
  echo "Merging ${REMOTE}/${BRANCH} into ${BRANCH}"
  set +e
  git merge --no-edit "${REMOTE}/${BRANCH}"
  MERGE_EXIT=$?
  set -e
elif [[ "$STRATEGY" == "rebase" ]]; then
  echo "Rebasing ${BRANCH} onto ${REMOTE}/${BRANCH}"
  set +e
  git rebase "${REMOTE}/${BRANCH}"
  MERGE_EXIT=$?
  set -e
else
  echo "Unknown strategy: $STRATEGY" >&2
  exit 2
fi

if [[ $MERGE_EXIT -eq 0 ]]; then
  echo "Update successful (no conflicts)."
  if [[ "$PUSH_AFTER" -eq 1 ]]; then
    echo "Pushing ${BRANCH} to origin..."
    git push origin "$BRANCH"
  fi
  if [[ "${STASHED:-0}" -eq 1 ]]; then
    echo "Popping stash..."
    git stash pop || true
  fi
  exit 0
fi

echo "Merge/Rebase exited with code $MERGE_EXIT — checking for conflicts..."
UNMERGED=$(git diff --name-only --diff-filter=U || true)
if [[ -z "$UNMERGED" ]]; then
  echo "No unmerged files found, but merge failed (exit $MERGE_EXIT). Please inspect the repository." >&2
  exit $MERGE_EXIT
fi

echo "Files with conflicts:"
echo "$UNMERGED"

# If auto-theirs requested, accept upstream changes for all conflicting files
if [[ "$AUTO_THEIRS" -eq 1 ]]; then
  echo "Auto-accepting upstream (theirs) for all conflicting files..."
  # Use xargs to handle spaces/newlines safely
  echo "$UNMERGED" | xargs -r -d '\n' git checkout --theirs --
  echo "$UNMERGED" | xargs -r -d '\n' git add --
  git commit -m "Merge ${REMOTE}/${BRANCH} - accept upstream for conflicts"
  if [[ "$PUSH_AFTER" -eq 1 ]]; then
    git push origin "$BRANCH"
  fi
  if [[ "${STASHED:-0}" -eq 1 ]]; then
    git stash pop || true
  fi
  echo "Merge completed by accepting upstream for all conflicts."
  exit 0
fi

# Try to auto-resolve common lockfiles by taking 'theirs' (upstream).
echo "Attempting to auto-resolve common lockfiles (package-lock.json, uv.lock, yarn.lock, pnpm-lock.yaml, Pipfile.lock, poetry.lock)"
COMMON_LOCKS=("package-lock.json" "uv.lock" "yarn.lock" "pnpm-lock.yaml" "Pipfile.lock" "poetry.lock")
RESOLVED=()
for f in ${COMMON_LOCKS[@]}; do
  if echo "$UNMERGED" | grep -qx "$f" 2>/dev/null; then
    echo "  Accepting upstream for $f"
    git checkout --theirs -- "$f" || true
    git add -- "$f" || true
    RESOLVED+=("$f")
  fi
done

if [[ ${#RESOLVED[@]} -gt 0 ]]; then
  echo "Auto-resolved lockfiles: ${RESOLVED[*]}"
  # Re-check if conflicts remain
  REMAINING=$(git diff --name-only --diff-filter=U || true)
  if [[ -z "$REMAINING" ]]; then
    git commit -m "Merge ${REMOTE}/${BRANCH} - auto-resolved lockfiles"
    if [[ "$PUSH_AFTER" -eq 1 ]]; then
      git push origin "$BRANCH"
    fi
    if [[ "${STASHED:-0}" -eq 1 ]]; then
      git stash pop || true
    fi
    echo "Merge completed after resolving lockfiles."
    exit 0
  else
    echo "Remaining conflicted files after resolving locks:"
    echo "$REMAINING"
    echo "Please resolve these conflicts manually. Files listed above." >&2
    exit 2
  fi
fi

echo "No automatic resolutions possible. Please resolve conflicts manually." >&2
echo "Conflicted files:"
echo "$UNMERGED"
echo
echo "To accept upstream for all conflicts run:"
echo "  git checkout --theirs -- \\$(git diff --name-only --diff-filter=U)" 
echo "  git add -A && git commit -m 'Accept upstream for conflicts'"
if [[ "${STASHED:-0}" -eq 1 ]]; then
  echo "Note: a stash was created. After you finish resolving, run 'git stash pop' if needed." 
fi

exit 2
