from functools import wraps
from sqlalchemy import func
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import User, Note, LearningActivity, SystemConfig, Conversation, ContentCollection, FinanceRecord

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            flash('需要管理员权限', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/')
@admin_required
def admin_dashboard():
    user_count = User.query.filter_by(role='user').count()
    note_count = Note.query.count()
    activity_count = LearningActivity.query.count()
    users = User.query.order_by(User.created_at.desc()).all()
    
    # Current LLM settings
    llm_provider = SystemConfig.get('llm_provider', '')
    llm_model = SystemConfig.get('llm_model', '')
    llm_api_key = SystemConfig.get('llm_api_key', '')
    llm_api_base = SystemConfig.get('llm_api_base', '')
    bot_api_token = SystemConfig.get('bot_api_token', '')
    
    return render_template('admin/dashboard.html',
                           user_count=user_count,
                           note_count=note_count,
                           activity_count=activity_count,
                           users=users,
                           llm_provider=llm_provider,
                           llm_model=llm_model,
                           llm_api_key=llm_api_key,
                           llm_api_base=llm_api_base,
                           bot_api_token=bot_api_token)


@admin_bp.route('/llm-settings', methods=['POST'])
@admin_required
def llm_settings():
    provider = request.form.get('llm_provider', '').strip()
    model = request.form.get('llm_model', '').strip()
    api_key = request.form.get('llm_api_key', '').strip()
    api_base = request.form.get('llm_api_base', '').strip()
    
    SystemConfig.set('llm_provider', provider, current_user.id)
    SystemConfig.set('llm_model', model, current_user.id)
    SystemConfig.set('llm_api_key', api_key, current_user.id)
    SystemConfig.set('llm_api_base', api_base, current_user.id)
    
    flash('大模型设置已更新，所有用户将使用此配置', 'success')
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/users')
@admin_required
def user_management():
    """User management page with detailed user info."""
    # Subquery: note count per user
    note_counts = db.session.query(
        Note.user_id, func.count(Note.id).label('note_count')
    ).group_by(Note.user_id).subquery()

    # Subquery: conversation count per user
    conv_counts = db.session.query(
        Conversation.user_id, func.count(Conversation.id).label('conv_count')
    ).group_by(Conversation.user_id).subquery()

    # Subquery: collection count per user
    coll_counts = db.session.query(
        ContentCollection.user_id, func.count(ContentCollection.id).label('coll_count')
    ).group_by(ContentCollection.user_id).subquery()

    users_q = db.session.query(
        User,
        func.coalesce(note_counts.c.note_count, 0).label('note_count'),
        func.coalesce(conv_counts.c.conv_count, 0).label('conv_count'),
        func.coalesce(coll_counts.c.coll_count, 0).label('coll_count'),
    ).outerjoin(note_counts, User.id == note_counts.c.user_id)\
     .outerjoin(conv_counts, User.id == conv_counts.c.user_id)\
     .outerjoin(coll_counts, User.id == coll_counts.c.user_id)\
     .order_by(User.created_at.desc()).all()

    users_data = []
    for row in users_q:
        users_data.append({
            'user': row[0],
            'note_count': row[1],
            'conv_count': row[2],
            'coll_count': row[3],
        })

    return render_template('admin/users.html', users_data=users_data)


@admin_bp.route('/user/<int:user_id>')
@admin_required
def user_detail(user_id):
    user = User.query.get_or_404(user_id)
    notes = Note.query.filter_by(user_id=user.id).order_by(Note.updated_at.desc()).all()
    activities = LearningActivity.query.filter_by(user_id=user.id)\
        .order_by(LearningActivity.created_at.desc()).limit(50).all()
    
    return render_template('admin/user_detail.html',
                           target_user=user,
                           notes=notes,
                           activities=activities)


@admin_bp.route('/user/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        flash('不能删除管理员账户', 'error')
        return redirect(url_for('admin.admin_dashboard'))
    
    db.session.delete(user)
    db.session.commit()
    flash(f'用户 {user.username} 已删除', 'success')
    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/user/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def reset_user_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()
    
    if len(new_password) < 6:
        flash('密码长度至少6个字符', 'error')
        return redirect(url_for('admin.user_detail', user_id=user_id))
    
    user.set_password(new_password)
    db.session.commit()
    flash(f'用户 {user.username} 的密码已重置', 'success')
    return redirect(url_for('admin.user_detail', user_id=user_id))
