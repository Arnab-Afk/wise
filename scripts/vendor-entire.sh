#!/bin/sh
# Copies the host's Entire CLI and plugins into the backend image build context.
# Install them first: curl -fsSL https://entire.io/install.sh | bash && entire plugin install graph
set -e
cd "$(dirname "$0")/../backend"
mkdir -p vendor/bin vendor/share
cp "$HOME/.local/bin/entire" "$HOME/.local/bin/git-remote-entire" vendor/bin/
rm -rf vendor/share/entire && cp -r "$HOME/.local/share/entire" vendor/share/
