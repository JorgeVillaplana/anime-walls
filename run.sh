#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
cd backend
uvicorn main:app --reload --port 8000