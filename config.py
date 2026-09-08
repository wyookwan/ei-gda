import os
from urllib.parse import quote_plus
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-me-in-production')
    MYSQL_HOST = os.getenv('MYSQL_HOST', '127.0.0.1')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
    MYSQL_DB = os.getenv('MYSQL_DB', 'eigda_db')
    MYSQL_USER = os.getenv('MYSQL_USER', 'eigda_user')
    MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'change-me')
    _PW = quote_plus(MYSQL_PASSWORD)
    SQLALCHEMY_DATABASE_URI = (
        f'mysql+pymysql://{MYSQL_USER}:{_PW}@{MYSQL_HOST}:{MYSQL_PORT}/'
        f'{MYSQL_DB}?charset=utf8mb4'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True, 'pool_recycle': 280}
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
    REPORT_FOLDER = os.getenv('REPORT_FOLDER', 'reports')
    MAX_CONTENT_LENGTH = 30 * 1024 * 1024
    APP_HOST = os.getenv('APP_HOST', '127.0.0.1')
    APP_PORT = int(os.getenv('APP_PORT', '5000'))
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'

    # OPEN documents are assessed by Gemini.
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
    GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash').strip()
    GEMINI_TIMEOUT = int(os.getenv('GEMINI_TIMEOUT', '120'))

    # CONFIDENTIAL documents are assessed by the local model only.
    LOCAL_MODEL_API_URL = os.getenv('LOCAL_MODEL_API_URL', 'http://10.80.39.43:8087/v1/chat/completions').strip()
    LOCAL_MODEL_NAME = os.getenv('LOCAL_MODEL_NAME', '').strip()
    LOCAL_MODEL_API_MODE = os.getenv('LOCAL_MODEL_API_MODE', 'openai_chat').strip()
    LOCAL_MODEL_TIMEOUT = int(os.getenv('LOCAL_MODEL_TIMEOUT', '120'))
    LOCAL_MODEL_BATCH_SIZE = max(1, int(os.getenv('LOCAL_MODEL_BATCH_SIZE', '10')))
    LOCAL_MODEL_MAX_TOKENS = max(512, int(os.getenv('LOCAL_MODEL_MAX_TOKENS', '3500')))
    LOCAL_MODEL_VERIFY_SSL = os.getenv('LOCAL_MODEL_VERIFY_SSL', 'False').lower() == 'true'

    # ThaiD / OpenID Connect configuration. Keep all credentials in .env only.
    THAID_ENABLED = os.getenv('THAID_ENABLED', 'False').lower() == 'true'
    THAID_DISCOVERY_URL = os.getenv('THAID_DISCOVERY_URL', '').strip()
    THAID_AUTHORIZATION_ENDPOINT = os.getenv('THAID_AUTHORIZATION_ENDPOINT', '').strip()
    THAID_TOKEN_ENDPOINT = os.getenv('THAID_TOKEN_ENDPOINT', '').strip()
    THAID_USERINFO_ENDPOINT = os.getenv('THAID_USERINFO_ENDPOINT', '').strip()
    THAID_INTROSPECT_URL = os.getenv('THAID_INTROSPECT_URL', '').strip()
    THAID_REVOKE_URL = os.getenv('THAID_REVOKE_URL', '').strip()
    THAID_CLIENT_ID = os.getenv('THAID_CLIENT_ID', '').strip()
    THAID_CLIENT_SECRET = os.getenv('THAID_CLIENT_SECRET', '').strip()
    THAID_API_KEY = os.getenv('THAID_API_KEY', '').strip()
    THAID_API_KEY_HEADER = os.getenv('THAID_API_KEY_HEADER', 'x-api-key').strip()
    THAID_SCOPE = os.getenv('THAID_SCOPE', 'pid openid name_en name').strip()
    THAID_REDIRECT_URI = os.getenv('THAID_REDIRECT_URI', '').strip()
    THAID_TOKEN_ENDPOINT_AUTH_METHOD = os.getenv('THAID_TOKEN_ENDPOINT_AUTH_METHOD', 'client_secret_basic').strip()
    THAID_ORGANIZATION_DEFAULT = os.getenv('THAID_ORGANIZATION_DEFAULT', '').strip()
    THAID_VERIFY_SSL = os.getenv('THAID_VERIFY_SSL', 'True').lower() == 'true'
