from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录'


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    from app.models import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.notes import notes_bp
    from app.routes.api import api_bp
    from app.routes.collect import collect_bp
    from app.routes.assistant import assistant_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(collect_bp)
    app.register_blueprint(assistant_bp)

    with app.app_context():
        db.create_all()
        _init_admin(app)

    return app


def _init_admin(app):
    """Initialize default admin user if not exists."""
    from app.models import User
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            role='admin'
        )
        admin.set_password('123321')
        db.session.add(admin)
        db.session.commit()
