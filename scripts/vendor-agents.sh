#!/bin/sh
# Copies the host's Claude Code and Cursor CLIs into the runner image build context.
# Install them first:  curl -fsSL https://claude.ai/install.sh | bash
#                      curl https://cursor.com/install -fsS | bash
set -e
cd "$(dirname "$0")/../backend"
mkdir -p vendor/agents
cp "$(readlink -f "$HOME/.local/bin/claude")" vendor/agents/claude
rm -rf vendor/agents/cursor && cp -r "$(dirname "$(readlink -f "$HOME/.local/bin/agent")")" vendor/agents/cursor
