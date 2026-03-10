"""AI Assistant - independent tab with persistent conversation history.

Token-saving strategy:
1. Rolling summary: When a conversation exceeds SUMMARY_THRESHOLD messages,
   the older messages are compressed into a summary by the LLM.
2. Context window: Only the last CONTEXT_WINDOW messages are sent to the LLM,
   plus the rolling summary as system context.
3. Title auto-generation: First user message auto-generates a conversation title.
"""
import json
import urllib.request
import urllib.error
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import (LearningActivity, SystemConfig, Conversation, ChatMessage)

assistant_bp = Blueprint('assistant', __name__, url_prefix='/assistant')

# --- Config ---
CONTEXT_WINDOW = 10       # max recent messages sent to LLM
SUMMARY_THRESHOLD = 16    # trigger summary compression after this many messages
SUMMARY_BATCH = 10        # how many old messages to summarize at once


def _get_llm_config():
    """Retrieve LLM configuration from SystemConfig."""
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


def _call_llm(api_base, api_key, model, messages, max_tokens=2000, temperature=0.7):
    """Call LLM API and return the response text."""
    url = f'{api_base.rstrip("/")}/chat/completions'
    payload = json.dumps({
        'model': model,
        'messages': messages,
        'temperature': temperature,
        'max_tokens': max_tokens
    }).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        return result['choices'][0]['message']['content']


def _build_system_prompt(conversation):
    """Build system prompt including rolling summary if available."""
    base = '你是一个智能知识库助手，擅长学习辅导、工作指导和生活建议。请用中文回答，回答简洁有条理。'

    if conversation.summary:
        base += f'\n\n以下是你和用户之前对话的摘要，请参考这些上下文来回答问题：\n{conversation.summary}'

    return base


def _maybe_compress(conversation, api_base, api_key, model):
    """If message count exceeds threshold, compress older messages into summary.
    
    Strategy: take the oldest SUMMARY_BATCH messages that haven't been summarized yet,
    ask the LLM to produce a concise summary, append to conversation.summary,
    then we can rely on the sliding window + summary for future calls.
    """
    total = conversation.message_count
    if total < SUMMARY_THRESHOLD:
        return

    # Get all messages in order
    all_msgs = conversation.messages.order_by(ChatMessage.created_at.asc()).all()
    # We want to summarize messages that are outside the context window
    msgs_to_summarize = all_msgs[:max(0, len(all_msgs) - CONTEXT_WINDOW)]
    if len(msgs_to_summarize) < 4:  # not enough to bother summarizing
        return

    # Check if we already have a summary covering these messages
    # Simple heuristic: only re-summarize when there are enough new old messages
    existing_summary = conversation.summary or ''
    
    # Build the text to summarize
    convo_text = ''
    for m in msgs_to_summarize[-SUMMARY_BATCH:]:
        role_label = '用户' if m.role == 'user' else 'AI'
        convo_text += f'{role_label}: {m.content}\n'

    summary_prompt = [
        {'role': 'system', 'content': '你是一个对话摘要助手。请将以下对话内容压缩成简洁的摘要，保留关键信息、用户的问题和你给出的重要结论。摘要控制在200字以内。'},
    ]
    if existing_summary:
        summary_prompt.append({'role': 'user', 'content': f'已有的历史摘要：\n{existing_summary}\n\n新增的对话内容：\n{convo_text}\n\n请合并生成一个更新的摘要：'})
    else:
        summary_prompt.append({'role': 'user', 'content': f'请总结以下对话：\n{convo_text}'})

    try:
        new_summary = _call_llm(api_base, api_key, model, summary_prompt,
                                max_tokens=500, temperature=0.3)
        conversation.summary = new_summary
        db.session.commit()
    except Exception:
        pass  # fail silently, summary is optional


def _auto_title(conversation, first_message, api_base, api_key, model):
    """Auto-generate a short title from the first user message."""
    try:
        title_prompt = [
            {'role': 'system', 'content': '根据用户的问题，生成一个简短的对话标题（不超过15个字），直接输出标题文字即可，不要加任何标点或前缀。'},
            {'role': 'user', 'content': first_message}
        ]
        title = _call_llm(api_base, api_key, model, title_prompt,
                          max_tokens=50, temperature=0.3)
        conversation.title = title.strip()[:50]
        db.session.commit()
    except Exception:
        # Fallback: use first 20 chars of message
        conversation.title = first_message[:20] + ('...' if len(first_message) > 20 else '')
        db.session.commit()


# ===================== Routes =====================

@assistant_bp.route('/')
@login_required
def assistant_page():
    """Render the AI assistant page."""
    llm_provider = SystemConfig.get('llm_provider', '')
    llm_model = SystemConfig.get('llm_model', '')

    # Get user's conversations, newest first
    conversations = Conversation.query.filter_by(user_id=current_user.id) \
        .order_by(Conversation.updated_at.desc()).all()

    # Current conversation: latest one or None
    current_conv = conversations[0] if conversations else None
    conv_id = request.args.get('conv_id', type=int)
    if conv_id:
        c = Conversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
        if c:
            current_conv = c

    # Load messages for current conversation
    messages = []
    if current_conv:
        messages = [m.to_dict() for m in
                    current_conv.messages.order_by(ChatMessage.created_at.asc()).all()]

    return render_template('assistant/chat.html',
                           llm_provider=llm_provider,
                           llm_model=llm_model,
                           conversations=conversations,
                           current_conv=current_conv,
                           messages=messages)


@assistant_bp.route('/conversations', methods=['GET'])
@login_required
def list_conversations():
    """API: list all conversations for current user."""
    convs = Conversation.query.filter_by(user_id=current_user.id) \
        .order_by(Conversation.updated_at.desc()).all()
    return jsonify([{
        'id': c.id,
        'title': c.title,
        'message_count': c.message_count,
        'updated_at': c.updated_at.strftime('%m-%d %H:%M')
    } for c in convs])


@assistant_bp.route('/conversations/new', methods=['POST'])
@login_required
def new_conversation():
    """API: create a new conversation."""
    conv = Conversation(user_id=current_user.id, title='新对话')
    db.session.add(conv)
    db.session.commit()
    return jsonify({'id': conv.id, 'title': conv.title})


@assistant_bp.route('/conversations/<int:conv_id>/delete', methods=['POST'])
@login_required
def delete_conversation(conv_id):
    """API: delete a conversation."""
    conv = Conversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({'error': '对话不存在'}), 404
    db.session.delete(conv)
    db.session.commit()
    return jsonify({'ok': True})


@assistant_bp.route('/conversations/<int:conv_id>/rename', methods=['POST'])
@login_required
def rename_conversation(conv_id):
    """API: rename a conversation."""
    conv = Conversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({'error': '对话不存在'}), 404
    data = request.get_json()
    new_title = data.get('title', '').strip()
    if new_title:
        conv.title = new_title[:50]
        db.session.commit()
    return jsonify({'ok': True, 'title': conv.title})


@assistant_bp.route('/conversations/<int:conv_id>/messages', methods=['GET'])
@login_required
def get_messages(conv_id):
    """API: get all messages in a conversation."""
    conv = Conversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({'error': '对话不存在'}), 404
    messages = [m.to_dict() for m in
                conv.messages.order_by(ChatMessage.created_at.asc()).all()]
    return jsonify({'messages': messages, 'summary': conv.summary or ''})


@assistant_bp.route('/send', methods=['POST'])
@login_required
def send_message():
    """Send a message to AI, persist it, and return the response."""
    data = request.get_json()
    message = data.get('message', '').strip()
    conv_id = data.get('conversation_id')

    if not message:
        return jsonify({'error': '请输入消息'}), 400

    provider, model, api_key, api_base = _get_llm_config()
    if not provider or not api_key:
        return jsonify({'error': '管理员尚未配置大模型，请联系管理员在后台设置'}), 400
    if not api_base:
        return jsonify({'error': '未配置 API 地址'}), 400

    # Get or create conversation
    conv = None
    is_first_message = False
    if conv_id:
        conv = Conversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if not conv:
        conv = Conversation(user_id=current_user.id, title='新对话')
        db.session.add(conv)
        db.session.commit()
        is_first_message = True

    # Save user message to DB
    user_msg = ChatMessage(conversation_id=conv.id, role='user', content=message)
    db.session.add(user_msg)
    conv.message_count = (conv.message_count or 0) + 1
    conv.updated_at = datetime.utcnow()
    db.session.commit()

    # Record learning activity
    activity = LearningActivity(
        user_id=current_user.id,
        activity_type='ai_query',
        content=message[:500],
        topic=message[:50]
    )
    db.session.add(activity)
    db.session.commit()

    try:
        # Build LLM messages with token-saving strategy:
        # [system prompt with summary] + [last N messages from DB]
        system_prompt = _build_system_prompt(conv)
        llm_messages = [{'role': 'system', 'content': system_prompt}]

        # Fetch recent messages from DB (context window)
        recent = conv.messages.order_by(ChatMessage.created_at.desc()) \
            .limit(CONTEXT_WINDOW).all()
        recent.reverse()  # chronological order
        for m in recent:
            llm_messages.append({'role': m.role, 'content': m.content})

        # Call LLM
        response_text = _call_llm(api_base, api_key, model, llm_messages)

        # Save assistant response to DB
        ai_msg = ChatMessage(conversation_id=conv.id, role='assistant', content=response_text)
        db.session.add(ai_msg)
        conv.message_count = (conv.message_count or 0) + 1
        conv.updated_at = datetime.utcnow()
        db.session.commit()

        # Auto-title on first message (async-ish, after response)
        if is_first_message or conv.title == '新对话':
            _auto_title(conv, message, api_base, api_key, model)

        # Maybe compress older messages into summary
        _maybe_compress(conv, api_base, api_key, model)

        return jsonify({
            'response': response_text,
            'conversation_id': conv.id,
            'conversation_title': conv.title,
            'message_id': ai_msg.id
        })

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='ignore') if e.fp else ''
        return jsonify({'error': f'API错误 {e.code}: {error_body[:200]}'}), 500
    except Exception as e:
        return jsonify({'error': f'调用失败: {str(e)}'}), 500
