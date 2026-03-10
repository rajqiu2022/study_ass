import os
import markdown
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app import db
from app.models import Note, LearningActivity

notes_bp = Blueprint('notes', __name__, url_prefix='/notes')


def _sync_note_to_obsidian(note, user):
    """Sync a note to the user's Obsidian vault folder."""
    vault_base = current_app.config['OBSIDIAN_VAULT_BASE']
    user_vault = os.path.join(vault_base, user.username)
    folder_path = os.path.join(user_vault, note.folder.strip('/'))
    os.makedirs(folder_path, exist_ok=True)
    
    safe_title = "".join(c for c in note.title if c.isalnum() or c in (' ', '-', '_', '.')).strip()
    file_path = os.path.join(folder_path, f'{safe_title}.md')
    
    frontmatter = f"""---
title: {note.title}
tags: [{note.tags}]
category: {note.category or 'general'}
source: {note.source_type or 'manual'}
created: {note.created_at.strftime('%Y-%m-%d %H:%M:%S') if note.created_at else ''}
updated: {note.updated_at.strftime('%Y-%m-%d %H:%M:%S') if note.updated_at else ''}
---

"""
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(frontmatter + note.content)
    return file_path


def _delete_obsidian_note(note, user):
    vault_base = current_app.config['OBSIDIAN_VAULT_BASE']
    user_vault = os.path.join(vault_base, user.username)
    folder_path = os.path.join(user_vault, note.folder.strip('/'))
    safe_title = "".join(c for c in note.title if c.isalnum() or c in (' ', '-', '_', '.')).strip()
    file_path = os.path.join(folder_path, f'{safe_title}.md')
    if os.path.exists(file_path):
        os.remove(file_path)


def _record_activity(activity_type, content='', topic=''):
    activity = LearningActivity(
        user_id=current_user.id,
        activity_type=activity_type,
        content=content,
        topic=topic
    )
    db.session.add(activity)
    db.session.commit()


def _extract_topics_from_tags(tags_str):
    if not tags_str:
        return ''
    tags = [t.strip() for t in tags_str.split(',') if t.strip()]
    return tags[0] if tags else ''


@notes_bp.route('/')
@login_required
def note_list():
    folder = request.args.get('folder', '')
    search = request.args.get('search', '')
    
    query = Note.query.filter_by(user_id=current_user.id)
    
    if folder:
        query = query.filter(Note.folder.like(f'%{folder}%'))
    if search:
        query = query.filter(
            db.or_(
                Note.title.ilike(f'%{search}%'),
                Note.content.ilike(f'%{search}%'),
                Note.tags.ilike(f'%{search}%')
            )
        )
        _record_activity('search', f'搜索: {search}', search)
    
    notes = query.order_by(Note.updated_at.desc()).all()
    
    folders = db.session.query(Note.folder).filter_by(user_id=current_user.id)\
        .distinct().order_by(Note.folder).all()
    folders = [f[0] for f in folders]
    
    return render_template('notes/list.html', notes=notes, folders=folders,
                           current_folder=folder, search=search)


@notes_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_note():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '')
        folder = request.form.get('folder', '/').strip() or '/'
        tags = request.form.get('tags', '').strip()
        category = request.form.get('category', 'general').strip()
        
        if not title:
            flash('请输入标题', 'error')
            return render_template('notes/edit.html', note=None, folders=[])
        
        note = Note(
            user_id=current_user.id,
            title=title,
            content=content,
            folder=folder,
            tags=tags,
            category=category,
            source_type='manual'
        )
        db.session.add(note)
        db.session.commit()
        
        _sync_note_to_obsidian(note, current_user)
        _record_activity('note_created', f'创建笔记: {title}', _extract_topics_from_tags(tags))
        
        flash('笔记已创建', 'success')
        return redirect(url_for('notes.view_note', note_id=note.id))
    
    folders = db.session.query(Note.folder).filter_by(user_id=current_user.id)\
        .distinct().order_by(Note.folder).all()
    folders = [f[0] for f in folders]
    
    return render_template('notes/edit.html', note=None, folders=folders)


@notes_bp.route('/<int:note_id>')
@login_required
def view_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id and not current_user.is_admin:
        flash('无权访问', 'error')
        return redirect(url_for('notes.note_list'))
    
    html_content = markdown.markdown(note.content, extensions=['fenced_code', 'tables', 'toc'])
    _record_activity('topic_viewed', f'查看: {note.title}', _extract_topics_from_tags(note.tags))
    
    return render_template('notes/view.html', note=note, html_content=html_content)


@notes_bp.route('/<int:note_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id:
        flash('无权编辑', 'error')
        return redirect(url_for('notes.note_list'))
    
    if request.method == 'POST':
        note.title = request.form.get('title', '').strip()
        note.content = request.form.get('content', '')
        note.folder = request.form.get('folder', '/').strip() or '/'
        note.tags = request.form.get('tags', '').strip()
        note.category = request.form.get('category', 'general').strip()
        db.session.commit()
        
        _sync_note_to_obsidian(note, current_user)
        _record_activity('note_edited', f'编辑: {note.title}', _extract_topics_from_tags(note.tags))
        
        flash('已更新', 'success')
        return redirect(url_for('notes.view_note', note_id=note.id))
    
    folders = db.session.query(Note.folder).filter_by(user_id=current_user.id)\
        .distinct().order_by(Note.folder).all()
    folders = [f[0] for f in folders]
    
    return render_template('notes/edit.html', note=note, folders=folders)


@notes_bp.route('/<int:note_id>/delete', methods=['POST'])
@login_required
def delete_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id:
        flash('无权删除', 'error')
        return redirect(url_for('notes.note_list'))
    
    _delete_obsidian_note(note, current_user)
    title = note.title
    db.session.delete(note)
    db.session.commit()
    _record_activity('note_deleted', f'删除: {title}')
    
    flash('已删除', 'success')
    return redirect(url_for('notes.note_list'))
