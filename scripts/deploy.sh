#!/usr/bin/env bash
set -e
git pull
docker compose up -d --build
docker image prune -f
docker compose logs --tail 20