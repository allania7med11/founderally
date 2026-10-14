# How to work on FounderAlly

Read `README.md` first.

## Working in the code

- `backend/` is the Python project (uv, `pyproject.toml`); `web/` is the Next.js app, later. Compose, Makefile
  and `docker/` sit at the root.
- Every API route is under `/api`.
- `make up`, `make test`, `make down` from the root; `uv run ...` from `backend/`.
- A schema change is `make makemigrations m="..."` after `make up && make migrate`, then the generated file is read
  and edited; never a hand-written migration. `make check-migrations` before a commit.

## Writing code: the least a reader must read

Every line costs the reader time, so every line is debt. A coding agent's default is to write more: more code, more
checks, more comments, its own helpers. Here the default is the reverse.

- Reuse what this codebase already has, only when it fits the problem: never bend a problem to fit a pattern.
- Then a standard package. Before writing a helper, name the package or built-in that does it in the report and use
  that: it is maintained, tested and documented. Custom code only when nothing standard fits our need without losing
  what we need, with the reason in one line.
- Write the least that does the job: no code, check or comment that does or says nothing new. Validation at the
  edges (Pydantic models) and type hints are never "nothing new".
- Read in one pass: neither dense (no helper that hides what it does, no unpacking tricks, no call or comprehension
  nested in a call's arguments) nor padded (no comment that repeats the code). Name each step, keep conditions where
  they apply, a short comment only for the reason.
- Import the name, not the module: `from db.passes import read_pass`, never `passes.read_pass`, because
  `passes.read_pass` reads as an object's method and the reader cannot tell a module from a class.
- A prompt is a template file under `backend/prompts/`, versioned by its name, never an f-string in code: the
  version then names everything the model reads.
- KISS before DRY: short, stable repetition stays inline. When the repeated part is long or must change together,
  suggest one shared piece; the owner decides.
- Group by job. Aim for files under 200 lines and functions under 40, so each can be read whole. Past that, split by
  what the code does (the SQL out of the activity, the providers out of the logic) or give the reason; never split
  by line count alone.
- A test ships in the same commit as the code it tests. It asserts what its name claims, plus the check that the bad
  path did not happen, and nothing else.
- Any value a test's assert depends on is passed where the test calls the code; shared fakes may build the objects.
  The more of the system a test runs as a black box, the more it explains: a test whose result is not obvious from
  its name, and every end-to-end test, opens with a docstring naming the input, the expected output and why one
  gives the other, so a reader can predict the result without reading the code inside.

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
