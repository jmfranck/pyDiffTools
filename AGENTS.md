## Agent instructions

- Always run the test suite when code changes, unless explicitly instructed
  otherwise in the task request.
- Do not stub external tools like pandoc or pandoc-crossref in tests.
- Tests may fail due to missing external tools only if the response includes
  the exact Unix command(s) needed to install the missing dependencies so they
  can be added to environment setup scripts.
- Never skip tests for missing external tools. If a dependency is missing,
  allow the test to fail and include the exact install commands in the response.
- Use the pyenv interpreter that is compatible with the conda site-packages:
  `PYENV_VERSION=3.13.8`.
- When installing and testing in this repo, prepend the conda site-packages:
  `PYTHONPATH=/root/conda/lib/python3.13/site-packages`.
- With the two settings above, the install/test flow can be simplified to:
  `PYENV_VERSION=3.13.8 PYTHONPATH=/root/conda/lib/python3.13/site-packages pip install -e . --no-build-isolation`
  then
  `PYENV_VERSION=3.13.8 PYTHONPATH=/root/conda/lib/python3.13/site-packages pytest`.
