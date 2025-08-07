import os
from dotenv import load_dotenv

# Load environment variables
env = os.getenv('FLASK_ENV', 'dev')
load_dotenv(os.path.join(os.path.dirname(__file__), 'env', f'{env}.env'))

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'super-secret-key')
    UPLOAD_BASE_DIR = os.getenv('UPLOAD_BASE_DIR')
    DB_PATH = os.getenv('DB_PATH')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
    MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
    AUTH_API_URL = os.getenv('AUTH_API_URL')
    LOG_FILE = os.getenv('LOG_FILE')

class DevConfig(Config):
    DEBUG = True
    LOG_LEVEL = 'DEBUG'

class UATConfig(Config):
    DEBUG = False
    LOG_LEVEL = 'INFO'

class ProdConfig(Config):
    DEBUG = False
    LOG_LEVEL = 'INFO'

config_map = {
    'dev': DevConfig,
    'uat': UATConfig,
    'prod': ProdConfig
}

def get_config():
    return config_map.get(env, DevConfig)