import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-2026'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'mysql+pymysql://root:tpcloud%40123@gz-cdb-gud1zg1t.sql.tencentcdb.com:27407/study_assistant?charset=utf8mb4'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
    }
    OBSIDIAN_VAULT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'obsidian_vaults')
    
    # Production settings
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
