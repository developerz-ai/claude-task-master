#!/usr/bin/env bash
# Setup git hooks for the project
# Run this after cloning the repository

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"
SOURCE_HOOKS_DIR="$SCRIPT_DIR/hooks"

echo "Setting up git hooks..."

# Ensure .git/hooks directory exists
mkdir -p "$HOOKS_DIR"

# Install pre-commit hook
if [ -f "$SOURCE_HOOKS_DIR/pre-commit" ]; then
    cp "$SOURCE_HOOKS_DIR/pre-commit" "$HOOKS_DIR/pre-commit"
    chmod +x "$HOOKS_DIR/pre-commit"
    echo "  Installed: pre-commit (runs the full gate: bin/check)"
fi

echo ""
echo "Git hooks installed successfully!"
echo "The pre-commit hook runs the full gate (bin/check) and blocks the commit when it fails."
echo "It runs the same gate as .githooks/pre-commit (git config core.hooksPath .githooks)."
