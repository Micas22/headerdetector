#!/bin/bash
set -e

# Start the FastAPI server in the background
echo "Starting FastAPI server on port 8000..."
uvicorn api:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# Start the Flask server in the foreground
echo "Starting Flask UI server on port 5000..."
exec gunicorn --workers=2 --threads=8 --bind=0.0.0.0:5000 app:app

# Cleanup on exit
trap "kill $API_PID" EXIT
