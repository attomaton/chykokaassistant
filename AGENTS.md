# AGENTS.md

Permanent development rule for this repository, for both human contributors
and AI coding agents. For every new feature or meaningful code change:

1. Add or update unit tests that cover the new behavior.
2. Run the full test suite (`pytest -q`).
3. If tests fail, determine whether the issue is in the production code or
   in the test itself, then fix the correct side. Do not weaken assertions,
   skip meaningful tests, or mock away the behavior under test just to force
   a green result.
4. Once the full test suite passes, create a git commit whose message
   clearly describes what changed and why.

Do not create a commit if the test suite is failing. Do not commit secrets,
`.env` files, local credentials, build artifacts, or virtual environments,
and do not bundle unrelated changes into the same commit.

See [README.md](README.md#8-test-locally) for the exact commands to run the
suite and generate a coverage report.
