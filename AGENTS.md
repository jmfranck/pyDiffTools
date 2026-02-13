## Agent instructions

- Always run the test suite when code changes, unless explicitly instructed
  otherwise in the task request.
- Do not stub external tools like pandoc or pandoc-crossref in tests.
- Tests may fail due to missing external tools only if the response includes
  the exact Unix command(s) needed to install the missing dependencies so they
  can be added to environment setup scripts.
- Never skip tests for missing external tools. If a dependency is missing,
  allow the test to fail and include the exact install commands in the response.
- When running tests in this repo, activate the conda environment and run pytest
  through conda's Python while prepending both the pyenv pytest path and conda
  site-packages: use
  `source "${HOME}/conda/etc/profile.d/conda.sh" && conda activate base && PYTHONPATH=/root/.pyenv/versions/3.12.12/lib/python3.12/site-packages:/root/conda/lib/python3.13/site-packages /root/conda/bin/python -m pytest`.
