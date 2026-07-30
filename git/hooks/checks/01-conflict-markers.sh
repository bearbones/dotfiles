#!/usr/bin/env bash
# Fail if any staged file contains unresolved merge conflict markers.

staged=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null)
[[ -z "$staged" ]] && exit 0

found=0
while IFS= read -r file; do
    # Read from the index (staged content), not the working tree
    if git show ":$file" 2>/dev/null | grep -qE '^(<{7}|={7}|>{7})'; then
        printf "  \033[31mconflict\033[0m  %s\n" "$file"
        found=1
    fi
done <<< "$staged"

if [[ $found -eq 1 ]]; then
    echo ""
    echo "🚫  pre-commit: unresolved merge conflict markers found"
    echo "    Resolve conflicts before committing."
    echo ""
    exit 1
fi

exit 0
