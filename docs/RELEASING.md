# Releasing

**Flow:** pull request checks pass → PR is merged into `main` → CI passes on that `main` commit → the *Release* workflow validates the
version → annotated tag `vX.Y.Z` + GitHub Release (generated notes).

## Version source of truth
The bot's release version is `__version__` in `app/__init__.py` (semantic versioning). It is **not** the TrustHost API version
(`API_VERSION`, currently `1.3.3`). To release: bump `__version__` in a PR. Merging a PR that does not change it releases nothing.

Rules enforced by `.github/workflows/release.yml`:
* the release job only runs when the `CI` workflow concluded `success` for a **push to `main`** (never for PRs, failures or cancellations);
* if tag `v<version>` already exists, no tag is created; if its GitHub Release is missing, only the release is created;
* a new tag must be higher than every existing `vX.Y.Z` tag, otherwise the job fails with an error annotation;
* tags are annotated; the release uses `gh release create --verify-tag --generate-notes`;
* permissions: `contents: write` for the release workflow only; `contents: read` for CI. No personal access token or extra secret is used;
* pushes made with the workflow `GITHUB_TOKEN` do not start further workflows, so the release cannot loop.

## Diagnosing a failed release
1. Actions → **Release** → open the failed run; the first red step names the cause (invalid `__version__`, version lower than the latest tag,
   tag push rejected, release creation failed).
2. *Tag push rejected*: a repository tag ruleset forbids `github-actions[bot]` from creating tags – allow it for `v*`, or create the tag by hand.
3. Fix the cause (usually: bump the version in a new PR) or the repository setting.

## Safe retry
Open the failed *Release* run → **Re-run failed jobs** (or **Re-run all jobs**). The job is idempotent: it skips an existing tag and an existing release,
so a re-run can only complete what is missing. Never delete and re-create a published tag; bump the patch version instead.
