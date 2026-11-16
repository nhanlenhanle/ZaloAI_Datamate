#!/usr/bin/env bash
# Fixed entry point required by Zalo AI Challenge 2026 DataMate Docker Submission Guide (/code/predict.sh).
# Reads /data, writes /result/submission.jsonl and /result/logs/logs.jsonl.
exec bash /app/run.sh "$@"
