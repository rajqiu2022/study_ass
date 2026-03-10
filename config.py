import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-2026'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///knowledge.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    OBSIDIAN_VAULT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'obsidian_vaults')
    
    # Production settings
    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
