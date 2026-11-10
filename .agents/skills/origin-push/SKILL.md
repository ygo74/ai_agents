---
name: origin-push
description: Prepare and push an explicitly requested commit to the current origin work branch, with required Python quality checks.
---

# Push a commit to origin

Use this skill only when the user or an approved plan asks for a commit or
push. Keep the commit limited to the approved change and push only the current
working branch.

## Before committing

1. Check `git status --short --branch`, the current branch, upstream, and the
   full staged and unstaged diff. Keep unrelated changes, generated test
   results, secrets, and parent-directory files out of the commit. Do not push
   directly to `main` or `master`.
2. If any changed or untracked file has a `.py` extension, run the repository's
   Python quality gates before committing. Use the Python 3.12 development
   environment. If it is not already set up, follow the dependency setup in the
   `Quality` workflow in `.github/workflows/quality.yml`, including
   `python -m scripts.install --env dev`. Then run:

   ```bash
   python -m ruff check .
   python -m mypy
   python -m pytest --junitxml=test-results.xml
   ```

   Ruff and pytest are mandatory for every Python change, including test
   scripts. Mypy is also part of this repository's Python CI gate. If any
   check fails, do not commit or push; fix the cause and rerun the required
   checks. Do not skip a check because it is slow or because the changed file
   is under `tests/`.
3. Run `git diff --check`, stage only files in scope, inspect
   `git diff --cached`, and run `git diff --cached --check`. Commit with a
   concise message describing the change.

## Push and verify

1. Confirm the commit is on the approved working branch and that its upstream
   is `origin`. For a branch that has no upstream, push it with
   `git push --set-upstream origin <branch-name>`; otherwise use
   `git push origin <branch-name>`.
2. Never force-push, rewrite shared history, merge, or push a release tag as
   part of this procedure. If the remote rejects the push, inspect the remote
   state and report or resolve the divergence without force-pushing.
3. After a successful push, check `git status --short --branch` and inspect
   the GitHub Actions result for the pushed commit when a workflow was
   triggered. If CI fails, report the failing check and fix it in a new commit
   only after rerunning the required local checks. Do not claim CI passed when
   no run was triggered or its result is unavailable.
