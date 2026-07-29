import os
import subprocess
import sys
from pathlib import Path


_TEST_ROOT = Path(__file__).resolve().parents[1]
HELPER = (
    _TEST_ROOT / "scripts" / "python_runtime.sh"
    if (_TEST_ROOT / "scripts" / "python_runtime.sh").is_file()
    else _TEST_ROOT / "python_runtime.sh"
)


def _run(command: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        ["bash", "-c", f"source {HELPER!s}; {command}"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_explicit_python_bin_is_validated_and_resolved():
    result = _run('cx_resolve_python "$PYTHON_BIN"', PYTHON_BIN=sys.executable)

    assert result.returncode == 0
    assert Path(result.stdout.strip()).resolve() == Path(sys.executable).resolve()


def test_explicit_old_python_is_rejected():
    result = _run(
        'cx_resolve_python "$PYTHON_BIN"',
        PYTHON_BIN="/usr/bin/python3.6",
    )

    assert result.returncode != 0
    assert "Python 3.14+" in result.stderr


def test_unreachable_explicit_path_does_not_fallback():
    result = _run(
        'cx_resolve_python "$PYTHON_BIN"',
        PYTHON_BIN="/tmp/python3.14-not-installed",
    )

    assert result.returncode != 0
    assert "executable" in result.stderr


def test_relocatable_python_gets_adjacent_libpython_path():
    """The resolver must support a visible Python tree outside ldconfig."""
    runtime_value = os.environ.get("CX_TEST_RELOCATABLE_PYTHON", "")
    if not runtime_value:
        return
    runtime = Path(runtime_value)
    result = _run(
        'resolved="$(cx_resolve_python "$PYTHON_BIN")"; '
        '[[ "$resolved" = "$PYTHON_BIN" ]]; '
        'cx_run_python "$resolved" -c "import sys; print(sys.version_info[:2])"',
        PYTHON_BIN=str(runtime),
    )
    assert result.returncode == 0, result.stderr
    assert "(3, 14)" in result.stdout


def test_relocatable_python_can_run_after_command_substitution():
    """The public wrapper must preserve libpython setup across subshells."""
    runtime_value = os.environ.get("CX_TEST_RELOCATABLE_PYTHON", "")
    if not runtime_value:
        return
    runtime = Path(runtime_value)
    result = _run(
        'resolved="$(cx_resolve_python "$PYTHON_BIN")"; '
        'cx_run_python "$resolved" -c "import sys; print(sys.version_info[:2])"',
        PYTHON_BIN=str(runtime),
    )
    assert result.returncode == 0, result.stderr
    assert "(3, 14)" in result.stdout
