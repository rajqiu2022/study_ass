from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models import Note, LearningActivity, SystemConfig, ContentCollection
from sqlalchemy import func

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@main_bp.route('/dashboard')
@login_required
def dashboard():
    note_count = Note.query.filter_by(user_id=current_user.id).count()
    collection_count = ContentCollection.query.filter_by(user_id=current_user.id).count()
    
    recent_notes = Note.query.filter_by(user_id=current_user.id)\
        .order_by(Note.updated_at.desc()).limit(6).all()
    
    recent_activities = LearningActivity.query.filter_by(user_id=current_user.id)\
        .order_by(LearningActivity.created_at.desc()).limit(10).all()
    
    topic_stats = db.session.query(
        LearningActivity.topic, func.count(LearningActivity.id)
    ).filter(
        LearningActivity.user_id == current_user.id,
        LearningActivity.topic != '',
        LearningActivity.is_learning == True
    ).group_by(LearningActivity.topic)\
     .order_by(func.count(LearningActivity.id).desc())\
     .limit(10).all()
    
    # Category distribution for notes
    category_stats = db.session.query(
        Note.category, func.count(Note.id)
    ).filter(Note.user_id == current_user.id)\
     .group_by(Note.category).all()
    
    llm_model = SystemConfig.get('llm_model', '')
    
    return render_template('main/dashboard.html',
                           note_count=note_count,
                           collection_count=collection_count,
                           recent_notes=recent_notes,
                           recent_activities=recent_activities,
                           topic_stats=topic_stats,
                           category_stats=category_stats,
                           llm_model=llm_model)


@main_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        interests = request.form.get('interests', '').strip()
        current_learning = request.form.get('current_learning', '').strip()
        bio = request.form.get('bio', '').strip()
        scene = request.form.get('scene', 'general').strip()
        
        current_user.interests = interests
        current_user.current_learning = current_learning
        current_user.bio = bio
        current_user.scene = scene
        db.session.commit()
        
        activity = LearningActivity(
            user_id=current_user.id,
            activity_type='profile_updated',
            content=f'更新了个人资料',
            topic=current_learning.split(',')[0].strip() if current_learning else ''
        )
        db.session.add(activity)
        db.session.commit()
        
        flash('个人资料已更新', 'success')
        return redirect(url_for('main.profile'))
    
    activity_types = db.session.query(
        LearningActivity.activity_type, func.count(LearningActivity.id)
    ).filter(
        LearningActivity.user_id == current_user.id
    ).group_by(LearningActivity.activity_type).all()
    
    top_topics = db.session.query(
        LearningActivity.topic, func.count(LearningActivity.id)
    ).filter(
        LearningActivity.user_id == current_user.id,
        LearningActivity.topic != '',
        LearningActivity.is_learning == True
    ).group_by(LearningActivity.topic)\
     .order_by(func.count(LearningActivity.id).desc())\
     .limit(10).all()
    
    return render_template('main/profile.html',
                           activity_types=activity_types,
                           top_topics=top_topics)
