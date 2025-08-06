from flask import Flask, request, send_file, jsonify, render_template, redirect, url_for, flash, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
import os
import sqlite3
from datetime import datetime
import logging

app = Flask(__name__)
app.secret_key = 'super-secret-key'  # Change in production

# Configuration
UPLOAD_DIR = r'C:\shared\uploads'  # Windows path
DB_PATH = r'C:\shared\uploads.db'  # Windows path
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

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
        conn.commit()
        logging.debug('Initialized SQLite database')

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Simple user class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

# Hardcoded user (hash for 'password123')
users = {
    'user1': User('user1', 'user1', 'pbkdf2:sha256:600000$XvW4BzvT4V7k3Y8K$5b7b8e8e7c7b7e8e7c7b7e8e7c7b7e8e7c7b7e8e7c7b7e8e7c7b7e8e7c7b7e8e')
}

@login_manager.user_loader
def load_user(user_id):
    logging.debug('Loading user %s', user_id)
    return users.get(user_id)

# Check allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    logging.debug('Accessing login route')
    if current_user.is_authenticated:
        logging.debug('User %s already authenticated, redirecting to index', current_user.id)
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        logging.debug('Login attempt for username %s', username)
        user = users.get(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            logging.debug('Login successful for %s', username)
            return redirect(url_for('index'))
        flash('Invalid username or password')
        logging.debug('Login failed for %s', username)
    logging.debug('Attempting to render login.html')
    response = make_response(render_template('login.html'))
    response.headers['Content-Type'] = 'text/html'
    logging.debug('Rendered login.html successfully')
    return response

# Logout route
@app.route('/logout')
@login_required
def logout():
    logging.debug('User %s logging out', current_user.id)
    logout_user()
    return redirect(url_for('login'))

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
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    logging.error('File not found: %s', filename)
    return jsonify({'error': 'File not found'}), 404

# Get upload history
@app.route('/uploads', methods=['GET'])
@login_required
def get_upload_history():
    logging.debug('User %s fetching upload history', current_user.id)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, filename, size, upload_time, user_id FROM uploads ORDER BY upload_time DESC')
            uploads = [{'id': row[0], 'filename': row[1], 'size': row[2], 'upload_time': row[3], 'user_id': row[4]} for row in cursor.fetchall()]
        return jsonify(uploads), 200
    except Exception as e:
        logging.error('Error fetching upload history: %s', str(e))
        return jsonify({'error': 'Error fetching upload history'}), 500

# Serve frontend
@app.route('/')
@login_required
def index():
    logging.debug('Attempting to render index.html for user %s', current_user.id)
    response = make_response(render_template('index.html'))
    response.headers['Content-Type'] = 'text/html'
    logging.debug('Rendered index.html successfully')
    return response

if __name__ == '__main__':
    init_db()
    logging.debug('Starting Flask development server on port 3000')
    app.run(host='0.0.0.0', port=3000, debug=True)