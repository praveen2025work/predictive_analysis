#!/bin/bash
export FLASK_ENV=uat
cd /file-upload-center
source venv/bin/activate
gunicorn --bind 0.0.0.0:3000 app:app
