"""Bot API - External API for QQ bot (大龙虾) and other integrations.

Provides token-based authentication so external bots can:
1. Chat with AI assistant (with full search/URL/finance capabilities)
2. Manage conversations
3. Record notes

Token is managed in SystemConfig by admin: key = 'bot_api_token'.
Each request must include header: Authorization: Bearer <token>
Also requires X-Bot-User header to identify which user the bot is acting for.
"""
import json
import re
import hashlib
import secrets
from functools import wraps
from datetime import datetime
from flask import Blueprint, request, jsonify
from app import db
from app.models import (User, SystemConfig, Conversation, ChatMessage,
                         Note, LearningActivity, FinanceRecord)

bot_api_bp = Blueprint('bot_api', __name__, url_prefix='/bot-api')


# ===================== Auth Decorator =====================

def _bot_auth_required(f):
    """Verify bot API token and resolve target user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': '缺少认证信息', 'code': 401}), 401
        token = auth_header[7:].strip()

        stored_token = SystemConfig.get('bot_api_token', '')
        if not stored_token or token != stored_token:
            return jsonify({'error': 'API Token 无效', 'code': 401}), 401

        # Resolve user: by header or request body
        bot_user_id = request.headers.get('X-Bot-User', '')
        if not bot_user_id:
            # Also check request body for user_id
            data = request.get_json(silent=True) or {}
            bot_user_id = str(data.get('user_id', ''))

        if not bot_user_id:
            return jsonify({'error': '缺少用户标识 (X-Bot-User header 或 user_id 字段)', 'code': 400}), 400

        # Find or auto-create user by bot_user_id
        # Use a prefixed username to distinguish bot-created users
        username = f'bot_{bot_user_id}'
        user = User.query.filter_by(username=username).first()
        if not user:
            # Auto-create user for this bot identity
            user = User(username=username, role='user')
            user.set_password(secrets.token_hex(16))  # random password
            user.bio = f'由机器人自动创建 (ID: {bot_user_id})'
            db.session.add(user)
            db.session.commit()

        # Inject user into kwargs
        kwargs['bot_user'] = user
        return f(*args, **kwargs)
    return decorated


# ===================== Health Check =====================

@bot_api_bp.route('/ping', methods=['GET'])
def ping():
    """Health check endpoint - no auth required."""
    return jsonify({'status': 'ok', 'service': 'knowledge-base-bot-api'})


# ===================== Chat =====================

@bot_api_bp.route('/chat', methods=['POST'])
@_bot_auth_required
def bot_chat(bot_user):
    """Main chat endpoint. Reuses assistant.py core logic.

    Request JSON:
    {
        "message": "用户消息",
        "user_id": "qq_12345",           // 可选，也可通过 X-Bot-User header
        "conversation_id": 123,           // 可选，续接已有对话
        "enable_search": false,           // 可选，是否强制联网搜索
        "user_name": "用户昵称"           // 可选，用于显示
    }

    Response JSON:
    {
        "response": "AI 回复内容",
        "conversation_id": 123,
        "conversation_title": "对话标题",
        "actions": ["已搜索: xxx"],       // 附加操作
        "finance_record": {...}           // 如有记账
    }
    """
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    conv_id = data.get('conversation_id')
    enable_search = data.get('enable_search', False)
    user_name = data.get('user_name', '')

    if not message:
        return jsonify({'error': '消息不能为空', 'code': 400}), 400

    # Import assistant core functions
    from app.routes.assistant import (
        _get_llm_config, _call_llm, _detect_intent, _web_search,
        _format_search_results, _fetch_url_content, _build_system_prompt,
        _maybe_compress, _auto_title, _classify_and_extract_topic,
        _parse_finance_with_llm, _save_finance_record,
        _get_recent_finance_records, CONTEXT_WINDOW
    )

    provider, model, api_key, api_base = _get_llm_config()
    if not provider or not api_key:
        return jsonify({'error': '管理员尚未配置大模型', 'code': 500}), 500
    if not api_base:
        return jsonify({'error': '未配置 API 地址', 'code': 500}), 500

    # Update user nickname if provided
    if user_name and not bot_user.bio.startswith('昵称'):
        bot_user.bio = f'昵称: {user_name}'
        db.session.commit()

    # Get or create conversation
    conv = None
    is_first_message = False
    if conv_id:
        conv = Conversation.query.filter_by(id=conv_id, user_id=bot_user.id).first()
    if not conv:
        conv = Conversation(user_id=bot_user.id, title='新对话')
        db.session.add(conv)
        db.session.commit()
        is_first_message = True

    # Save user message
    user_msg = ChatMessage(conversation_id=conv.id, role='user', content=message)
    db.session.add(user_msg)
    conv.message_count = (conv.message_count or 0) + 1
    conv.updated_at = datetime.utcnow()
    db.session.commit()

    # Record activity
    try:
        is_learning, topic = _classify_and_extract_topic(message, api_base, api_key, model)
    except Exception:
        is_learning, topic = True, message[:30]

    activity = LearningActivity(
        user_id=bot_user.id,
        activity_type='ai_query',
        content=message[:500],
        topic=topic,
        is_learning=is_learning
    )
    db.session.add(activity)
    db.session.commit()

    try:
        # Intent detection
        intent = _detect_intent(message)
        extra_context = ''
        actions_taken = []

        # URL Analysis
        if intent['has_url']:
            url_contents = []
            for url in intent['urls'][:3]:
                content, error = _fetch_url_content(url)
                if content:
                    url_contents.append(content)
                    actions_taken.append(f'已抓取: {content["title"][:50] or url[:50]}')
            if url_contents:
                parts = ['以下是用户发送的链接的内容（已自动抓取）：\n']
                for uc in url_contents:
                    parts.append(f'--- 网页标题: {uc["title"]} ---')
                    parts.append(f'来源: {uc["url"]}')
                    parts.append(f'正文内容:\n{uc["text"][:4000]}')
                    parts.append('')
                extra_context += '\n'.join(parts)

        # Web Search
        if enable_search or intent['needs_search']:
            search_query = intent.get('search_query', message)
            for kw in ['搜索', '搜一下', '查一下', '查查', '帮我查', '帮我搜', '联网']:
                search_query = search_query.replace(kw, '')
            search_query = search_query.strip() or message

            results = _web_search(search_query)
            if results:
                extra_context += '\n' + _format_search_results(results)
                actions_taken.append(f'已搜索: {search_query[:30]}')

        # Finance Record
        finance_saved = None
        finance_action = None
        if intent.get('is_finance'):
            recent_ctx = _get_recent_finance_records(bot_user.id)
            parsed = _parse_finance_with_llm(message, api_base, api_key, model, recent_ctx)
            if parsed:
                record, finance_action = _save_finance_record(bot_user.id, parsed)
                finance_saved = record
                type_label = '支出' if record.record_type == 'expense' else '收入'

                if finance_action == 'delete':
                    extra_context += (
                        f'\n\n[系统提示] 已根据用户要求删除了一笔记账记录：\n'
                        f'- 类型：{type_label}\n- 金额：¥{record.amount:.2f}\n'
                        f'- 分类：{record.category}\n- 描述：{record.description}\n'
                        f'请在回复中确认已帮用户删除了这笔记录。'
                    )
                elif finance_action == 'update':
                    extra_context += (
                        f'\n\n[系统提示] 已根据用户要求修改了一笔记账记录：\n'
                        f'- 类型：{type_label}\n- 金额：¥{record.amount:.2f}\n'
                        f'- 分类：{record.category}\n- 描述：{record.description}\n'
                        f'- 日期：{record.record_date}\n'
                        f'请在回复中确认已帮用户修改了这笔记录。'
                    )
                else:
                    extra_context += (
                        f'\n\n[系统提示] 已自动识别并保存了一笔记账记录：\n'
                        f'- 类型：{type_label}\n- 金额：¥{record.amount:.2f}\n'
                        f'- 分类：{record.category}\n- 描述：{record.description}\n'
                        f'- 日期：{record.record_date}\n'
                        f'请在回复中确认已帮用户记录了这笔{type_label}。'
                    )

        # Build LLM messages
        system_prompt = _build_system_prompt(conv, extra_context)
        llm_messages = [{'role': 'system', 'content': system_prompt}]

        db.session.expire_all()
        recent = ChatMessage.query.filter_by(conversation_id=conv.id) \
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()).all()
        recent = recent[-CONTEXT_WINDOW:] if len(recent) > CONTEXT_WINDOW else recent
        for m in recent:
            llm_messages.append({'role': m.role, 'content': m.content})

        # Call LLM
        response_text = _call_llm(api_base, api_key, model, llm_messages)
        response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()

        # Save assistant response
        ai_msg = ChatMessage(conversation_id=conv.id, role='assistant', content=response_text)
        db.session.add(ai_msg)
        conv.message_count = (conv.message_count or 0) + 1
        conv.updated_at = datetime.utcnow()
        db.session.commit()

        # Auto-title
        if is_first_message or conv.title == '新对话':
            _auto_title(conv, message, api_base, api_key, model)

        # Compression
        _maybe_compress(conv, api_base, api_key, model)

        result_data = {
            'response': response_text,
            'conversation_id': conv.id,
            'conversation_title': conv.title,
            'message_id': ai_msg.id,
            'actions': actions_taken,
        }

        if finance_saved:
            type_label = '支出' if finance_saved.record_type == 'expense' else '收入'
            finance_data = {
                'type': type_label,
                'amount': finance_saved.amount,
                'category': finance_saved.category,
                'description': finance_saved.description,
                'action': finance_action or 'add',
            }
            if finance_action != 'delete':
                finance_data['id'] = finance_saved.id
                finance_data['date'] = finance_saved.record_date.strftime('%Y-%m-%d')
            else:
                finance_data['date'] = (finance_saved.record_date.strftime('%Y-%m-%d')
                                        if hasattr(finance_saved.record_date, 'strftime')
                                        else str(finance_saved.record_date))
            result_data['finance_record'] = finance_data

        return jsonify(result_data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'调用失败: {str(e)}', 'code': 500}), 500


# ===================== Conversation Management =====================

@bot_api_bp.route('/conversations', methods=['GET'])
@_bot_auth_required
def bot_list_conversations(bot_user):
    """List user's conversations."""
    convs = Conversation.query.filter_by(user_id=bot_user.id) \
        .order_by(Conversation.updated_at.desc()).limit(20).all()
    return jsonify({
        'conversations': [{
            'id': c.id,
            'title': c.title,
            'message_count': c.message_count,
            'updated_at': c.updated_at.strftime('%Y-%m-%d %H:%M')
        } for c in convs]
    })


@bot_api_bp.route('/conversations/new', methods=['POST'])
@_bot_auth_required
def bot_new_conversation(bot_user):
    """Create a new conversation."""
    data = request.get_json() or {}
    title = data.get('title', '新对话')
    conv = Conversation(user_id=bot_user.id, title=title[:50])
    db.session.add(conv)
    db.session.commit()
    return jsonify({'id': conv.id, 'title': conv.title})


@bot_api_bp.route('/conversations/<int:conv_id>/history', methods=['GET'])
@_bot_auth_required
def bot_conversation_history(bot_user, conv_id):
    """Get conversation message history."""
    conv = Conversation.query.filter_by(id=conv_id, user_id=bot_user.id).first()
    if not conv:
        return jsonify({'error': '对话不存在', 'code': 404}), 404

    limit = request.args.get('limit', 20, type=int)
    messages = ChatMessage.query.filter_by(conversation_id=conv.id) \
        .order_by(ChatMessage.created_at.desc()).limit(limit).all()
    messages.reverse()  # chronological order

    return jsonify({
        'conversation_id': conv.id,
        'title': conv.title,
        'messages': [m.to_dict() for m in messages]
    })


# ===================== Notes CRUD =====================

@bot_api_bp.route('/notes', methods=['GET'])
@_bot_auth_required
def bot_list_notes(bot_user):
    """List user's notes with optional filtering and search.

    Query params:
      - category: filter by category (work/study/life/general)
      - tag: filter by tag (substring match)
      - q: search keyword in title and content
      - page: page number (default 1)
      - per_page: items per page (default 20, max 50)
    """
    category = request.args.get('category', '').strip()
    tag = request.args.get('tag', '').strip()
    keyword = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)

    query = Note.query.filter_by(user_id=bot_user.id)

    if category:
        query = query.filter_by(category=category)
    if tag:
        query = query.filter(Note.tags.ilike(f'%{tag}%'))
    if keyword:
        query = query.filter(
            db.or_(
                Note.title.ilike(f'%{keyword}%'),
                Note.content.ilike(f'%{keyword}%')
            )
        )

    query = query.order_by(Note.updated_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'notes': [{
            'id': n.id,
            'title': n.title,
            'category': n.category,
            'tags': n.tags,
            'folder': n.folder,
            'source_type': n.source_type,
            'created_at': n.created_at.strftime('%Y-%m-%d %H:%M'),
            'updated_at': n.updated_at.strftime('%Y-%m-%d %H:%M'),
            'content_preview': n.content[:200] + ('...' if len(n.content) > 200 else '')
        } for n in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'pages': pagination.pages,
    })


@bot_api_bp.route('/notes/<int:note_id>', methods=['GET'])
@_bot_auth_required
def bot_get_note(bot_user, note_id):
    """Get full content of a single note."""
    note = Note.query.filter_by(id=note_id, user_id=bot_user.id).first()
    if not note:
        return jsonify({'error': '笔记不存在', 'code': 404}), 404

    return jsonify({
        'id': note.id,
        'title': note.title,
        'content': note.content,
        'category': note.category,
        'tags': note.tags,
        'folder': note.folder,
        'source_type': note.source_type,
        'source_url': note.source_url or '',
        'created_at': note.created_at.strftime('%Y-%m-%d %H:%M'),
        'updated_at': note.updated_at.strftime('%Y-%m-%d %H:%M'),
    })


@bot_api_bp.route('/notes', methods=['POST'])
@_bot_auth_required
def bot_create_note(bot_user):
    """Create a new note.

    Request JSON:
    {
        "title": "笔记标题",
        "content": "笔记内容 (Markdown)",
        "category": "general",      // optional: work/study/life/general
        "tags": "tag1,tag2",         // optional
        "folder": "/"               // optional
    }
    """
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    title = data.get('title', '').strip()
    category = data.get('category', 'general')
    tags = data.get('tags', '')
    folder = data.get('folder', '/')

    if not content:
        return jsonify({'error': '内容不能为空', 'code': 400}), 400
    if not title:
        first_line = content.split('\n')[0]
        title = re.sub(r'[#*\-\[\]()]', '', first_line).strip()[:50] or '机器人笔记'

    note = Note(
        user_id=bot_user.id,
        title=title,
        content=content,
        category=category,
        tags=tags,
        source_type='bot',
        folder=folder
    )
    db.session.add(note)
    db.session.commit()

    return jsonify({
        'ok': True,
        'note_id': note.id,
        'title': note.title,
        'message': f'已保存笔记：{note.title}'
    })


@bot_api_bp.route('/notes/<int:note_id>', methods=['PUT'])
@_bot_auth_required
def bot_update_note(bot_user, note_id):
    """Update an existing note.

    Request JSON (all fields optional, only provided fields will be updated):
    {
        "title": "新标题",
        "content": "新内容",
        "category": "study",
        "tags": "new_tag1,new_tag2",
        "folder": "/学习"
    }
    """
    note = Note.query.filter_by(id=note_id, user_id=bot_user.id).first()
    if not note:
        return jsonify({'error': '笔记不存在', 'code': 404}), 404

    data = request.get_json() or {}

    if 'title' in data:
        note.title = data['title'].strip()[:200]
    if 'content' in data:
        note.content = data['content']
    if 'category' in data:
        note.category = data['category']
    if 'tags' in data:
        note.tags = data['tags']
    if 'folder' in data:
        note.folder = data['folder']

    note.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'ok': True,
        'note_id': note.id,
        'title': note.title,
        'message': f'已更新笔记：{note.title}'
    })


@bot_api_bp.route('/notes/<int:note_id>', methods=['DELETE'])
@_bot_auth_required
def bot_delete_note(bot_user, note_id):
    """Delete a note."""
    note = Note.query.filter_by(id=note_id, user_id=bot_user.id).first()
    if not note:
        return jsonify({'error': '笔记不存在', 'code': 404}), 404

    title = note.title
    db.session.delete(note)
    db.session.commit()

    return jsonify({
        'ok': True,
        'message': f'已删除笔记：{title}'
    })


# ===================== Legacy: Save Note (兼容旧接口) =====================

@bot_api_bp.route('/save-note', methods=['POST'])
@_bot_auth_required
def bot_save_note(bot_user):
    """Save content as a note (legacy endpoint, redirects to /notes POST)."""
    data = request.get_json() or {}
    content = data.get('content', '').strip()
    title = data.get('title', '').strip()
    category = data.get('category', 'general')
    tags = data.get('tags', '')

    if not content:
        return jsonify({'error': '内容不能为空', 'code': 400}), 400
    if not title:
        first_line = content.split('\n')[0]
        title = re.sub(r'[#*\-\[\]()]', '', first_line).strip()[:50] or '机器人笔记'

    note = Note(
        user_id=bot_user.id,
        title=title,
        content=content,
        category=category,
        tags=tags,
        source_type='bot',
        folder='/'
    )
    db.session.add(note)
    db.session.commit()

    return jsonify({
        'ok': True,
        'note_id': note.id,
        'title': note.title,
        'message': f'已保存笔记：{note.title}'
    })


# ===================== Finance CRUD =====================

@bot_api_bp.route('/finance', methods=['GET'])
@_bot_auth_required
def bot_list_finance(bot_user):
    """List user's finance records with optional filtering.

    Query params:
      - type: filter by record_type (expense/income)
      - category: filter by category
      - start_date: start date (YYYY-MM-DD)
      - end_date: end date (YYYY-MM-DD)
      - q: search keyword in description
      - page: page number (default 1)
      - per_page: items per page (default 20, max 50)
    """
    from datetime import date, timedelta

    record_type = request.args.get('type', '').strip()
    category = request.args.get('category', '').strip()
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    keyword = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)

    query = FinanceRecord.query.filter_by(user_id=bot_user.id)

    if record_type in ('expense', 'income'):
        query = query.filter_by(record_type=record_type)
    if category:
        query = query.filter_by(category=category)
    if keyword:
        query = query.filter(FinanceRecord.description.ilike(f'%{keyword}%'))

    # Date range
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(FinanceRecord.record_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(FinanceRecord.record_date <= ed)
        except ValueError:
            pass

    query = query.order_by(FinanceRecord.record_date.desc(), FinanceRecord.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    # Summary stats for current filter
    from sqlalchemy import func
    stats_query = FinanceRecord.query.filter_by(user_id=bot_user.id)
    if record_type in ('expense', 'income'):
        stats_query = stats_query.filter_by(record_type=record_type)
    if category:
        stats_query = stats_query.filter_by(category=category)
    if start_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            stats_query = stats_query.filter(FinanceRecord.record_date >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
            stats_query = stats_query.filter(FinanceRecord.record_date <= ed)
        except ValueError:
            pass

    total_expense = stats_query.filter_by(record_type='expense') \
        .with_entities(func.coalesce(func.sum(FinanceRecord.amount), 0)).scalar()
    total_income = stats_query.filter_by(record_type='income') \
        .with_entities(func.coalesce(func.sum(FinanceRecord.amount), 0)).scalar()

    return jsonify({
        'records': [{
            'id': r.id,
            'type': '支出' if r.record_type == 'expense' else '收入',
            'record_type': r.record_type,
            'amount': r.amount,
            'category': r.category,
            'description': r.description,
            'date': r.record_date.strftime('%Y-%m-%d'),
            'source': r.source,
            'created_at': r.created_at.strftime('%Y-%m-%d %H:%M'),
        } for r in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'pages': pagination.pages,
        'summary': {
            'total_expense': round(float(total_expense), 2),
            'total_income': round(float(total_income), 2),
            'balance': round(float(total_income) - float(total_expense), 2),
        }
    })


@bot_api_bp.route('/finance/<int:record_id>', methods=['GET'])
@_bot_auth_required
def bot_get_finance(bot_user, record_id):
    """Get a single finance record."""
    record = FinanceRecord.query.filter_by(id=record_id, user_id=bot_user.id).first()
    if not record:
        return jsonify({'error': '记账记录不存在', 'code': 404}), 404

    return jsonify({
        'id': record.id,
        'type': '支出' if record.record_type == 'expense' else '收入',
        'record_type': record.record_type,
        'amount': record.amount,
        'category': record.category,
        'description': record.description,
        'date': record.record_date.strftime('%Y-%m-%d'),
        'source': record.source,
        'created_at': record.created_at.strftime('%Y-%m-%d %H:%M'),
    })


@bot_api_bp.route('/finance', methods=['POST'])
@_bot_auth_required
def bot_create_finance(bot_user):
    """Create a new finance record.

    Request JSON:
    {
        "record_type": "expense",      // "expense" or "income"
        "amount": 88.0,
        "category": "购物",
        "description": "买了一本书",
        "date": "2026-03-17"           // optional, default today
    }
    """
    from datetime import date as date_type

    data = request.get_json() or {}
    record_type = data.get('record_type', 'expense')
    amount = data.get('amount')
    category = data.get('category', '')
    description = data.get('description', '')
    record_date_str = data.get('date', '')

    if record_type not in ('expense', 'income'):
        return jsonify({'error': 'record_type 必须是 expense 或 income', 'code': 400}), 400
    if not amount or float(amount) <= 0:
        return jsonify({'error': '金额必须大于 0', 'code': 400}), 400
    if not category:
        return jsonify({'error': '分类不能为空', 'code': 400}), 400

    # Parse date
    if record_date_str:
        try:
            record_date = datetime.strptime(record_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': '日期格式应为 YYYY-MM-DD', 'code': 400}), 400
    else:
        record_date = date_type.today()

    record = FinanceRecord(
        user_id=bot_user.id,
        record_type=record_type,
        amount=float(amount),
        category=category,
        description=description,
        record_date=record_date,
        source='bot'
    )
    db.session.add(record)
    db.session.commit()

    type_label = '支出' if record_type == 'expense' else '收入'
    return jsonify({
        'ok': True,
        'record_id': record.id,
        'message': f'已记录{type_label}：¥{record.amount} ({category})'
    })


@bot_api_bp.route('/finance/<int:record_id>', methods=['PUT'])
@_bot_auth_required
def bot_update_finance(bot_user, record_id):
    """Update an existing finance record.

    Request JSON (all fields optional):
    {
        "record_type": "expense",
        "amount": 99.0,
        "category": "教育",
        "description": "买了两本书",
        "date": "2026-03-17"
    }
    """
    record = FinanceRecord.query.filter_by(id=record_id, user_id=bot_user.id).first()
    if not record:
        return jsonify({'error': '记账记录不存在', 'code': 404}), 404

    data = request.get_json() or {}

    if 'record_type' in data and data['record_type'] in ('expense', 'income'):
        record.record_type = data['record_type']
    if 'amount' in data and float(data['amount']) > 0:
        record.amount = float(data['amount'])
    if 'category' in data and data['category']:
        record.category = data['category']
    if 'description' in data:
        record.description = data['description']
    if 'date' in data:
        try:
            record.record_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': '日期格式应为 YYYY-MM-DD', 'code': 400}), 400

    db.session.commit()

    type_label = '支出' if record.record_type == 'expense' else '收入'
    return jsonify({
        'ok': True,
        'record_id': record.id,
        'message': f'已修改{type_label}：¥{record.amount} ({record.category})'
    })


@bot_api_bp.route('/finance/<int:record_id>', methods=['DELETE'])
@_bot_auth_required
def bot_delete_finance(bot_user, record_id):
    """Delete a finance record."""
    record = FinanceRecord.query.filter_by(id=record_id, user_id=bot_user.id).first()
    if not record:
        return jsonify({'error': '记账记录不存在', 'code': 404}), 404

    type_label = '支出' if record.record_type == 'expense' else '收入'
    amount = record.amount
    category = record.category
    db.session.delete(record)
    db.session.commit()

    return jsonify({
        'ok': True,
        'message': f'已删除{type_label}：¥{amount} ({category})'
    })


@bot_api_bp.route('/finance/categories', methods=['GET'])
@_bot_auth_required
def bot_finance_categories(bot_user):
    """Get available finance categories."""
    return jsonify({
        'expense_categories': FinanceRecord.EXPENSE_CATEGORIES,
        'income_categories': FinanceRecord.INCOME_CATEGORIES,
    })


# ===================== Admin: Generate Token =====================

@bot_api_bp.route('/admin/generate-token', methods=['POST'])
def admin_generate_token():
    """Generate a new bot API token. Requires admin session login."""
    from flask_login import current_user, login_required
    # Quick auth check
    try:
        if not current_user.is_authenticated or not current_user.is_admin:
            return jsonify({'error': '需要管理员权限', 'code': 403}), 403
    except Exception:
        return jsonify({'error': '需要管理员登录', 'code': 401}), 401

    token = secrets.token_urlsafe(32)
    SystemConfig.set('bot_api_token', token, current_user.id)
    return jsonify({'token': token, 'message': '新 Token 已生成，请妥善保管'})
