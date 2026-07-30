#!/usr/bin/env bash
# Fail if staged files contain common debug statements that don't belong in commits.
# Checks staged content (the index), not the working tree.
#
# Override: SKIP=debug-leftovers git commit

staged=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null)
[[ -z "$staged" ]] && exit 0

found=0

check() {
    local file="$1" pattern="$2"
    local hits
    hits=$(git show ":$file" 2>/dev/null | grep -nF "$pattern" | head -3)
    if [[ -n "$hits" ]]; then
        printf "  \033[31mdebug\033[0m  %s  (%s)\n" "$file" "$pattern"
        while IFS= read -r line; do
            printf "         %s\n" "$line"
        done <<< "$hits"
        found=1
    fi
}

while IFS= read -r file; do
    [[ -f "$file" ]] || continue
    case "$file" in
        *.py)
            check "$file" "breakpoint()"
            check "$file" "pdb.set_trace()"
            check "$file" "import pdb; pdb.set_trace"
            ;;
        *.js|*.ts|*.tsx|*.jsx|*.mjs|*.cjs)
            check "$file" "debugger;"
            check "$file" "console.log("
            ;;
    esac
done <<< "$staged"

if [[ $found -eq 1 ]]; then
    echo ""
    echo "🚫  pre-commit: debug statements found in staged files"
    echo "    Remove them or override with: SKIP=debug-leftovers git commit"
    echo ""
    exit 1
fi

exit 0
