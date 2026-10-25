#!/usr/bin/env sh
# Build the AIRI stage-web bundle on the host, inject the bootstrap script, and
# stage it for the nginx image. Building on the host keeps the Docker VM small.
set -e
cd "$(dirname "$0")/../.."

if command -v mise >/dev/null 2>&1; then
  PNPM="mise exec -- pnpm"
else
  PNPM="pnpm"
fi

$PNPM -F @proj-airi/stage-web run build
node deploy/local/inject-bootstrap.mjs

rm -rf deploy/local/web-dist
cp -R apps/stage-web/dist deploy/local/web-dist
echo "staged deploy/local/web-dist"
