## Agent instructions

- Always run the test suite when code changes, unless explicitly instructed
  otherwise in the task request.
- Do not stub external tools like pandoc or pandoc-crossref in tests.
- Tests may fail due to missing external tools only if the response includes
  the exact Unix command(s) needed to install the missing dependencies so they
  can be added to environment setup scripts.
- Never skip tests for missing external tools. If a dependency is missing,
  allow the test to fail and include the exact install commands in the response.
- When running tests in this repo, use the simpler maintenance flow:
  `source "${HOME}/conda/etc/profile.d/conda.sh" && conda activate base && pip install -e . && pytest -q -ra`.
- The `-ra` flag is required so skipped tests are reported with reasons.
