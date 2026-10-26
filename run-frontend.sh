#!/usr/bin/env bash
# ThreadSmith frontend on :3010, in a second terminal.
set -euo pipefail
cd "$(dirname "$0")/frontend"
npm install
exec npm run dev
