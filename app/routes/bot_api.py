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


# ===================== Save Note =====================

@bot_api_bp.route('/save-note', methods=['POST'])
@_bot_auth_required
def bot_save_note(bot_user):
    """Save content as a note.

    Request JSON:
    {
        "title": "笔记标题",
        "content": "笔记内容 (Markdown)",
        "category": "general",
        "tags": "tag1,tag2"
    }
    """
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
