#!/usr/bin/env bash
# Shared Python runtime discovery for Chuanxu release packages.
#
# The project requires CPython 3.14 or newer.  A package must not depend on a
# vendor-specific installation path: operators may use the system package,
# Linuxbrew, pyenv, or an explicitly provisioned runtime.  This helper is
# sourced by shell entrypoints and can also be executed to print the selected
# interpreter.

cx_python_version() {
    local candidate="$1"
    cx_python_exec "$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null
}

cx_python_supported() {
    local candidate="$1"
    cx_python_exec "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 14) else 1)' >/dev/null 2>&1
}

cx_python_runtime_libdir() {
    # Relocatable/isolated Python builds often keep libpython beside the
    # executable without registering that directory with ldconfig.  The
    # sandbox used for release verification exposes exactly this layout.
    local candidate="$1"
    local resolved prefix libdir
    # PATH entries and operator-provided values may be symbolic links.  Find
    # libpython beside the real installation, while preserving the selected
    # executable path for the caller.
    resolved="$(readlink -f -- "$candidate" 2>/dev/null || printf '%s' "$candidate")"
    prefix="$(cd "$(dirname "$resolved")/.." 2>/dev/null && pwd)" || return 0
    for libdir in "$prefix/lib" "$prefix/lib64"; do
        if compgen -G "$libdir/libpython*.so*" >/dev/null 2>&1; then
            printf '%s\n' "$libdir"
            return 0
        fi
    done
}

cx_python_exec() {
    local candidate="$1"
    shift
    local libdir
    libdir="$(cx_python_runtime_libdir "$candidate" || true)"
    if [[ -n "$libdir" ]]; then
        LD_LIBRARY_PATH="$libdir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
            "$candidate" "$@"
    else
        "$candidate" "$@"
    fi
}

cx_prepare_python_environment() {
    local candidate="$1"
    local libdir
    libdir="$(cx_python_runtime_libdir "$candidate" || true)"
    [[ -n "$libdir" ]] || return 0
    case ":${LD_LIBRARY_PATH:-}:" in
        *:"$libdir":*) ;;
        *) export LD_LIBRARY_PATH="$libdir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;;
    esac
}

cx_run_python() {
    # Command substitution runs functions in a subshell, so callers that use
    # `PYTHON_BIN="$(cx_resolve_python)"` must prepare the environment again
    # before executing the selected interpreter.  This wrapper keeps that
    # requirement in one place for scripts and operators.
    local candidate="${1:-}"
    if [[ -z "$candidate" ]]; then
        echo "[python] cx_run_python requires an interpreter path" >&2
        return 2
    fi
    shift
    cx_prepare_python_environment "$candidate"
    "$candidate" "$@"
}

cx_python_absolute_path() {
    local candidate="$1"
    if [[ "$candidate" != */* ]]; then
        command -v "$candidate" 2>/dev/null || return 1
        return 0
    fi
    if [[ "$candidate" = /* ]]; then
        printf '%s\n' "$candidate"
        return 0
    fi
    local directory basename
    directory="$(cd "$(dirname "$candidate")" 2>/dev/null && pwd)" || return 1
    basename="$(basename "$candidate")"
    printf '%s/%s\n' "$directory" "$basename"
}

cx_validate_explicit_python() {
    local candidate="$1"
    local resolved
    resolved="$(cx_python_absolute_path "$candidate")" || {
        echo "[python] executable was not found: $candidate" >&2
        return 1
    }
    if [[ ! -x "$resolved" ]]; then
        echo "[python] executable is not accessible or executable: $candidate" >&2
        return 1
    fi
    if ! cx_python_supported "$resolved"; then
        local version
        version="$(cx_python_version "$resolved" || printf 'unknown')"
        echo "[python] Python 3.14+ is required; $candidate reports $version" >&2
        return 1
    fi
    cx_prepare_python_environment "$resolved"
    printf '%s\n' "$resolved"
}

cx_resolve_python() {
    # An explicit value is authoritative.  Falling back after an invalid
    # explicit value would hide a deployment error and can select an older
    # interpreter from PATH.
    local explicit="${1:-${PYTHON_BIN:-}}"
    if [[ -n "$explicit" ]]; then
        cx_validate_explicit_python "$explicit"
        return $?
    fi

    local path_dir candidate basename version major minor
    local best="" best_major=-1 best_minor=-1
    local -a path_dirs
    IFS=':' read -r -a path_dirs <<< "${PATH:-}"
    declare -A seen=()

    for path_dir in "${path_dirs[@]}"; do
        [[ -n "$path_dir" ]] || path_dir="."
        for candidate in "$path_dir"/python3 "$path_dir"/python3.*; do
            [[ -x "$candidate" ]] || continue
            basename="$(basename "$candidate")"
            [[ "$basename" == "python3" || "$basename" =~ ^python3\.[0-9]+$ ]] || continue
            candidate="$(cx_python_absolute_path "$candidate")" || continue
            [[ -n "${seen[$candidate]+yes}" ]] && continue
            seen["$candidate"]=1
            version="$(cx_python_version "$candidate" || true)"
            [[ "$version" =~ ^([0-9]+)\.([0-9]+)\. ]] || continue
            major="${BASH_REMATCH[1]}"
            minor="${BASH_REMATCH[2]}"
            (( major == 3 && minor >= 14 )) || continue
            if (( major > best_major || (major == best_major && minor > best_minor) )); then
                best="$candidate"
                best_major="$major"
                best_minor="$minor"
            fi
        done
    done

    if [[ -z "$best" ]]; then
        echo "[python] no executable Python 3.14+ interpreter was found on PATH" >&2
        echo "[python] set PYTHON_BIN to an accessible Python 3.14+ executable" >&2
        return 1
    fi
    cx_prepare_python_environment "$best"
    printf '%s\n' "$best"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    cx_resolve_python "$@"
fi
