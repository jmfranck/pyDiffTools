import subprocess
import sys
from pathlib import Path


CHECKER = Path(__file__).parents[1] / ".github/scripts/check_single_use.py"


def run_checker(*paths):
    return subprocess.run(
        [sys.executable, str(CHECKER), *(str(path) for path in paths)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_unit_test_import_counts_as_function_use(tmp_path):
    implementation = tmp_path / "implementation.py"
    test_file = tmp_path / "test_implementation.py"
    implementation.write_text(
        "def helper():\n    return 1\n\n"
        "value = helper()\n"
    )
    test_file.write_text(
        "from implementation import helper\n\n"
        "def test_helper():\n    assert helper() == 1\n"
    )

    result = run_checker(implementation, test_file)

    assert result.returncode == 0, result.stdout + result.stderr


def test_single_use_function_is_reported(tmp_path):
    implementation = tmp_path / "implementation.py"
    implementation.write_text(
        "def helper():\n    return 1\n\n"
        "value = helper()\n"
    )

    result = run_checker(implementation)

    assert result.returncode == 1
    assert "helper" in result.stdout
