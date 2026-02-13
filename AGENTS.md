## Agent instructions

- Always run the test suite when code changes, unless explicitly instructed
  otherwise in the task request.
- Do not stub external tools like pandoc or pandoc-crossref in tests.
- Tests may fail due to missing external tools only if the response includes
  the exact Unix command(s) needed to install the missing dependencies so they
  can be added to environment setup scripts.
- Never skip tests for missing external tools. If a dependency is missing,
  allow the test to fail and include the exact install commands in the response.
- Prefer the conda base environment for installs and tests, so version selection
  is handled by conda activation instead of per-command env vars.
- Recommended flow for test:
  1. source /root/conda/etc/profile.d/conda.sh && conda activate base && python -m pip install -e . --no-build-isolation
	2. source /root/conda/etc/profile.d/conda.sh && conda activate base && python -m pytest
