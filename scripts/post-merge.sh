#!/bin/bash
set -e

echo "==> Installing backend dependencies"
pip install -q -r backend/requirements.txt

echo "==> Running database migrations"
cd backend && alembic upgrade head
cd ..

echo "==> Installing frontend dependencies"
cd frontend && npm install --legacy-peer-deps --silent
cd ..

echo "==> Post-merge setup complete"
