#!/bin/bash
export FLASK_ENV=prod
cd /file-upload-center
source venv/bin/activate
gunicorn --bind $SERVER_HOST:$PORT --workers 4 --threads 4 app:app