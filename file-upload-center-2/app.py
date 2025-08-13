from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
from datetime import datetime
import os
import sqlite3
import logging
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Load environment variables from specified .env file (e.g., dev.env, uat.env)
env_file = os.getenv('ENV_FILE', 'dev.env')
load_dotenv(env_file)
logging.debug(f'Loaded environment variables from {env_file}')

# Config variables from .env
ALLOWED_EXTENSIONS = os.getenv('ALLOWED_EXTENSIONS', '').split(',') if os.getenv('ALLOWED_EXTENSIONS') else set()
UPLOAD_BASE_DIR = os.getenv('UPLOAD_BASE_DIR', r'C:\shared')
DB_PATH = os.getenv('DB_PATH', r'C:\shared\uploads.db')
LOG_FILE = os.getenv('LOG_FILE', r'C:\logs\app.log')
SERVER_HOST = os.getenv('SERVER_HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 3000))
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', 'http://localhost:3001,http://127.0.0.1:3001').split(',')
USERINFO_API_URL = os.getenv('USERINFO_API_URL', 'http://test/api')
USE_MOCK_USERINFO = os.getenv('USE_MOCK_USERINFO', 'False') == 'True'
MAIL_HOST = os.getenv('MAIL_HOST', 'smtp.example.com')
MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
MAIL_FROM = os.getenv('MAIL_FROM', 'no-reply@example.com')
API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:3000')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG')
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# Initialize Flask app
app = Flask(__name__)

# Setup CORS
cors = CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})
logging.debug('CORS initialized with allowed origins: %s', ALLOWED_ORIGINS)

# Setup logging
try:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    logging.debug('Logging initialized successfully')
except Exception as e:
    logging.error(f'Failed to initialize logging: {e}')

# Automate directory and permissions setup
def setup_directories():
    try:
        os.makedirs(UPLOAD_BASE_DIR, exist_ok=True)
        os.system(f'icacls "{UPLOAD_BASE_DIR}" /grant "{os.environ.get("USERNAME")}:(OI)(CI)M"')
        logging.debug(f'Created and set permissions for UPLOAD_BASE_DIR: {UPLOAD_BASE_DIR}')

        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        if not os.path.exists(DB_PATH):
            open(DB_PATH, 'a').close()
            os.system(f'icacls "{DB_PATH}" /grant "{os.environ.get("USERNAME")}:(OI)(CI)M"')
            logging.debug(f'Created and set permissions for DB_PATH: {DB_PATH}')

        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        os.system(f'icacls "{os.path.dirname(LOG_FILE)}" /grant "{os.environ.get("USERNAME")}:(OI)(CI)M"')
        logging.debug(f'Created and set permissions for LOG_FILE directory: {os.path.dirname(LOG_FILE)}')
    except Exception as e:
        logging.error(f'Failed to set up directories: {e}')

# Initialize SQLite database
def init_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    updated_by TEXT NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS application_locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id INTEGER NOT NULL,
                    location_name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    FOREIGN KEY(application_id) REFERENCES applications(id),
                    UNIQUE(application_id, location_name),
                    UNIQUE(application_id, path)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    upload_time TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    file_location TEXT NOT NULL,
                    application_id INTEGER,
                    location_id INTEGER,
                    download_count INTEGER DEFAULT 0,
                    FOREIGN KEY(application_id) REFERENCES applications(id),
                    FOREIGN KEY(location_id) REFERENCES application_locations(id)
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON uploads(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_upload_time ON uploads(upload_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_filename ON uploads(filename)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_application_id ON uploads(application_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_location_id ON uploads(location_id)')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS shared_uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    upload_id INTEGER NOT NULL,
                    shared_by TEXT NOT NULL,
                    shared_with TEXT NOT NULL,
                    shared_time TEXT NOT NULL,
                    FOREIGN KEY(upload_id) REFERENCES uploads(id)
                )
            ''')
            conn.commit()
            logging.debug('Initialized SQLite database with indexes and shared_uploads table')
    except Exception as e:
        logging.error(f'Failed to initialize database: {e}')

# Middleware to check user_id in headers
def require_user_id(func):
    def wrapper(*args, **kwargs):
        user_id = request.headers.get('X-User-Id')
        if not user_id:
            logging.error('Missing X-User-Id header')
            return jsonify({
                'status': 'error',
                'message': 'Missing user ID in headers'
            }), 401
        request.user_id = user_id
        return func(*args, **kwargs)
    wrapper.__name__ = func.__name__
    return wrapper

# Check allowed file extensions
def allowed_file(filename):
    if not ALLOWED_EXTENSIONS:
        return True
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Validate file location
def validate_file_location(location):
    if not location.startswith(UPLOAD_BASE_DIR):
        logging.error('File location does not start with %s: %s', UPLOAD_BASE_DIR, location)
        return False
    try:
        if not os.path.exists(location):
            os.makedirs(location)
            os.system(f'icacls "{location}" /grant "{os.environ.get("USERNAME")}:(OI)(CI)M"')
            logging.debug('Created directory: %s', location)
        return os.access(location, os.W_OK | os.R_OK)
    except Exception as e:
        logging.error('Invalid file location %s: %s', location, str(e))
        return False

# Fetch user info from external API or mock
def get_user_info(userid):
    if USE_MOCK_USERINFO:
        logging.debug('Using mock user info for userid: %s', userid)
        return {
            "userConfigs": [
                {
                    "id": 0,
                    "displayName": f"Mock User {userid}",
                    "username": "System.DirectoryServices.ResultPropertyValueCollection",
                    "active": null,
                    "createdBy": null,
                    "action": null,
                    "email": f"{userid}@example.com"
                }
            ]
        }
    try:
        url = f"{USERINFO_API_URL}/{userid}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if "userConfigs" in data and len(data["userConfigs"]) > 0:
                logging.debug('Fetched user info for %s: %s', userid, data)
                return data
            else:
                logging.error('No user config found for %s', userid)
                return None
        else:
            logging.error('Failed to fetch user info for %s: status=%s', userid, response.status_code)
            return None
    except Exception as e:
        logging.error('Error fetching user info for %s: %s', userid, str(e))
        return None

# Config endpoint
@app.route('/api/config', methods=['GET'])
def get_config_info():
    return jsonify({
        'status': 'success',
        'data': {
            'allowed_extensions': list(ALLOWED_EXTENSIONS) if ALLOWED_EXTENSIONS else []
        }
    }), 200

# User info endpoint
@app.route('/api/userinfo/<userid>', methods=['GET'])
def get_userinfo(userid):
    user_info = get_user_info(userid)
    if user_info:
        return jsonify(user_info), 200
    return jsonify({
        'status': 'error',
        'message': 'User not found'
    }), 404

# Create application endpoint
@app.route('/api/applications', methods=['POST'])
@require_user_id
def create_application():
    user_id = request.user_id
    logging.debug('User %s creating application', user_id)
    name = request.json.get('name')
    if not name:
        logging.error('Missing name for application')
        return jsonify({
            'status': 'error',
            'message': 'Name is required'
        }), 400

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM applications WHERE name = ?', (name,))
            if cursor.fetchone():
                logging.error('Application name %s already exists', name)
                return jsonify({
                    'status': 'error',
                    'message': 'Application name already exists'
                }), 400

            cursor.execute('INSERT INTO applications (name, updated_by) VALUES (?, ?)', (name, user_id))
            application_id = cursor.lastrowid
            conn.commit()
            logging.debug('Created application %d: %s by %s', application_id, name, user_id)
        return jsonify({
            'status': 'success',
            'data': {
                'application_id': application_id,
                'name': name,
                'updated_by': user_id
            }
        }), 201
    except sqlite3.IntegrityError:
        logging.error('Application name %s already exists', name)
        return jsonify({
            'status': 'error',
            'message': 'Application name already exists'
        }), 400
    except Exception as e:
        logging.error('Error creating application: %s', str(e))
        return jsonify({
            'status': 'error',
            'message': 'Database error'
        }), 500

# List applications endpoint
@app.route('/api/applications', methods=['GET'])
@require_user_id
def list_applications():
    user_id = request.user_id
    logging.debug('User %s listing applications', user_id)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, updated_by FROM applications ORDER BY name')
            applications = [{'id': row[0], 'name': row[1], 'updated_by': row[2]} for row in cursor.fetchall()]
        return jsonify({
            'status': 'success',
            'data': applications
        }), 200
    except Exception as e:
        logging.error('Error listing applications: %s', str(e))
        return jsonify({
            'status': 'error',
            'message': 'Database error'
        }), 500

# Add location to application endpoint
@app.route('/api/applications/<int:application_id>/locations', methods=['POST'])
@require_user_id
def add_location(application_id):
    user_id = request.user_id
    logging.debug('User %s adding location to application %d', user_id, application_id)
    location_name = request.json.get('location_name')
    path = request.json.get('path')
    if not location_name or not path:
        logging.error('Missing location_name or path')
        return jsonify({
            'status': 'error',
            'message': 'Location name and path are required'
        }), 400

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM applications WHERE id = ?', (application_id,))
            if not cursor.fetchone():
                logging.error('Application %d not found', application_id)
                return jsonify({
                    'status': 'error',
                    'message': 'Application not found'
                }), 404

            cursor.execute(
                'SELECT id FROM application_locations WHERE application_id = ? AND (location_name = ? OR path = ?)',
                (application_id, location_name, path)
            )
            if cursor.fetchone():
                logging.error('Location name %s or path %s already exists for application %d', location_name, path, application_id)
                return jsonify({
                    'status': 'error',
                    'message': 'Location name or path already exists for this application'
                }), 400

            cursor.execute(
                'INSERT INTO application_locations (application_id, location_name, path, updated_by) VALUES (?, ?, ?, ?)',
                (application_id, location_name, path, user_id)
            )
            location_id = cursor.lastrowid
            conn.commit()
            logging.debug('Added location %d to application %d: %s - %s by %s', location_id, application_id, location_name, path, user_id)
        return jsonify({
            'status': 'success',
            'data': {
                'location_id': location_id,
                'application_id': application_id,
                'location_name': location_name,
                'path': path,
                'updated_by': user_id
            }
        }), 201
    except sqlite3.IntegrityError:
        logging.error('Location name %s or path %s already exists for application %d', location_name, path, application_id)
        return jsonify({
            'status': 'error',
            'message': 'Location name or path already exists for this application'
        }), 400
    except Exception as e:
        logging.error('Error adding location: %s', str(e))
        return jsonify({
            'status': 'error',
            'message': 'Database error'
        }), 500

# List locations for application endpoint
@app.route('/api/applications/<int:application_id>/locations', methods=['GET'])
@require_user_id
def list_locations(application_id):
    user_id = request.user_id
    logging.debug('User %s listing locations for application %d', user_id, application_id)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, location_name, path, updated_by FROM application_locations WHERE application_id = ? ORDER BY location_name', (application_id,))
            locations = [{'id': row[0], 'location_name': row[1], 'path': row[2], 'updated_by': row[3]} for row in cursor.fetchall()]
        return jsonify({
            'status': 'success',
            'data': locations
        }), 200
    except Exception as e:
        logging.error('Error listing locations: %s', str(e))
        return jsonify({
            'status': 'error',
            'message': 'Database error'
        }), 500

# Upload file endpoint
@app.route('/api/upload', methods=['POST'])
@require_user_id
def upload_file():
    user_id = request.user_id
    logging.debug('User %s attempting file upload', user_id)
    if 'file' not in request.files or 'application_id' not in request.form or 'location_id' not in request.form:
        logging.error('Missing file, application_id, or location_id')
        return jsonify({
            'status': 'error',
            'message': 'Missing file, application_id, or location_id'
        }), 400

    file = request.files['file']
    application_id = request.form['application_id']
    location_id = request.form['location_id']
    additional_path = request.form.get('additional_path', '')

    if file.filename == '':
        logging.error('No file selected')
        return jsonify({
            'status': 'error',
            'message': 'No file selected'
        }), 400

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT path FROM application_locations WHERE id = ? AND application_id = ?', (location_id, application_id))
            result = cursor.fetchone()
            if not result:
                logging.error('Invalid application_id %s or location_id %s', application_id, location_id)
                return jsonify({
                    'status': 'error',
                    'message': 'Invalid application or location'
                }), 400
            base_path = result[0]

        file_location = os.path.join(base_path, additional_path) if additional_path else base_path

        if not validate_file_location(file_location):
            logging.error('Invalid or inaccessible file location: %s', file_location)
            return jsonify({
                'status': 'error',
                'message': 'Invalid or inaccessible file location'
            }), 400

        if file and allowed_file(file.filename):
            if file.content_length and file.content_length > MAX_FILE_SIZE:
                logging.error('File too large: %s', file.filename)
                return jsonify({
                    'status': 'error',
                    'message': 'File too large'
                }), 400

            timestamp = str(datetime.now().timestamp()).replace('.', '')
            name, ext = os.path.splitext(file.filename)
            filename = secure_filename(f"{name}_{timestamp}{ext}")
            file_path = os.path.join(file_location, filename)
            file.save(file_path)
            logging.debug('Saved file %s to %s', filename, file_path)

            try:
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        'INSERT INTO uploads (filename, size, upload_time, user_id, file_location, application_id, location_id, download_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                        (filename, os.path.getsize(file_path), datetime.now().isoformat(), user_id, file_location, application_id, location_id, 0)
                    )
                    upload_id = cursor.lastrowid
                    conn.commit()
                    logging.debug('Logged upload to database: %s by %s at %s', filename, user_id, file_location)
                return jsonify({
                    'status': 'success',
                    'data': {
                        'upload_id': upload_id,
                        'filename': filename,
                        'size': os.path.getsize(file_path),
                        'upload_time': datetime.now().isoformat(),
                        'file_location': file_location
                    }
                }), 201
            except Exception as e:
                logging.error('Error saving to database: %s', str(e))
                return jsonify({
                    'status': 'error',
                    'message': 'Database error'
                }), 500
        else:
            logging.error('Invalid file type: %s', file.filename)
            return jsonify({
                'status': 'error',
                'message': 'Invalid file type'
            }), 400
    except Exception as e:
        logging.error('Error in upload process: %s', str(e))
        return jsonify({
            'status': 'error',
            'message': 'Server error'
        }), 500

# Share file endpoint with HTML email
@app.route('/api/share/<int:upload_id>', methods=['POST'])
@require_user_id
def share_file(upload_id):
    user_id = request.user_id
    logging.debug('User %s attempting to share upload %d', user_id, upload_id)
    shared_with = request.json.get('shared_with')
    send_email = request.json.get('send_email', False)
    if not shared_with:
        logging.error('No user ID provided for sharing')
        return jsonify({
            'status': 'error',
            'message': 'Please provide a user ID to share with'
        }), 400

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT u.filename, u.size, u.upload_time, u.file_location, u.application_id, u.location_id, a.name, l.location_name '
                'FROM uploads u '
                'JOIN applications a ON u.application_id = a.id '
                'JOIN application_locations l ON u.location_id = l.id '
                'WHERE u.id = ? AND u.user_id = ?',
                (upload_id, user_id)
            )
            upload = cursor.fetchone()
            if not upload:
                logging.error('Upload %d not found or not owned by %s', upload_id, user_id)
                return jsonify({
                    'status': 'error',
                    'message': 'Upload not found or not owned'
                }), 404

            filename, size, upload_time, file_location, application_id, location_id, application_name, location_name = upload

            cursor.execute(
                'INSERT INTO shared_uploads (upload_id, shared_by, shared_with, shared_time) VALUES (?, ?, ?, ?)',
                (upload_id, user_id, shared_with, datetime.now().isoformat())
            )
            conn.commit()
            logging.debug('Shared upload %d with %s', upload_id, shared_with)

        if send_email:
            sender_info = get_user_info(user_id)
            recipient_info = get_user_info(shared_with)
            sender_display_name = sender_info["userConfigs"][0]["displayName"] if sender_info and sender_info["userConfigs"] else user_id
            recipient_email = recipient_info["userConfigs"][0]["email"] if recipient_info and recipient_info["userConfigs"] else None
            recipient_display_name = recipient_info["userConfigs"][0]["displayName"] if recipient_info and recipient_info["userConfigs"] else shared_with

            if recipient_email:
                email_body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; color: #333; line-height: 1.6; }}
    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
    .header {{ background-color: #2a73b2; color: white; padding: 10px; text-align: center; border-radius: 5px 5px 0 0; }}
    .content {{ padding: 20px; background-color: #f9f9f9; }}
    .button {{ display: inline-block; padding: 10px 20px; background-color: #2a73b2; color: white; text-decoration: none; border-radius: 5px; }}
    .footer {{ text-align: center; font-size: 12px; color: #777; margin-top: 20px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h2>File Shared with You</h2>
    </div>
    <div class="content">
      <p>Hello {recipient_display_name},</p>
      <p>{sender_display_name} has shared a file with you via the File Upload Center.</p>
      <h3>File Details</h3>
      <ul>
        <li><strong>Filename:</strong> {filename}</li>
        <li><strong>Application:</strong> {application_name}</li>
        <li><strong>Folder:</strong> {location_name} ({file_location})</li>
        <li><strong>Size:</strong> {size / 1024:.2f} KB</li>
        <li><strong>Uploaded:</strong> {upload_time}</li>
      </ul>
      <p>
        <a href="{API_BASE_URL}/api/download/{filename}" class="button">Download File</a>
      </p>
      <p>Please contact the sender for any questions.</p>
    </div>
    <div class="footer">
      <p>File Upload Center Team</p>
    </div>
  </div>
</body>
</html>
"""
                msg = MIMEMultipart()
                msg['Subject'] = 'File Shared with You - File Upload Center'
                msg['From'] = MAIL_FROM
                msg['To'] = recipient_email
                msg.attach(MIMEText(email_body, 'html'))

                try:
                    with smtplib.SMTP(MAIL_HOST, MAIL_PORT) as server:
                        server.starttls()
                        server.login(MAIL_USERNAME, MAIL_PASSWORD)
                        server.sendmail(MAIL_FROM, [recipient_email], msg.as_string())
                    logging.debug('Sent email to %s for share %d', recipient_email, upload_id)
                except Exception as e:
                    logging.error('Error sending email to %s: %s', recipient_email, str(e))
            else:
                logging.error('No email found for user %s', shared_with)

        return jsonify({
            'status': 'success',
            'message': f'Shared upload {upload_id} with {shared_with} successfully'
        }), 200
    except Exception as e:
        logging.error('Error sharing file: %s', str(e))
        return jsonify({
            'status': 'error',
            'message': 'Database error'
        }), 500

# Fetch user uploads with filters
def get_user_uploads(user_id, from_date=None, to_date=None, search_query=None, application_id=None, location_id=None):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            base_conditions = []
            params = []
            
            if from_date:
                from_datetime = f"{from_date}T00:00:00"
                base_conditions.append("u.upload_time >= ?")
                params.append(from_datetime)
            
            if to_date:
                to_datetime = f"{to_date}T23:59:59.999999"
                base_conditions.append("u.upload_time <= ?")
                params.append(to_datetime)
            
            if search_query:
                base_conditions.append("u.filename LIKE ?")
                params.append(f'%{search_query}%')
            
            if application_id:
                base_conditions.append("u.application_id = ?")
                params.append(application_id)
            
            if location_id:
                base_conditions.append("u.location_id = ?")
                params.append(location_id)
            
            additional_conditions = ""
            if base_conditions:
                additional_conditions = " AND " + " AND ".join(base_conditions)
            
            query = f'''
                SELECT u.id, u.filename, u.size, u.upload_time, u.user_id, u.file_location, u.download_count, u.application_id, u.location_id
                FROM uploads u 
                WHERE u.user_id = ?{additional_conditions}
                UNION
                SELECT u.id, u.filename, u.size, u.upload_time, u.user_id, u.file_location, u.download_count, u.application_id, u.location_id
                FROM uploads u 
                JOIN shared_uploads s ON u.id = s.upload_id 
                WHERE s.shared_with = ?{additional_conditions}
                ORDER BY upload_time DESC
            '''
            
            query_params = [user_id] + params + [user_id] + params
            
            logging.debug('Executing query: %s with params: %s', query, query_params)
            cursor.execute(query, query_params)
            uploads = [
                {
                    'id': row[0],
                    'filename': row[1],
                    'size': row[2],
                    'upload_time': row[3],
                    'user_id': row[4],
                    'file_location': row[5],
                    'download_count': row[6],
                    'application_id': row[7],
                    'location_id': row[8]
                } for row in cursor.fetchall()
            ]
            logging.debug('Fetched %d uploads for user %s', len(uploads), user_id)
            return uploads
    except Exception as e:
        logging.error('Error fetching uploads: %s', str(e))
        return []

# List uploads endpoint
@app.route('/api/uploads', methods=['GET'])
@require_user_id
def list_uploads():
    user_id = request.user_id
    logging.debug('User %s listing uploads', user_id)
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    search_query = request.args.get('search')
    application_id = request.args.get('application_id')
    location_id = request.args.get('location_id')

    try:
        if from_date:
            datetime.strptime(from_date, '%Y-%m-%d')
        if to_date:
            datetime.strptime(to_date, '%Y-%m-%d')
        if from_date and to_date and from_date > to_date:
            logging.warning('From date %s is after to date %s', from_date, to_date)
            return jsonify({
                'status': 'error',
                'message': 'From date cannot be after to date'
            }), 400
    except ValueError:
        logging.error('Invalid date format: from_date=%s, to_date=%s', from_date, to_date)
        return jsonify({
            'status': 'error',
            'message': 'Invalid date format'
        }), 400

    uploads = get_user_uploads(user_id, from_date, to_date, search_query, application_id, location_id)
    return jsonify({
        'status': 'success',
        'data': uploads
    }), 200

# Download file endpoint
@app.route('/api/download/<filename>', methods=['GET'])
@require_user_id
def download_file(filename):
    user_id = request.user_id
    logging.debug('User %s downloading file %s', user_id, filename)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, file_location FROM uploads WHERE filename = ? AND user_id = ?',
                (filename, user_id)
            )
            upload = cursor.fetchone()
            if not upload:
                cursor.execute(
                    '''
                    SELECT u.id, u.file_location FROM uploads u 
                    JOIN shared_uploads s ON u.id = s.upload_id 
                    WHERE u.filename = ? AND s.shared_with = ?
                    ''',
                    (filename, user_id)
                )
                upload = cursor.fetchone()
                if not upload:
                    logging.error('File %s not accessible by %s', filename, user_id)
                    return jsonify({
                        'status': 'error',
                        'message': 'File not accessible'
                    }), 403

            upload_id, file_location = upload
            cursor.execute(
                'UPDATE uploads SET download_count = download_count + 1 WHERE id = ?',
                (upload_id,)
            )
            conn.commit()
            logging.debug('Incremented download count for upload %d', upload_id)

        file_path = os.path.join(file_location, filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        logging.error('File not found: %s', file_path)
        return jsonify({
            'status': 'error',
            'message': 'File not found'
        }), 404
    except Exception as e:
        logging.error('Error downloading file: %s', str(e))
        return jsonify({
            'status': 'error',
            'message': 'Server error'
        }), 500

# Health check endpoint
@app.route('/api/health', methods=['GET'])
def health():
    logging.debug('Health check accessed')
    return jsonify({
        'status': 'success',
        'data': {
            'server': 'running',
            'debug_mode': DEBUG
        }
    }), 200

if __name__ == '__main__':
    setup_directories()
    init_db()
    logging.debug('Starting Flask server on %s:%s', SERVER_HOST, PORT)
    try:
        app.run(host=SERVER_HOST, port=PORT, debug=DEBUG)
    except Exception as e:
        logging.error('Failed to start Flask server: %s', str(e))