from flask import Flask, request, send_file, jsonify, render_template, redirect, url_for, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
import os
import sqlite3
from datetime import datetime
import logging
import requests

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'super-secret-key'  # Change in production

# Configuration
UPLOAD_BASE_DIR = r'C:\shared'
DB_PATH = r'C:\shared\uploads.db'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
AUTH_API_URL = 'http://bam-auth.client.example.com'  # Replace with actual URL

# Setup logging
log_file = r'C:\file-upload-center\app.log'
try:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='a'),
            logging.StreamHandler()  # Log to console
        ]
    )
    logging.debug('Logging initialized successfully')
except Exception as e:
    print(f"Failed to initialize logging: {e}")
    logging.error(f"Failed to initialize logging: {e}")

# Ensure base directory exists
if not os.path.exists(UPLOAD_BASE_DIR):
    try:
        os.makedirs(UPLOAD_BASE_DIR)
        logging.debug(f'Created UPLOAD_BASE_DIR: {UPLOAD_BASE_DIR}')
    except Exception as e:
        logging.error(f'Failed to create UPLOAD_BASE_DIR: {e}')

# Initialize SQLite database
def init_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    upload_time TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    file_location TEXT NOT NULL
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON uploads(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_upload_time ON uploads(upload_time)')
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

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'index'

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username, display_name, employee_id):
        self.id = id  # username from API
        self.username = username
        self.display_name = display_name
        self.employee_id = employee_id

# Global users dict
users = {}

# Fetch bamToken from auth API
def get_bam_token(client_token):
    try:
        headers = {
            'Cookie': client_token,  # Pass client_token as Cookie
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Accept-Language': 'en-US,en;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
        }
        logging.debug('Calling AUTH_API_URL with client_token in Cookie: %s', client_token)
        response = requests.get(AUTH_API_URL, headers=headers, timeout=5)
        logging.debug('AUTH_API_URL response: status=%s, body=%s', response.status_code, response.text)
        if response.status_code == 200 and response.json().get('code') == 'SUCCESS':
            data = response.json()
            bam_token = data.get('bamToken')
            redirect_url = data.get('redirectURL')
            logging.debug('Extracted bamToken: %s, redirectURL: %s', bam_token, redirect_url)
            return bam_token, redirect_url
        else:
            logging.error('Auth API call failed: status=%s, body=%s', response.status_code, response.text)
            return None, None
    except Exception as e:
        logging.error('Error fetching bamToken: %s', str(e))
        return None, None

# Fetch user details using bamToken
def get_user_details(bam_token, redirect_url):
    try:
        headers = {
            'Authorization': f'Bearer {bam_token}',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': 'http://dummyclient.local:9013',
            'Referer': 'http://dummyclient.local:9013/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
        }
        logging.debug('Calling redirectURL with bamToken: %s, headers: %s', redirect_url, headers)
        response = requests.get(redirect_url, headers=headers, timeout=5)
        logging.debug('RedirectURL response: status=%s, body=%s', response.status_code, response.text)
        if response.status_code == 200:
            data = response.json()
            return {
                'username': data.get('username'),
                'display_name': data.get('displayName'),
                'employee_id': data.get('employeeId')
            }
        else:
            logging.error('User API call failed: status=%s, body=%s', response.status_code, response.text)
            return None
    except Exception as e:
        logging.error('Error fetching user details: %s', str(e))
        return None

@login_manager.user_loader
def load_user(user_id):
    logging.debug('Loading user %s', user_id)
    return users.get(user_id)

# Check allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Validate file location
def validate_file_location(location):
    if not location.startswith(UPLOAD_BASE_DIR):
        logging.error('File location does not start with %s: %s', UPLOAD_BASE_DIR, location)
        return False
    try:
        if not os.path.exists(location):
            os.makedirs(location)
            logging.debug('Created directory: %s', location)
        return os.access(location, os.W_OK | os.R_OK)
    except Exception as e:
        logging.error('Invalid file location %s: %s', location, str(e))
        return False

# Root route with BAM authentication
@app.route('/')
def index():
    logging.debug('Accessing index route')
    logging.debug('Request headers: %s', dict(request.headers))
    logging.debug('Query parameters: %s', dict(request.args))
    if current_user.is_authenticated:
        logging.debug('User %s already authenticated', current_user.id)
    else:
        # Try header, query parameter, or cookie
        client_token = (request.headers.get('X-Client-Token') or 
                        request.headers.get('Authorization', '').replace('Bearer ', '') or 
                        request.headers.get('Client-Token') or 
                        request.args.get('client_token') or 
                        request.args.get('token') or 
                        request.headers.get('Cookie'))
        if not client_token:
            logging.error('No client token provided')
            return jsonify({'error': 'No client token provided'}), 401
        bam_token, redirect_url = get_bam_token(client_token)
        if not bam_token or not redirect_url:
            logging.error('Invalid client token or no redirectURL: %s', client_token)
            return jsonify({'error': 'Invalid client token or BAM API failure'}), 401
        user_details = get_user_details(bam_token, redirect_url)
        if user_details:
            user_id = user_details['username']
            user = User(
                id=user_id,
                username=user_details['username'],
                display_name=user_details['display_name'],
                employee_id=user_details['employee_id']
            )
            users[user_id] = user
            login_user(user)
            logging.debug('Authenticated user %s', user_id)
        else:
            logging.error('Invalid bamToken or user API failure')
            return jsonify({'error': 'Invalid bamToken or user API failure'}), 401
    logging.debug('Attempting to render index.html for user %s', current_user.id)
    try:
        response = make_response(render_template('index.html', users=[u for u in users.keys() if u != current_user.id], client_token=client_token))
        response.headers['Content-Type'] = 'text/html'
        logging.debug('Rendered index.html successfully')
        return response
    except Exception as e:
        logging.error('Error rendering index.html: %s', str(e))
        return jsonify({'error': 'Failed to render page'}), 500

# Logout route
@app.route('/logout')
@login_required
def logout():
    logging.debug('User %s logging out', current_user.id)
    logout_user()
    return redirect(url_for('index'))

# Upload endpoint
@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    logging.debug('User %s attempting file upload', current_user.id)
    if 'file' not in request.files or 'file_location' not in request.form:
        logging.error('Missing file or file_location')
        return jsonify({'error': 'Missing file or file location'}), 400
    file = request.files['file']
    file_location = request.form['file_location']
    if file.filename == '':
        logging.error('No file selected')
        return jsonify({'error': 'No file selected'}), 400
    if not validate_file_location(file_location):
        logging.error('Invalid or inaccessible file location: %s', file_location)
        return jsonify({'error': 'Invalid or inaccessible file location'}), 400
    if file and allowed_file(file.filename):
        if file.content_length and file.content_length > MAX_FILE_SIZE:
            logging.error('File too large: %s', file.filename)
            return jsonify({'error': 'File too large'}), 400
        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
        file_path = os.path.join(file_location, filename)
        file.save(file_path)
        logging.debug('Saved file %s to %s', filename, file_path)
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO uploads (filename, size, upload_time, user_id, file_location) VALUES (?, ?, ?, ?, ?)',
                    (filename, os.path.getsize(file_path), datetime.now().isoformat(), current_user.id, file_location)
                )
                conn.commit()
                logging.debug('Logged upload to database: %s by %s at %s', filename, current_user.id, file_location)
            return jsonify({'message': 'File uploaded successfully', 'filename': filename}), 200
        except Exception as e:
            logging.error('Error saving to database: %s', str(e))
            return jsonify({'error': 'Database error'}), 500
    logging.error('Invalid file type: %s', file.filename)
    return jsonify({'error': 'Invalid file type'}), 400

# Share upload endpoint
@app.route('/share/<int:upload_id>', methods=['POST'])
@login_required
def share_file(upload_id):
    logging.debug('User %s attempting to share upload %d', current_user.id, upload_id)
    shared_with = request.form.get('shared_with')
    if shared_with not in users:
        logging.error('Invalid user to share with: %s', shared_with)
        return jsonify({'error': 'Invalid user'}), 400
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM uploads WHERE id = ? AND user_id = ?', (upload_id, current_user.id))
            if not cursor.fetchone():
                logging.error('Upload %d not found or not owned by %s', upload_id, current_user.id)
                return jsonify({'error': 'Upload not found or not owned'}), 404
            cursor.execute(
                'INSERT INTO shared_uploads (upload_id, shared_by, shared_with, shared_time) VALUES (?, ?, ?, ?)',
                (upload_id, current_user.id, shared_with, datetime.now().isoformat())
            )
            conn.commit()
            logging.debug('Shared upload %d with %s', upload_id, shared_with)
        return jsonify({'message': f'Shared with {shared_with}'}), 200
    except Exception as e:
        logging.error('Error sharing file: %s', str(e))
        return jsonify({'error': 'Database error'}), 500

# List files
@app.route('/files', methods=['GET'])
@login_required
def list_files():
    logging.debug('User %s listing files', current_user.id)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT filename FROM uploads WHERE user_id = ?
                UNION
                SELECT u.filename FROM uploads u 
                JOIN shared_uploads s ON u.id = s.upload_id 
                WHERE s.shared_with = ?
                ''',
                (current_user.id, current_user.id)
            )
            files = [row[0] for row in cursor.fetchall()]
        return jsonify(files), 200
    except Exception as e:
        logging.error('Error listing files: %s', str(e))
        return jsonify({'error': 'Error reading files'}), 500

# Download file
@app.route('/download/<filename>', methods=['GET'])
@login_required
def download_file(filename):
    logging.debug('User %s downloading file %s', current_user.id, filename)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT file_location FROM uploads WHERE filename = ? AND user_id = ?',
                (filename, current_user.id)
            )
            upload = cursor.fetchone()
            if not upload:
                cursor.execute(
                    '''
                    SELECT u.file_location FROM uploads u 
                    JOIN shared_uploads s ON u.id = s.upload_id 
                    WHERE u.filename = ? AND s.shared_with = ?
                    ''',
                    (filename, current_user.id)
                )
                upload = cursor.fetchone()
                if not upload:
                    logging.error('File %s not accessible by %s', filename, current_user.id)
                    return jsonify({'error': 'File not accessible'}), 403
            file_location = upload[0]
        file_path = os.path.join(file_location, filename)
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        logging.error('File not found: %s', filename)
        return jsonify({'error': 'File not found'}), 404
    except Exception as e:
        logging.error('Error downloading file: %s', str(e))
        return jsonify({'error': 'Server error'}), 500

# Get upload history
@app.route('/uploads', methods=['GET'])
@login_required
def get_upload_history():
    logging.debug('User %s fetching upload history', current_user.id)
    date_filter = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT u.id, u.filename, u.size, u.upload_time, u.user_id, u.file_location 
                FROM uploads u 
                WHERE u.user_id = ? AND DATE(u.upload_time) = ?
                UNION
                SELECT u.id, u.filename, u.size, u.upload_time, u.user_id, u.file_location 
                FROM uploads u 
                JOIN shared_uploads s ON u.id = s.upload_id 
                WHERE s.shared_with = ? AND DATE(u.upload_time) = ?
                ORDER BY u.upload_time DESC
                ''',
                (current_user.id, date_filter, current_user.id, date_filter)
            )
            uploads = [{'id': row[0], 'filename': row[1], 'size': row[2], 'upload_time': row[3], 'user_id': row[4], 'file_location': row[5]} for row in cursor.fetchall()]
        return jsonify(uploads), 200
    except Exception as e:
        logging.error('Error fetching upload history: %s', str(e))
        return jsonify({'error': 'Error fetching upload history'}), 500

# Health check endpoint
@app.route('/health')
def health():
    logging.debug('Health check accessed')
    return jsonify({'status': 'Server running', 'debug_mode': app.debug}), 200

if __name__ == '__main__':
    init_db()
    logging.debug('Starting Flask development server on port 3000')
    try:
        app.run(host='0.0.0.0', port=3000, debug=True)
    except Exception as e:
        logging.error('Failed to start Flask server: %s', str(e))
        print(f"Failed to start server: {e}")