# Agent Instructions

- Always run the full test suite.  Generally, it should not be necessary to install any dependenencies that are not listed in the toml file.
	- If you allege other dependencies, you are doing something wrong!! See the recommended flow below.
- Recommended flow for test INSIDE WEB/CLOUD CONTAINER:
  1. source /root/conda/etc/profile.d/conda.sh && conda activate base && python -m pip install -e . --no-build-isolation
	2. source /root/conda/etc/profile.d/conda.sh && conda activate base && python -m pytest
- Recommended flow for test LOCALLY (inside vscode IDE):
	1. DO NOT create a .venv directory inside the repo!!
  2. Run tests with: ~/base/bin/python -m pytest
	3. Note that *all required packages are already installed in the base
		 environment* and you are NOT allowed to mess with the base environment.
		 Nor should you need to!
- When refactoring, check for functions that are only used once. Prefer to
  move that logic back in place rather than keeping a single-use helper.
	Use vim fold markers, as described next.
- When inlining substantial one-off logic, surround it with vim fold markers
	like `# {{{ description of code purpose` and `# }}}`.
