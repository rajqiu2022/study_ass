from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='user')  # 'user' or 'admin'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # User profile / learning preferences
    interests = db.Column(db.Text, default='')
    current_learning = db.Column(db.Text, default='')
    bio = db.Column(db.Text, default='')
    scene = db.Column(db.String(20), default='general')  # 'work', 'study', 'life', 'general'
    
    # Relationships
    notes = db.relationship('Note', backref='author', lazy='dynamic', cascade='all, delete-orphan')
    activities = db.relationship('LearningActivity', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    collections = db.relationship('ContentCollection', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    conversations = db.relationship('Conversation', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_admin(self):
        return self.role == 'admin'
    
    def __repr__(self):
        return f'<User {self.username}>'


class Note(db.Model):
    """Obsidian-compatible markdown notes, stored per user."""
    __tablename__ = 'notes'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, default='')
    folder = db.Column(db.String(200), default='/')
    tags = db.Column(db.Text, default='')
    category = db.Column(db.String(50), default='general')  # 'work','study','life','general'
    source_url = db.Column(db.Text, default='')  # original URL if from content collection
    source_type = db.Column(db.String(20), default='manual')  # 'manual','article','video'
    is_favorited = db.Column(db.Boolean, default=False, index=True)  # 收藏标记
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Note {self.title}>'


class ContentCollection(db.Model):
    """Collected content items (articles, videos) pending or processed."""
    __tablename__ = 'content_collections'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    url = db.Column(db.Text, nullable=False)
    content_type = db.Column(db.String(20), default='article')  # 'article','video','other'
    title = db.Column(db.String(300), default='')
    summary = db.Column(db.Text, default='')  # AI-generated summary
    key_points = db.Column(db.Text, default='')  # AI-extracted key points (JSON)
    category = db.Column(db.String(50), default='')  # AI-classified category
    tags = db.Column(db.Text, default='')  # AI-generated tags
    raw_content = db.Column(db.Text, default='')  # extracted text content
    status = db.Column(db.String(20), default='pending')  # 'pending','processing','done','error'
    error_msg = db.Column(db.Text, default='')
    note_id = db.Column(db.Integer, db.ForeignKey('notes.id'), nullable=True)  # linked note after processing
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)
    
    note = db.relationship('Note', backref='source_collection')
    
    def __repr__(self):
        return f'<Collection {self.title or self.url}>'


class LearningActivity(db.Model):
    """Track user learning activities and habits."""
    __tablename__ = 'learning_activities'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    activity_type = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, default='')
    topic = db.Column(db.String(200), default='')
    is_learning = db.Column(db.Boolean, default=True)  # True=学习相关, False=闲聊/兴趣
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Activity {self.activity_type}: {self.topic}>'


class Conversation(db.Model):
    """AI assistant conversation sessions, stored per user."""
    __tablename__ = 'conversations'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title = db.Column(db.String(200), default='新对话')
    summary = db.Column(db.Text, default='')  # AI-generated rolling summary for context compression
    message_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = db.relationship('ChatMessage', backref='conversation', lazy='dynamic',
                               cascade='all, delete-orphan', order_by='ChatMessage.created_at')

    def __repr__(self):
        return f'<Conversation {self.id}: {self.title}>'


class ChatMessage(db.Model):
    """Individual messages within a conversation."""
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False)  # 'user', 'assistant'
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'role': self.role,
            'content': self.content,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M')
        }

    def __repr__(self):
        return f'<ChatMessage {self.role}: {self.content[:30]}>'


class FinanceRecord(db.Model):
    """Personal finance records - income and expenses."""
    __tablename__ = 'finance_records'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    record_type = db.Column(db.String(10), nullable=False)  # 'expense' or 'income'
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(50), nullable=False)  # e.g. '餐饮','交通','工资','兼职'
    description = db.Column(db.Text, default='')  # original user input or detail
    record_date = db.Column(db.Date, nullable=False, index=True)  # the actual date of the record
    source = db.Column(db.String(20), default='ai')  # 'ai' (from assistant), 'manual' (from form)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('finance_records', lazy='dynamic',
                                                       cascade='all, delete-orphan'))

    # Category presets
    EXPENSE_CATEGORIES = [
        '餐饮', '交通', '购物', '娱乐', '居住', '医疗', '教育', '通讯',
        '服饰', '美容', '社交', '旅行', '宠物', '办公', '数码', '其他支出'
    ]
    INCOME_CATEGORIES = [
        '工资', '奖金', '兼职', '理财', '报销', '红包', '转账', '其他收入'
    ]

    def to_dict(self):
        return {
            'id': self.id,
            'record_type': self.record_type,
            'amount': self.amount,
            'category': self.category,
            'description': self.description,
            'record_date': self.record_date.strftime('%Y-%m-%d'),
            'source': self.source,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M')
        }

    def __repr__(self):
        return f'<Finance {self.record_type}: {self.category} {self.amount}>'


class SystemConfig(db.Model):
    """System-wide configuration, managed by admin."""
    __tablename__ = 'system_config'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, default='')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    @staticmethod
    def get(key, default=''):
        config = SystemConfig.query.filter_by(key=key).first()
        return config.value if config else default
    
    @staticmethod
    def set(key, value, admin_id=None):
        config = SystemConfig.query.filter_by(key=key).first()
        if config:
            config.value = value
            config.updated_by = admin_id
        else:
            config = SystemConfig(key=key, value=value, updated_by=admin_id)
            db.session.add(config)
        db.session.commit()
        return config
    
    def __repr__(self):
        return f'<Config {self.key}>'
