#!/bin/bash
# Commit and push changes using message from commit.txt

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MSG_FILE="$SCRIPT_DIR/commit.txt"

if [ ! -f "$MSG_FILE" ]; then
    echo "Error: $MSG_FILE not found" >&2
    echo "Create commit.txt with your commit message" >&2
    exit 1
fi

if [ ! -s "$MSG_FILE" ]; then
    echo "Error: commit.txt is empty" >&2
    exit 1
fi

cd "$SCRIPT_DIR"

if git diff-index --quiet HEAD --; then
    GIT_EXIT=0
else
    GIT_EXIT=$?
fi

if [ $GIT_EXIT -ne 0 ]; then
    git add -A

    echo ">>> Committing..."
    git commit -F "$MSG_FILE"

    if git diff-index --quiet HEAD -- 2>/dev/null; then
        echo ">>> Nothing to commit"
    else
        echo ">>> Pushing..."
        git push && echo ">>> Done!"
    fi
else
    echo ">>> Nothing to commit"
fi
