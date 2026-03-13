import os
import json
import urllib.request
import markdown
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required, current_user
from app import db
from app.models import Note, LearningActivity, SystemConfig

notes_bp = Blueprint('notes', __name__, url_prefix='/notes')

# ============ LLM helpers ============

CATEGORIES = [
    ('general', '通用'), ('work', '工作'), ('study', '学习'),
    ('life', '生活'), ('tech', '技术'), ('finance', '理财'), ('health', '健康')
]
CAT_KEYS = [c[0] for c in CATEGORIES]


def _get_llm_config():
    provider = SystemConfig.get('llm_provider', '')
    model = SystemConfig.get('llm_model', '')
    api_key = SystemConfig.get('llm_api_key', '')
    api_base = SystemConfig.get('llm_api_base', '')
    if not api_base and provider:
        bases = {
            'openai': 'https://api.openai.com/v1',
            'deepseek': 'https://api.deepseek.com/v1',
            'zhipu': 'https://open.bigmodel.cn/api/paas/v4',
            'moonshot': 'https://api.moonshot.cn/v1',
            'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        }
        api_base = bases.get(provider, '')
    return provider, model, api_key, api_base


def _call_llm(api_base, api_key, model, messages, max_tokens=500, temperature=0.1):
    url = f'{api_base.rstrip("/")}/chat/completions'
    payload = json.dumps({
        'model': model, 'messages': messages,
        'temperature': temperature, 'max_tokens': max_tokens
    }).encode('utf-8')
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}
    req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        return result['choices'][0]['message']['content']


def _auto_classify(title, content, tags):
    """Use AI to auto-classify note into one of the predefined categories."""
    provider, model, api_key, api_base = _get_llm_config()
    if not api_key:
        return 'general'
    try:
        cat_str = ', '.join(CAT_KEYS)
        prompt = f"""根据以下笔记内容，判断它最适合的分类。
可选分类：{cat_str}
只需返回一个分类的英文key，不要其他内容。

标题：{title}
标签：{tags}
内容摘要：{content[:500]}"""
        result = _call_llm(api_base, api_key, model,
                           [{'role': 'user', 'content': prompt}],
                           max_tokens=20, temperature=0.1).strip().lower()
        return result if result in CAT_KEYS else 'general'
    except Exception:
        return 'general'


def _semantic_search(search_query, notes):
    """Use AI to rank notes by semantic relevance to the search query."""
    provider, model, api_key, api_base = _get_llm_config()
    if not api_key or not notes:
        return notes

    try:
        notes_info = []
        for n in notes[:50]:  # Limit to 50 notes to avoid token overflow
            notes_info.append({
                'id': n.id,
                'title': n.title,
                'tags': n.tags or '',
                'category': n.category or '',
                'excerpt': (n.content or '')[:150]
            })

        prompt = f"""用户搜索："{search_query}"

以下是笔记列表（JSON格式）：
{json.dumps(notes_info, ensure_ascii=False)}

请根据搜索意图，返回与搜索最相关的笔记ID列表（从最相关到最不相关排序）。
只返回JSON数组格式的ID列表，如 [3, 1, 7]。完全不相关的笔记不要包含在内。"""

        result = _call_llm(api_base, api_key, model,
                           [{'role': 'user', 'content': prompt}],
                           max_tokens=200, temperature=0.1).strip()

        # Parse the returned ID list
        # Handle cases where AI wraps in markdown code block
        if '```' in result:
            result = result.split('```')[1]
            if result.startswith('json'):
                result = result[4:]
        ranked_ids = json.loads(result.strip())

        # Reorder notes by the ranked IDs
        note_map = {n.id: n for n in notes}
        ranked = [note_map[nid] for nid in ranked_ids if nid in note_map]
        # Append any notes not in the ranked list at the end
        ranked_set = set(ranked_ids)
        for n in notes:
            if n.id not in ranked_set:
                ranked.append(n)
        return ranked
    except Exception:
        return notes


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
    category = request.args.get('category', '')
    
    query = Note.query.filter_by(user_id=current_user.id)
    
    if folder:
        query = query.filter(Note.folder.like(f'%{folder}%'))
    if category:
        query = query.filter(Note.category == category)
    
    notes = query.order_by(Note.updated_at.desc()).all()
    
    # Use AI semantic search if search query is provided
    if search:
        notes = _semantic_search(search, notes)
        _record_activity('search', f'搜索: {search}', search)
    
    folders = db.session.query(Note.folder).filter_by(user_id=current_user.id)\
        .distinct().order_by(Note.folder).all()
    folders = [f[0] for f in folders]
    
    # Count notes per category (unfiltered by category, but respecting folder/search)
    base_query = Note.query.filter_by(user_id=current_user.id)
    if folder:
        base_query = base_query.filter(Note.folder.like(f'%{folder}%'))
    all_notes_for_count = base_query.all()
    total_count = len(all_notes_for_count)
    category_counts = {'__all__': total_count}
    for n in all_notes_for_count:
        cat = n.category or 'general'
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    return render_template('notes/list.html', notes=notes, folders=folders,
                           current_folder=folder, search=search,
                           current_category=category, categories=CATEGORIES,
                           category_counts=category_counts)


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
            return render_template('notes/edit.html', note=None, folders=[], categories=CATEGORIES)
        
        # Auto-classify if user didn't pick a specific category
        if category == 'auto' or category == 'general':
            category = _auto_classify(title, content, tags)
        
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
    
    return render_template('notes/edit.html', note=None, folders=folders, categories=CATEGORIES)


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
        category = request.form.get('category', 'general').strip()
        
        # Auto-classify if user chose auto
        if category == 'auto':
            category = _auto_classify(note.title, note.content, note.tags)
        note.category = category
        db.session.commit()
        
        _sync_note_to_obsidian(note, current_user)
        _record_activity('note_edited', f'编辑: {note.title}', _extract_topics_from_tags(note.tags))
        
        flash('已更新', 'success')
        return redirect(url_for('notes.view_note', note_id=note.id))
    
    folders = db.session.query(Note.folder).filter_by(user_id=current_user.id)\
        .distinct().order_by(Note.folder).all()
    folders = [f[0] for f in folders]
    
    return render_template('notes/edit.html', note=note, folders=folders, categories=CATEGORIES)


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
