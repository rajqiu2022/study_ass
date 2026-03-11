"""AI Assistant - full-featured with web search, URL analysis, and note saving.

Features:
1. Real LLM integration with proper system prompt
2. Web search: auto-detect or user-triggered internet search
3. URL analysis: fetch & summarize any URL the user pastes
4. Save to notes: save AI responses as knowledge base entries
5. Token-saving: rolling summary + sliding context window
"""
import json
import re
import urllib.request
import urllib.error
import urllib.parse
from html.parser import HTMLParser
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app import db
from datetime import date as date_type
from app.models import (LearningActivity, SystemConfig, Conversation, ChatMessage,
                         Note, User, FinanceRecord)

assistant_bp = Blueprint('assistant', __name__, url_prefix='/assistant')

# --- Config ---
CONTEXT_WINDOW = 10
SUMMARY_THRESHOLD = 16
SUMMARY_BATCH = 10


# ===================== HTML Text Extractor =====================

class _HTMLTextExtractor(HTMLParser):
    """Simple HTML to text converter."""
    def __init__(self):
        super().__init__()
        self._result = []
        self._skip = False
        self._skip_tags = {'script', 'style', 'noscript', 'header', 'footer', 'nav'}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True
        if tag in ('br', 'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'tr'):
            self._result.append('\n')

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._result.append(data)

    def get_text(self):
        return ''.join(self._result)


def _html_to_text(html_content):
    """Convert HTML to plain text."""
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(html_content)
        text = extractor.get_text()
        # Clean up whitespace
        lines = [line.strip() for line in text.split('\n')]
        text = '\n'.join(line for line in lines if line)
        return text[:8000]  # limit length
    except Exception:
        return html_content[:8000]


# ===================== LLM Helpers =====================

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


def _call_llm(api_base, api_key, model, messages, max_tokens=3000, temperature=0.7):
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


# ===================== Web Search =====================

def _web_search(query, num_results=5):
    """Search the web using a search API. Falls back to DuckDuckGo HTML scraping."""
    results = []

    # Method 1: Try DuckDuckGo Instant Answer API
    try:
        encoded_q = urllib.parse.quote(query)
        url = f'https://api.duckduckgo.com/?q={encoded_q}&format=json&no_html=1&skip_disambig=1'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))

            # Abstract
            if data.get('Abstract'):
                results.append({
                    'title': data.get('Heading', query),
                    'snippet': data['Abstract'][:500],
                    'url': data.get('AbstractURL', '')
                })

            # Related topics
            for topic in data.get('RelatedTopics', [])[:num_results]:
                if isinstance(topic, dict) and topic.get('Text'):
                    results.append({
                        'title': topic.get('Text', '')[:100],
                        'snippet': topic.get('Text', '')[:300],
                        'url': topic.get('FirstURL', '')
                    })
    except Exception:
        pass

    # Method 2: Fallback - scrape DuckDuckGo HTML search
    if len(results) < 2:
        try:
            encoded_q = urllib.parse.quote(query)
            url = f'https://html.duckduckgo.com/html/?q={encoded_q}'
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                # Extract result snippets with regex
                snippets = re.findall(
                    r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL
                )
                titles = re.findall(
                    r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL
                )
                urls = re.findall(
                    r'class="result__url"[^>]*>(.*?)</a>', html, re.DOTALL
                )
                for i in range(min(num_results, len(snippets))):
                    title = re.sub(r'<[^>]+>', '', titles[i]).strip() if i < len(titles) else ''
                    snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()
                    link = re.sub(r'<[^>]+>', '', urls[i]).strip() if i < len(urls) else ''
                    if snippet:
                        results.append({
                            'title': title,
                            'snippet': snippet[:300],
                            'url': link
                        })
        except Exception:
            pass

    return results[:num_results]


def _format_search_results(results):
    """Format search results into text for LLM context."""
    if not results:
        return '未找到相关搜索结果。'
    parts = ['以下是互联网搜索结果：\n']
    for i, r in enumerate(results, 1):
        parts.append(f'{i}. **{r["title"]}**')
        parts.append(f'   {r["snippet"]}')
        if r.get('url'):
            parts.append(f'   来源: {r["url"]}')
        parts.append('')
    return '\n'.join(parts)


# ===================== URL Fetching =====================

def _fetch_url_content(url):
    """Fetch a URL and extract its main text content."""
    try:
        if not url.startswith('http'):
            url = 'https://' + url

        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get('Content-Type', '')
            if 'text/html' not in content_type and 'text/plain' not in content_type:
                return None, f'不支持的内容类型: {content_type}'

            html = resp.read().decode('utf-8', errors='ignore')

            # Extract title
            title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else ''

            # Extract main text
            text = _html_to_text(html)
            return {'title': title, 'text': text, 'url': url}, None

    except urllib.error.HTTPError as e:
        return None, f'HTTP错误 {e.code}'
    except Exception as e:
        return None, f'获取失败: {str(e)[:100]}'


def _extract_urls(text):
    """Extract URLs from user message."""
    url_pattern = r'https?://[^\s<>\"\'\)）\]】,，。、；;！!？?]+'
    urls = re.findall(url_pattern, text)
    return urls


# ===================== Intent Detection =====================

def _detect_intent(message):
    """Detect special intents in user message."""
    intent = {
        'has_url': False,
        'urls': [],
        'needs_search': False,
        'search_query': '',
    }

    # Check for URLs
    urls = _extract_urls(message)
    if urls:
        intent['has_url'] = True
        intent['urls'] = urls

    # Check if user wants web search
    search_keywords = [
        '搜索', '搜一下', '查一下', '查查', '帮我查', '查找', '搜一搜',
        '联网', '上网', '网上', '最新', '最近', '今天', '今年', '现在',
        '实时', '当前', '目前', '新闻', '热点', '百度', '谷歌', 'google',
        'search', '帮我搜', '查询一下'
    ]
    msg_lower = message.lower()
    for kw in search_keywords:
        if kw in msg_lower:
            intent['needs_search'] = True
            # Extract search query (remove the keyword itself)
            intent['search_query'] = message
            break

    # Check if user wants to record a finance entry
    finance_keywords = [
        '花了', '花费', '消费', '支出', '买了', '购买', '付了', '付款',
        '充值', '缴费', '打车', '吃饭', '外卖', '点了',
        '收入', '工资', '奖金', '进账', '到账', '收到', '赚了', '入账',
        '报销', '红包', '转账收', '兼职',
        '记账', '记一笔', '记录一下',
        '块', '元', '￥', '¥'
    ]
    # Need at least one finance keyword AND a number to be considered finance
    has_finance_kw = any(kw in msg_lower for kw in finance_keywords)
    has_number = bool(re.search(r'\d+\.?\d*', message))
    if has_finance_kw and has_number:
        intent['is_finance'] = True

    return intent


# ===================== Finance Parsing =====================

def _parse_finance_with_llm(message, api_base, api_key, model):
    """Use LLM to parse a finance record from user message.
    Returns dict with: record_type, amount, category, description, record_date or None.
    """
    today = date_type.today().strftime('%Y-%m-%d')
    categories_info = (
        f"支出分类: {', '.join(FinanceRecord.EXPENSE_CATEGORIES)}\n"
        f"收入分类: {', '.join(FinanceRecord.INCOME_CATEGORIES)}"
    )
    prompt = [
        {'role': 'system', 'content': f'''你是一个记账解析助手。今天是 {today}。
用户会用自然语言描述一笔消费或收入，你需要从中提取以下信息，严格以 JSON 格式输出：
{{
  "record_type": "expense" 或 "income",
  "amount": 数字金额,
  "category": "分类名称",
  "description": "简短描述",
  "record_date": "YYYY-MM-DD"
}}

{categories_info}

规则：
1. 如果用户没有说具体日期，默认用今天 {today}
2. 如果说"昨天"就用昨天的日期，"前天"用前天的日期
3. 金额提取纯数字，不要带单位
4. 从上面的预设分类中选择最匹配的，不要自创分类
5. description 简洁概括，不超过20字
6. 只输出 JSON，不要输出任何其他内容'''},
        {'role': 'user', 'content': message}
    ]
    try:
        result = _call_llm(api_base, api_key, model, prompt, max_tokens=200, temperature=0.1)
        # Clean up: remove thinking tags, markdown code blocks
        result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
        result = re.sub(r'^```(?:json)?\s*', '', result, flags=re.MULTILINE)
        result = re.sub(r'```\s*$', '', result, flags=re.MULTILINE)
        result = result.strip()

        data = json.loads(result)
        # Validate
        if data.get('record_type') not in ('expense', 'income'):
            return None
        if not isinstance(data.get('amount'), (int, float)) or data['amount'] <= 0:
            return None
        return data
    except Exception:
        return None


def _save_finance_record(user_id, parsed):
    """Save a parsed finance record to the database. Returns the record."""
    try:
        record_date = datetime.strptime(parsed['record_date'], '%Y-%m-%d').date()
    except (ValueError, KeyError):
        record_date = date_type.today()

    record = FinanceRecord(
        user_id=user_id,
        record_type=parsed['record_type'],
        amount=parsed['amount'],
        category=parsed.get('category', '其他支出' if parsed['record_type'] == 'expense' else '其他收入'),
        description=parsed.get('description', ''),
        record_date=record_date,
        source='ai'
    )
    db.session.add(record)
    db.session.commit()
    return record


# ===================== System Prompt =====================

def _build_system_prompt(conversation, extra_context=''):
    """Build system prompt including rolling summary and user context."""
    base = """你是一个强大的 AI 助手，能够直接帮用户解决各种问题。

核心行为规则：
1. 直接回答问题，给出具体、有价值的内容
2. 绝对不要说"我是XX模型"、"我没有联网能力"之类的话
3. 如果用户的消息中包含链接分析结果或搜索结果，基于这些信息给出详细回答
4. 回答要有结构、有深度，善用 Markdown 格式（标题、列表、代码块、加粗等）
5. 使用中文回答

你的能力：
- 📖 学习辅导：知识讲解、学习方法、难点拆解、考试备考
- 💻 编程开发：代码编写、调试、架构设计、技术选型、最佳实践
- 💼 工作效率：方案撰写、数据分析、流程优化、PPT大纲、邮件撰写
- 🌐 联网搜索：可以搜索互联网获取最新信息
- 🔗 链接分析：可以抓取和分析网页内容，提取要点
- 📝 知识整理：总结要点、生成笔记、思维导图结构、知识归纳
- 🌟 生活建议：理财规划、健康管理、旅行规划、时间管理
- 💰 智能记账：识别消费/收入记录，自动归类并保存（可在记账报表中查看）"""

    # Inject user context
    try:
        user = User.query.get(conversation.user_id)
        if user:
            parts = []
            if user.interests and user.interests.strip():
                parts.append(f'兴趣领域：{user.interests.strip()}')
            if user.current_learning and user.current_learning.strip():
                parts.append(f'当前在学：{user.current_learning.strip()}')
            if user.bio and user.bio.strip():
                parts.append(f'个人简介：{user.bio.strip()}')
            if parts:
                base += '\n\n关于这位用户：\n' + '\n'.join(parts)
    except Exception:
        pass

    # Extra context (search results, URL content, etc.)
    if extra_context:
        base += '\n\n' + extra_context

    # Rolling summary
    if conversation.summary:
        base += f'\n\n以下是你们之前对话的摘要，请参考这些上下文来回答：\n{conversation.summary}'

    return base


# ===================== Compression =====================

def _maybe_compress(conversation, api_base, api_key, model):
    """Compress older messages into summary when threshold is exceeded."""
    total = conversation.message_count
    if total < SUMMARY_THRESHOLD:
        return

    all_msgs = ChatMessage.query.filter_by(conversation_id=conversation.id) \
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()).all()
    msgs_to_summarize = all_msgs[:max(0, len(all_msgs) - CONTEXT_WINDOW)]
    if len(msgs_to_summarize) < 4:
        return

    existing_summary = conversation.summary or ''
    convo_text = ''
    for m in msgs_to_summarize[-SUMMARY_BATCH:]:
        role_label = '用户' if m.role == 'user' else 'AI'
        convo_text += f'{role_label}: {m.content[:200]}\n'

    summary_prompt = [
        {'role': 'system', 'content': '你是一个对话摘要助手。请将以下对话内容压缩成简洁的摘要，保留关键信息。摘要控制在200字以内。'},
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
        pass


def _auto_title(conversation, first_message, api_base, api_key, model):
    """Auto-generate a short title from the first user message."""
    try:
        title_prompt = [
            {'role': 'system', 'content': '根据用户的问题，生成一个简短的对话标题（不超过15个字），直接输出标题文字即可，不要加任何标点或前缀。'},
            {'role': 'user', 'content': first_message}
        ]
        title = _call_llm(api_base, api_key, model, title_prompt,
                          max_tokens=50, temperature=0.3)
        # Clean up: remove quotes, thinking tags, etc.
        title = re.sub(r'<think>.*?</think>', '', title, flags=re.DOTALL).strip()
        title = title.strip('"\'""''「」')
        conversation.title = title.strip()[:50] or first_message[:20]
        db.session.commit()
    except Exception:
        conversation.title = first_message[:20] + ('...' if len(first_message) > 20 else '')
        db.session.commit()


def _classify_and_extract_topic(message, api_base, api_key, model):
    """Use LLM to classify if a message is learning-related or casual chat,
    and extract a concise topic keyword.
    Returns: (is_learning: bool, topic: str)
    """
    try:
        prompt = [
            {'role': 'system', 'content': '''你是一个消息分类助手。判断用户的消息是"学习/知识/技能相关"还是"闲聊/日常/情感"。

分类标准：
- 学习相关：涉及知识学习、技术问题、编程、数学、科学、语言学习、考试备考、专业技能、工作方法论、学术研究、读书笔记等有知识价值的内容
- 闲聊：日常寒暄、情感倾诉、闲谈、笑话、天气、打招呼、无具体知识点的随意聊天、纯粹的生活琐事

严格以 JSON 格式输出，不要输出任何其他内容：
{
  "is_learning": true或false,
  "topic": "精炼的主题关键词（2-8个字）"
}

规则：
1. topic 必须是精炼的关键词，不是完整句子，例如："Python排序算法"、"微积分求导"、"英语语法"
2. 如果是闲聊，topic 填写用户的兴趣方向，例如："美食"、"电影"、"旅行"、"心情"
3. 只输出 JSON，不要有其他文字'''},
            {'role': 'user', 'content': message[:200]}
        ]
        result = _call_llm(api_base, api_key, model, prompt, max_tokens=100, temperature=0.1)
        # Clean up
        result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
        result = re.sub(r'^```(?:json)?\s*', '', result, flags=re.MULTILINE)
        result = re.sub(r'```\s*$', '', result, flags=re.MULTILINE)
        result = result.strip()

        data = json.loads(result)
        is_learning = bool(data.get('is_learning', True))
        topic = str(data.get('topic', ''))[:50]
        return is_learning, topic
    except Exception:
        # Fallback: treat as learning, use truncated message
        return True, message[:30]


# ===================== Routes =====================

@assistant_bp.route('/')
@login_required
def assistant_page():
    """Render the AI assistant page."""
    llm_provider = SystemConfig.get('llm_provider', '')
    llm_model = SystemConfig.get('llm_model', '')

    conversations = Conversation.query.filter_by(user_id=current_user.id) \
        .order_by(Conversation.updated_at.desc()).all()

    current_conv = conversations[0] if conversations else None
    conv_id = request.args.get('conv_id', type=int)
    if conv_id:
        c = Conversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
        if c:
            current_conv = c

    messages = []
    if current_conv:
        messages = [m.to_dict() for m in
                    ChatMessage.query.filter_by(conversation_id=current_conv.id)
                    .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()).all()]

    return render_template('assistant/chat.html',
                           llm_provider=llm_provider,
                           llm_model=llm_model,
                           conversations=conversations,
                           current_conv=current_conv,
                           messages=messages)


@assistant_bp.route('/conversations', methods=['GET'])
@login_required
def list_conversations():
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
    conv = Conversation(user_id=current_user.id, title='新对话')
    db.session.add(conv)
    db.session.commit()
    return jsonify({'id': conv.id, 'title': conv.title})


@assistant_bp.route('/conversations/<int:conv_id>/delete', methods=['POST'])
@login_required
def delete_conversation(conv_id):
    conv = Conversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({'error': '对话不存在'}), 404
    db.session.delete(conv)
    db.session.commit()
    return jsonify({'ok': True})


@assistant_bp.route('/conversations/<int:conv_id>/rename', methods=['POST'])
@login_required
def rename_conversation(conv_id):
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
    conv = Conversation.query.filter_by(id=conv_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({'error': '对话不存在'}), 404
    messages = [m.to_dict() for m in
                ChatMessage.query.filter_by(conversation_id=conv.id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()).all()]
    return jsonify({'messages': messages, 'summary': conv.summary or ''})


@assistant_bp.route('/send', methods=['POST'])
@login_required
def send_message():
    """Main message handler: detect intent -> enrich context -> call LLM."""
    data = request.get_json()
    message = data.get('message', '').strip()
    conv_id = data.get('conversation_id')
    enable_search = data.get('enable_search', False)  # user toggled search on

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

    # Save user message
    user_msg = ChatMessage(conversation_id=conv.id, role='user', content=message)
    db.session.add(user_msg)
    conv.message_count = (conv.message_count or 0) + 1
    conv.updated_at = datetime.utcnow()
    db.session.commit()

    # Record activity - classify message first
    try:
        is_learning, topic = _classify_and_extract_topic(
            message, api_base, api_key, model)
    except Exception:
        is_learning, topic = True, message[:30]

    activity = LearningActivity(
        user_id=current_user.id,
        activity_type='ai_query',
        content=message[:500],
        topic=topic,
        is_learning=is_learning
    )
    db.session.add(activity)
    db.session.commit()

    try:
        # --- Intent detection ---
        intent = _detect_intent(message)
        extra_context = ''
        actions_taken = []  # track what we did for the user

        # --- URL Analysis ---
        if intent['has_url']:
            url_contents = []
            for url in intent['urls'][:3]:  # max 3 URLs
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

        # --- Web Search ---
        if enable_search or intent['needs_search']:
            search_query = intent.get('search_query', message)
            # Clean search query
            for kw in ['搜索', '搜一下', '查一下', '查查', '帮我查', '帮我搜', '联网']:
                search_query = search_query.replace(kw, '')
            search_query = search_query.strip() or message

            results = _web_search(search_query)
            if results:
                extra_context += '\n' + _format_search_results(results)
                actions_taken.append(f'已搜索: {search_query[:30]}')

        # --- Finance Record Detection ---
        finance_saved = None
        if intent.get('is_finance'):
            parsed = _parse_finance_with_llm(message, api_base, api_key, model)
            if parsed:
                record = _save_finance_record(current_user.id, parsed)
                finance_saved = record
                type_label = '支出' if record.record_type == 'expense' else '收入'
                extra_context += (
                    f'\n\n[系统提示] 已自动识别并保存了一笔记账记录：\n'
                    f'- 类型：{type_label}\n'
                    f'- 金额：¥{record.amount:.2f}\n'
                    f'- 分类：{record.category}\n'
                    f'- 描述：{record.description}\n'
                    f'- 日期：{record.record_date}\n'
                    f'请在回复中确认已帮用户记录了这笔{type_label}，并简要总结。'
                    f'可以提醒用户在「记账报表」页面查看详细统计。'
                )

        # --- Build LLM messages ---
        system_prompt = _build_system_prompt(conv, extra_context)
        llm_messages = [{'role': 'system', 'content': system_prompt}]

        # Context window: last N messages (use fresh query to include the just-saved user message)
        db.session.expire_all()  # ensure we see the latest committed data
        recent = ChatMessage.query.filter_by(conversation_id=conv.id) \
            .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc()) \
            .all()
        # Take only the last CONTEXT_WINDOW messages
        recent = recent[-CONTEXT_WINDOW:] if len(recent) > CONTEXT_WINDOW else recent
        for m in recent:
            llm_messages.append({'role': m.role, 'content': m.content})

        # --- Call LLM ---
        response_text = _call_llm(api_base, api_key, model, llm_messages)

        # Clean up response: remove thinking tags if model outputs them
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
            'actions': actions_taken  # tell frontend what enrichments were done
        }
        if finance_saved:
            type_label = '支出' if finance_saved.record_type == 'expense' else '收入'
            result_data['finance_record'] = {
                'id': finance_saved.id,
                'type': type_label,
                'amount': finance_saved.amount,
                'category': finance_saved.category,
                'description': finance_saved.description,
                'date': finance_saved.record_date.strftime('%Y-%m-%d')
            }

        return jsonify(result_data)

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='ignore') if e.fp else ''
        return jsonify({'error': f'API错误 {e.code}: {error_body[:200]}'}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'调用失败: {str(e)}'}), 500


@assistant_bp.route('/search', methods=['POST'])
@login_required
def web_search_api():
    """Standalone web search endpoint."""
    data = request.get_json()
    query = data.get('query', '').strip()
    if not query:
        return jsonify({'error': '请输入搜索内容'}), 400

    results = _web_search(query)
    return jsonify({'results': results})


@assistant_bp.route('/fetch-url', methods=['POST'])
@login_required
def fetch_url_api():
    """Standalone URL fetch endpoint."""
    data = request.get_json()
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': '请输入 URL'}), 400

    content, error = _fetch_url_content(url)
    if error:
        return jsonify({'error': error}), 400
    return jsonify({'content': content})


@assistant_bp.route('/save-note', methods=['POST'])
@login_required
def save_to_note():
    """Save an AI response as a knowledge base note."""
    data = request.get_json()
    content = data.get('content', '').strip()
    title = data.get('title', '').strip()
    category = data.get('category', 'general')
    tags = data.get('tags', '')

    if not content:
        return jsonify({'error': '内容不能为空'}), 400
    if not title:
        # Auto-generate title from first line
        first_line = content.split('\n')[0]
        title = re.sub(r'[#*\-\[\]()]', '', first_line).strip()[:50] or 'AI 笔记'

    note = Note(
        user_id=current_user.id,
        title=title,
        content=content,
        category=category,
        tags=tags,
        source_type='ai_assistant',
        folder='/'
    )
    db.session.add(note)
    db.session.commit()

    return jsonify({
        'ok': True,
        'note_id': note.id,
        'title': note.title,
        'message': f'已保存到知识库：{note.title}'
    })
