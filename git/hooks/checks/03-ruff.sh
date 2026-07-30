#!/usr/bin/env bash
# Run ruff check and ruff format --check on staged Python files.
# Silently skips if ruff is not in PATH.
#
# Override: SKIP=ruff git commit

command -v ruff &>/dev/null || exit 0

staged_py=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null | grep '\.py$' || true)
[[ -z "$staged_py" ]] && exit 0

failed=0

# ruff check (linting)
# Feed the list as args; run from the repo root so pyproject.toml / .ruff.toml are found.
if ! ruff check --quiet $staged_py 2>/dev/null; then
    echo ""
    echo "🚫  pre-commit: ruff check failed"
    ruff check $staged_py
    failed=1
fi

# ruff format --check (formatting)
if ! ruff format --check --quiet $staged_py 2>/dev/null; then
    echo ""
    echo "🚫  pre-commit: ruff format check failed"
    ruff format --check $staged_py
    echo "    Fix with: ruff format $staged_py"
    failed=1
fi

[[ $failed -eq 1 ]] && exit 1
exit 0
