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
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Config variables
ALLOWED_EXTENSIONS = os.getenv('ALLOWED_EXTENSIONS', '').split(',') if os.getenv('ALLOWED_EXTENSIONS') else set()
UPLOAD_BASE_DIR = os.getenv('UPLOAD_BASE_DIR', r'C:\shared')
DB_PATH = os.getenv('DB_PATH', r'C:\shared\uploads.db')
LOG_FILE = os.getenv('LOG_FILE', r'C:\logs\app.log')
SERVER_HOST = os.getenv('SERVER_HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', 3000))
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', '*').split(',')

MAIL_HOST = os.getenv('MAIL_HOST', 'smtp.example.com')
MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
MAIL_USERNAME = os.getenv('MAIL_USERNAME')
MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
MAIL_FROM = os.getenv('MAIL_FROM', 'no-reply@example.com')

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
                    name TEXT NOT NULL
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS application_locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id INTEGER NOT NULL,
                    location_name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    FOREIGN KEY(application_id) REFERENCES applications(id)
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
    # If ALLOWED_EXTENSIONS is empty, allow all file types
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

# Fetch uploads for a user (FIXED VERSION)
def get_user_uploads(user_id, from_date=None, to_date=None, search_query=None):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()

            # Build the base query with proper WHERE conditions for both parts of UNION
            base_conditions = []
            params = []
            
            # Add date filters
            if from_date:
                from_datetime = f"{from_date}T00:00:00"
                base_conditions.append("u.upload_time >= ?")
                params.append(from_datetime)
            
            if to_date:
                to_datetime = f"{to_date}T23:59:59.999999"
                base_conditions.append("u.upload_time <= ?")
                params.append(to_datetime)
            
            # Add search filter
            if search_query:
                base_conditions.append("u.filename LIKE ?")
                params.append(f'%{search_query}%')
            
            # Build WHERE clause
            additional_conditions = ""
            if base_conditions:
                additional_conditions = " AND " + " AND ".join(base_conditions)
            
            # Construct the full query with conditions applied to both parts of UNION
            query = f'''
                SELECT u.id, u.filename, u.size, u.upload_time, u.user_id, u.file_location, u.download_count
                FROM uploads u 
                WHERE u.user_id = ?{additional_conditions}
                UNION
                SELECT u.id, u.filename, u.size, u.upload_time, u.user_id, u.file_location, u.download_count
                FROM uploads u 
                JOIN shared_uploads s ON u.id = s.upload_id 
                WHERE s.shared_with = ?{additional_conditions}
                ORDER BY upload_time DESC
            '''
            
            # Parameters: user_id for first query + conditions + user_id for second query + conditions again
            query_params = [user_id] + params + [user_id] + params
            
            logging.debug('Executing query: %s with params: %s', query, query_params)
            cursor.execute(query, query_params)
            uploads = [{'id': row[0], 'filename': row[1], 'size': row[2], 'upload_time': row[3], 'user_id': row[4], 'file_location': row[5], 'download_count': row[6]} for row in cursor.fetchall()]
        return uploads
    except Exception as e:
        logging.error('Error fetching uploads: %s', str(e))
        return []

# Upload file endpoint
@app.route('/api/upload', methods=['POST'])
@require_user_id
def upload_file():
    user_id = request.user_id
    logging.debug('User %s attempting file upload', user_id)
    if 'file' not in request.files or 'file_location' not in request.form:
        logging.error('Missing file or file_location')
        return jsonify({
            'status': 'error',
            'message': 'Missing file or file location'
        }), 400

    file = request.files['file']
    file_location = request.form['file_location']
    if file.filename == '':
        logging.error('No file selected')
        return jsonify({
            'status': 'error',
            'message': 'No file selected'
        }), 400

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
                    'INSERT INTO uploads (filename, size, upload_time, user_id, file_location, download_count) VALUES (?, ?, ?, ?, ?, ?)',
                    (filename, os.path.getsize(file_path), datetime.now().isoformat(), user_id, file_location, 0)
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

    logging.error('Invalid file type: %s', file.filename)
    return jsonify({
        'status': 'error',
        'message': 'Invalid file type'
    }), 400

# Share file endpoint
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
            cursor.execute('SELECT id, filename FROM uploads WHERE id = ? AND user_id = ?', (upload_id, user_id))
            upload = cursor.fetchone()
            if not upload:
                logging.error('Upload %d not found or not owned by %s', upload_id, user_id)
                return jsonify({
                    'status': 'error',
                    'message': 'Upload not found or not owned'
                }), 404

            filename = upload[1]

            cursor.execute(
                'INSERT INTO shared_uploads (upload_id, shared_by, shared_with, shared_time) VALUES (?, ?, ?, ?)',
                (upload_id, user_id, shared_with, datetime.now().isoformat())
            )
            conn.commit()
            logging.debug('Shared upload %d with %s', upload_id, shared_with)

        if send_email:
            email_url = f"http://api/some/{shared_with}"
            email_response = requests.get(email_url)
            if email_response.status_code == 200:
                email_data = email_response.json()
                email = email_data.get('email')
                if email:
                    msg = MIMEText(f"User {user_id} shared a file with you: {filename}")
                    msg['Subject'] = 'File Shared with You'
                    msg['From'] = MAIL_FROM
                    msg['To'] = email
                    try:
                        with smtplib.SMTP(MAIL_HOST, MAIL_PORT) as server:
                            server.login(MAIL_USERNAME, MAIL_PASSWORD)
                            server.sendmail(MAIL_FROM, [email], msg.as_string())
                        logging.debug('Sent email to %s for share %d', email, upload_id)
                    except Exception as e:
                        logging.error('Error sending email: %s', str(e))
                        # Continue without failing the share
            else:
                logging.error('Failed to fetch email for %s: status=%s', shared_with, email_response.status_code)

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
    except ValueValueError:
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
        logging.error('File not found: %s', filename)
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
            cursor.execute('INSERT INTO applications (name) VALUES (?)', (name,))
            application_id = cursor.lastrowid
            conn.commit()
            logging.debug('Created application %d: %s', application_id, name)
        return jsonify({
            'status': 'success',
            'data': {
                'application_id': application_id,
                'name': name
            }
        }), 201
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
            cursor.execute('SELECT id, name FROM applications ORDER BY name')
            applications = [{'id': row[0], 'name': row[1]} for row in cursor.fetchall()]
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

            cursor.execute('INSERT INTO application_locations (application_id, location_name, path) VALUES (?, ?, ?)', (application_id, location_name, path))
            location_id = cursor.lastrowid
            conn.commit()
            logging.debug('Added location %d to application %d: %s - %s', location_id, application_id, location_name, path)
        return jsonify({
            'status': 'success',
            'data': {
                'location_id': location_id,
                'application_id': application_id,
                'location_name': location_name,
                'path': path
            }
        }), 201
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
            cursor.execute('SELECT id, location_name, path FROM application_locations WHERE application_id = ? ORDER BY location_name', (application_id,))
            locations = [{'id': row[0], 'location_name': row[1], 'path': row[2]} for row in cursor.fetchall()]
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

# Config endpoint
@app.route('/api/config', methods=['GET'])
def get_config_info():
    return jsonify({
        'status': 'success',
        'data': {
            'allowed_extensions': list(ALLOWED_EXTENSIONS) if ALLOWED_EXTENSIONS else []
        }
    }), 200

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

        logging.error('Invalid file type: %s', file.filename)
        return jsonify({
            'status': 'error',
            'message': 'Invalid file type'
        }), 400

# Share file endpoint
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
            cursor.execute('SELECT id, filename FROM uploads WHERE id = ? AND user_id = ?', (upload_id, user_id))
            upload = cursor.fetchone()
            if not upload:
                logging.error('Upload %d not found or not owned by %s', upload_id, user_id)
                return jsonify({
                    'status': 'error',
                    'message': 'Upload not found or not owned'
                }), 404

            filename = upload[1]

            cursor.execute(
                'INSERT INTO shared_uploads (upload_id, shared_by, shared_with, shared_time) VALUES (?, ?, ?, ?)',
                (upload_id, user_id, shared_with, datetime.now().isoformat())
            )
            conn.commit()
            logging.debug('Shared upload %d with %s', upload_id, shared_with)

        if send_email:
            email_url = f"http://api/some/{shared_with}"
            email_response = requests.get(email_url)
            if email_response.status_code == 200:
                email_data = email_response.json()
                email = email_data.get('email')
                if email:
                    msg = MIMEText(f"User {user_id} shared a file with you: {filename}")
                    msg['Subject'] = 'File Shared with You'
                    msg['From'] = MAIL_FROM
                    msg['To'] = email
                    try:
                        with smtplib.SMTP(MAIL_HOST, MAIL_PORT) as server:
                            server.login(MAIL_USERNAME, MAIL_PASSWORD)
                            server.sendmail(MAIL_FROM, [email], msg.as_string())
                        logging.debug('Sent email to %s for share %d', email, upload_id)
                    except Exception as e:
                        logging.error('Error sending email: %s', str(e))
                        # Don't fail the share if email fails
            else:
                logging.error('Failed to fetch email for %s: status=%s', shared_with, email_response.status_code)

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
        logging.error('File not found: %s', filename)
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

# Config endpoint to expose ALLOWED_EXTENSIONS
@app.route('/api/config', methods=['GET'])
def get_config_info():
    return jsonify({
        'status': 'success',
        'data': {
            'allowed_extensions': list(ALLOWED_EXTENSIONS) if ALLOWED_EXTENSIONS else []
        }
    }), 200

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