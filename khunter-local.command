#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
exec .venv/bin/python local_server.py "${1:-start}"
