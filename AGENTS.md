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
- Recommended flow:
  1. `source /root/conda/etc/profile.d/conda.sh`
  2. `conda activate base`
  3. `python -m pip install -e . --no-build-isolation`
  4. `python -m pytest`
- If `python -m pytest` fails because pytest is missing in base, install it with:
  `python -m pip install pytest`
