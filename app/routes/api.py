import json
import urllib.request
import urllib.error
from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import LearningActivity, SystemConfig, Note
from sqlalchemy import func

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/chat', methods=['POST'])
@login_required
def chat():
    """Send a message to the configured LLM and get a response."""
    data = request.get_json()
    message = data.get('message', '').strip()
    
    if not message:
        return jsonify({'error': '请输入消息'}), 400
    
    # Get LLM configuration
    provider = SystemConfig.get('llm_provider', '')
    model = SystemConfig.get('llm_model', '')
    api_key = SystemConfig.get('llm_api_key', '')
    api_base = SystemConfig.get('llm_api_base', '')
    
    if not provider or not api_key:
        return jsonify({'error': '管理员尚未配置大模型，请联系管理员设置'}), 400
    
    # Record the AI query activity
    # Extract a topic from the message (first few words)
    topic = message[:50] if len(message) > 50 else message
    activity = LearningActivity(
        user_id=current_user.id,
        activity_type='ai_query',
        content=message[:500],
        topic=topic
    )
    db.session.add(activity)
    db.session.commit()
    
    try:
        response_text = _call_llm(provider, model, api_key, api_base, message)
        return jsonify({'response': response_text})
    except Exception as e:
        return jsonify({'error': f'调用大模型失败: {str(e)}'}), 500


def _call_llm(provider, model, api_key, api_base, message):
    """Call the configured LLM API using OpenAI-compatible format."""
    if not api_base:
        # Default API bases for common providers
        api_bases = {
            'openai': 'https://api.openai.com/v1',
            'deepseek': 'https://api.deepseek.com/v1',
            'zhipu': 'https://open.bigmodel.cn/api/paas/v4',
            'moonshot': 'https://api.moonshot.cn/v1',
            'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'other': api_base
        }
        api_base = api_bases.get(provider, api_base)
    
    url = f'{api_base.rstrip("/")}/chat/completions'
    
    payload = json.dumps({
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是一个学习助手，帮助用户学习和解答问题。请用中文回答。'},
            {'role': 'user', 'content': message}
        ],
        'temperature': 0.7,
        'max_tokens': 2000
    }).encode('utf-8')
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }
    
    req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return result['choices'][0]['message']['content']
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else ''
        raise Exception(f'API返回错误 {e.code}: {error_body[:200]}')
    except urllib.error.URLError as e:
        raise Exception(f'无法连接到API: {str(e)}')


@api_bp.route('/learning-stats')
@login_required
def learning_stats():
    """Get learning statistics for the current user."""
    # Topic distribution
    topic_stats = db.session.query(
        LearningActivity.topic, func.count(LearningActivity.id)
    ).filter(
        LearningActivity.user_id == current_user.id,
        LearningActivity.topic != ''
    ).group_by(LearningActivity.topic)\
     .order_by(func.count(LearningActivity.id).desc())\
     .limit(15).all()
    
    # Activity type distribution
    activity_stats = db.session.query(
        LearningActivity.activity_type, func.count(LearningActivity.id)
    ).filter(
        LearningActivity.user_id == current_user.id
    ).group_by(LearningActivity.activity_type).all()
    
    # Recent activity timeline (last 30 entries)
    recent = LearningActivity.query.filter_by(user_id=current_user.id)\
        .order_by(LearningActivity.created_at.desc()).limit(30).all()
    
    return jsonify({
        'topics': [{'topic': t[0], 'count': t[1]} for t in topic_stats],
        'activity_types': [{'type': a[0], 'count': a[1]} for a in activity_stats],
        'recent': [
            {
                'type': a.activity_type,
                'content': a.content,
                'topic': a.topic,
                'time': a.created_at.strftime('%Y-%m-%d %H:%M')
            } for a in recent
        ]
    })
