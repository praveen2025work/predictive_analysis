#!/bin/bash
export FLASK_ENV=uat
cd /file-upload-center
source venv/bin/activate
gunicorn --bind $SERVER_HOST:$PORT app:app