# File Upload Center API

A Flask-based RESTful API for secure file uploads, designed to work with a custom UI that provides authenticated user IDs via headers. Access is restricted to specific UI origins using CORS.

## Overview
This API supports file uploads, sharing, downloading, and listing, with user identification via the `X-User-Id` header. It includes configurable server host and port, automated setup (directories, permissions, database), and CORS to restrict access to allowed UI origins. All endpoints are documented in `endpoints.md`.

## Setup Instructions
1. **Create Folder Structure and Files**:
   - Create the following structure in `C:\file-upload-center`:
     ```
     C:\file-upload-center\
     ├── app.py
     ├── config.py
     ├── endpoints.md
     ├── requirements.txt
     ├── scripts\
     │   ├── run_dev.ps1
     │   ├── run_uat.sh
     │   ├── run_prod.sh
     │   ├── test_api.py
     ├── env\
     │   ├── dev.env
     │   ├── uat.env
     │   ├── prod.env
     └── README.md
     ```
   - Copy the provided file contents into each file using a text editor (e.g., VS Code).

2. **Install Dependencies** (Only Manual Step):
   ```powershell
   cd C:\file-upload-center
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt