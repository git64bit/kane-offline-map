# Linux Development and Git Delivery

## Single source of truth

Development begins only from the accepted full SHA on `main`. Before applying a batch:

```sh
git status --short
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

The working tree must be clean and the local and remote SHAs must match.

## Batch delivery

Each development batch is one Git commit delivered as a `git format-patch` file. Apply it from the repository root:

```sh
git am --3way /path/to/kane-offline-map-batch-NNN.patch
```

This preserves the authored commit, file additions and deletions, and Git file modes. If the patch does not apply cleanly:

```sh
git am --abort
```

Do not continue on a partially applied batch.

## Linux verification

```sh
bash verify-linux.sh
```

All development and verification occur on Linux. Windows is only a final offline runtime target.

## Publish and reconcile

After tests pass:

```sh
git push origin main
LOCAL_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
printf 'Local:  %s\nRemote: %s\n' "$LOCAL_SHA" "$REMOTE_SHA"
test "$LOCAL_SHA" = "$REMOTE_SHA"
```

The resulting full SHA becomes the next accepted SSOT only after reconciliation.
