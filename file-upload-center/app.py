from flask import Flask, request, send_file, jsonify, render_template, redirect, url_for, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
import sqlite3
from datetime import datetime
import logging
import requests

app = Flask(__name__)
app.secret_key = 'super-secret-key'  # Change in production

# Configuration
UPLOAD_DIR = r'C:\shared\uploads'
DB_PATH = r'C:\shared\uploads.db'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
USER_API_URL = 'https://your-user-api.example.com/user'  # Replace with actual URL

# Setup logging
logging.basicConfig(level=logging.DEBUG, filename='app.log', filemode='a', format='%(asctime)s - %(levelname)s - %(message)s')

# Ensure upload directory exists
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

# Initialize SQLite database
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                size INTEGER NOT NULL,
                upload_time TEXT NOT NULL,
                user_id TEXT NOT NULL
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

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'index'

# Simple user class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username, display_name, employee_id):
        self.id = id  # username from API
        self.username = username
        self.display_name = display_name
        self.employee_id = employee_id

# Global users dict (populated dynamically)
users = {}

# Fetch user details using bamToken
def get_user_details(bam_token):
    try:
        headers = {'Authorization': f'Bearer {bam_token}'}
        response = requests.get(USER_API_URL, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return {
                'username': data.get('username'),
                'display_name': data.get('displayName'),
                'employee_id': data.get('employeeId')
            }
        else:
            logging.error('User API call failed: %s', response.text)
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

# Root route with BAM authentication
@app.route('/')
def index():
    logging.debug('Accessing index route')
    if current_user.is_authenticated:
        logging.debug('User %s already authenticated', current_user.id)
    else:
        # Get bamToken from request header (e.g., Authorization: Bearer <token>)
        bam_token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not bam_token:
            logging.error('No bamToken provided')
            return jsonify({'error': 'No bamToken provided'}), 401
        user_details = get_user_details(bam_token)
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
            logging.error('Invalid bamToken')
            return jsonify({'error': 'Invalid bamToken'}), 401
    logging.debug('Attempting to render index.html for user %s', current_user.id)
    response = make_response(render_template('index.html', users=[u for u in users.keys() if u != current_user.id]))
    response.headers['Content-Type'] = 'text/html'
    logging.debug('Rendered index.html successfully')
    return response

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
    if 'file' not in request.files:
        logging.error('No file uploaded')
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    if file.filename == '':
        logging.error('No file selected')
        return jsonify({'error': 'No file selected'}), 400
    if file and allowed_file(file.filename):
        if file.content_length and file.content_length > MAX_FILE_SIZE:
            logging.error('File too large: %s', file.filename)
            return jsonify({'error': 'File too large'}), 400
        filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
        file_path = os.path.join(UPLOAD_DIR, filename)
        file.save(file_path)
        logging.debug('Saved file %s to %s', filename, file_path)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO uploads (filename, size, upload_time, user_id) VALUES (?, ?, ?, ?)',
                (filename, os.path.getsize(file_path), datetime.now().isoformat(), current_user.id)
            )
            conn.commit()
            logging.debug('Logged upload to database: %s by %s', filename, current_user.id)
        return jsonify({'message': 'File uploaded successfully', 'filename': filename}), 200
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

# List files
@app.route('/files', methods=['GET'])
@login_required
def list_files():
    logging.debug('User %s listing files', current_user.id)
    try:
        files = os.listdir(UPLOAD_DIR)
        return jsonify(files), 200
    except Exception as e:
        logging.error('Error listing files: %s', str(e))
        return jsonify({'error': 'Error reading files'}), 500

# Download file
@app.route('/download/<filename>', methods=['GET'])
@login_required
def download_file(filename):
    logging.debug('User %s downloading file %s', current_user.id, filename)
    file_path = os.path.join(UPLOAD_DIR, filename)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id FROM uploads WHERE filename = ? AND user_id = ?', (filename, current_user.id)
        )
        upload = cursor.fetchone()
        if not upload:
            cursor.execute(
                'SELECT u.filename FROM uploads u JOIN shared_uploads s ON u.id = s.upload_id WHERE u.filename = ? AND s.shared_with = ?',
                (filename, current_user.id)
            )
            if not cursor.fetchone():
                logging.error('File %s not accessible by %s', filename, current_user.id)
                return jsonify({'error': 'File not accessible'}), 403
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    logging.error('File not found: %s', filename)
    return jsonify({'error': 'File not found'}), 404

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
                SELECT u.id, u.filename, u.size, u.upload_time, u.user_id 
                FROM uploads u 
                WHERE u.user_id = ? AND DATE(u.upload_time) = ?
                UNION
                SELECT u.id, u.filename, u.size, u.upload_time, u.user_id 
                FROM uploads u 
                JOIN shared_uploads s ON u.id = s.upload_id 
                WHERE s.shared_with = ? AND DATE(u.upload_time) = ?
                ORDER BY u.upload_time DESC
                ''',
                (current_user.id, date_filter, current_user.id, date_filter)
            )
            uploads = [{'id': row[0], 'filename': row[1], 'size': row[2], 'upload_time': row[3], 'user_id': row[4]} for row in cursor.fetchall()]
        return jsonify(uploads), 200
    except Exception as e:
        logging.error('Error fetching upload history: %s', str(e))
        return jsonify({'error': 'Error fetching upload history'}), 500

if __name__ == '__main__':
    init_db()
    logging.debug('Starting Flask development server on port 3000')
    app.run(host='0.0.0.0', port=3000, debug=True)