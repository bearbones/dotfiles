#!/usr/bin/env bash
# Block staging ephemeral development notes, plans, handoffs, or TODO files
# that belong in GitHub Issues or untracked scratch space rather than VCS.
#
# Override: SKIP=ephemeral-docs git commit

staged=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null)
[[ -z "$staged" ]] && exit 0

found=0

while IFS= read -r file; do
    case "$file" in
        docs/plans/*|docs/handoffs/*|docs/tasks/*|docs/issues/*|docs/superpowers/*|\
        docs/investigations/*|docs/diagnoses/*|docs/design-*.md|docs/*-review.md|\
        docs/*-todos.md|docs/*-proposal.md|dev/NOTES-*.md|tasks/*|roadmap/*|\
        ROADMAP.md|CHARTER.md|milestone-notes.md)
            printf "  \033[31mephemeral-doc\033[0m  %s\n" "$file"
            found=1
            ;;
    esac
done <<< "$staged"

if [[ $found -eq 1 ]]; then
    echo ""
    echo "🚫  pre-commit: ephemeral development notes/plans staged for commit"
    echo "    Policy: temporary work artifacts must stay temporary (scratch/) or"
    echo "    go into GitHub Issues (gh issue create), not version control."
    echo "    Override if intentional: SKIP=ephemeral-docs git commit"
    echo ""
    exit 1
fi

exit 0
