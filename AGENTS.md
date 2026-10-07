# How to work on FounderAlly

Read `README.md` first.

## Working in the code

- `backend/` is the Python project (uv, `pyproject.toml`); `web/` is the Next.js app, later. Compose, Makefile
  and `docker/` sit at the root.
- Every API route is under `/api`.
- `make up`, `make test`, `make down` from the root; `uv run ...` from `backend/`.
- Before writing a helper, name the package or built-in that does it and use that; custom code only when nothing
  standard fits, with the reason in one line.
- A test ships in the same commit as the code it tests.

## Conduct

Whoever works here, a person or any coding agent: the owner decides, you draft, ask and report. Nothing is obvious enough to do unasked.

- One request, one action. Do not move, edit, commit or delete what was not named. Stop after the step and report.
- Unclear request: one short question, nothing else.
- Check before asking: search the docs and the git log for an existing decision. Found: apply it and cite it. Not
  found: ask once.
- A draft goes into its file, not the terminal.
- Give the command; do not run the app. Run only on "run" or "fix it".
- Terse. Facts, not commentary. No duplication.
- The owner runs git. One branch per ticket off `develop`, `feature/FA-N-<what it does>`; every commit message is one
  line, plain words, prefixed `FA-N: `; the pull request goes to `develop` by rebase merge, never squash or merge
  commit.
