"""Content collection routes - collect articles/videos via URL, AI auto-categorizes."""
import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import ContentCollection, Note, LearningActivity, SystemConfig

collect_bp = Blueprint('collect', __name__, url_prefix='/collect')


def _fetch_page_content(url):
    """Fetch webpage content. For videos, extract metadata only to save tokens."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        raise Exception(f'无法访问链接: {str(e)}')
    
    # Extract title
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ''
    
    # Extract meta description
    desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
    if not desc_match:
        desc_match = re.search(r'<meta[^>]*content=["\'](.*?)["\'][^>]*name=["\']description["\']', html, re.IGNORECASE)
    description = desc_match.group(1).strip() if desc_match else ''
    
    # Extract og:description for better social meta
    og_desc_match = re.search(r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
    og_desc = og_desc_match.group(1).strip() if og_desc_match else ''
    
    # Extract keywords
    kw_match = re.search(r'<meta[^>]*name=["\']keywords["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
    keywords = kw_match.group(1).strip() if kw_match else ''
    
    return title, description or og_desc, keywords, html


def _detect_content_type(url):
    """Detect if URL is a video, article, etc."""
    video_domains = ['youtube.com', 'youtu.be', 'bilibili.com', 'b23.tv',
                     'douyin.com', 'tiktok.com', 'v.qq.com', 'ixigua.com',
                     'zhihu.com/zvideo', 'weibo.com/tv']
    url_lower = url.lower()
    for domain in video_domains:
        if domain in url_lower:
            return 'video'
    return 'article'


def _extract_text_from_html(html, max_len=5000):
    """Extract readable text from HTML, limit length to save tokens."""
    # Remove scripts, styles, nav, footer
    html = re.sub(r'<(script|style|nav|footer|header|aside)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Clean whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove common noise
    text = re.sub(r'(cookie|copyright|©|登录|注册|关注|分享|评论|回复|广告).*?[\n。]', '', text, flags=re.IGNORECASE)
    return text[:max_len]


def _extract_video_info(url, html):
    """Extract video metadata without downloading the video to save tokens.
    Strategy: Use page metadata (title + description + tags) instead of transcript."""
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else ''
    
    # Try to get video description from various meta tags
    desc_patterns = [
        r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\'](.*?)["\']',
        r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']',
        r'"description"\s*:\s*"(.*?)"',  # JSON-LD
        r'class=["\']video-desc[^"\']*["\'][^>]*>(.*?)<',  # bilibili
    ]
    desc = ''
    for pat in desc_patterns:
        m = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if m:
            desc = m.group(1).strip()
            if len(desc) > 20:
                break
    
    # Try to get video tags
    tag_patterns = [
        r'"keywords"\s*:\s*"(.*?)"',
        r'"tag"\s*:\s*"(.*?)"',
        r'class=["\']tag[^"\']*["\'][^>]*>(.*?)<',
    ]
    tags = ''
    for pat in tag_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            tags = m.group(1).strip()
            if tags:
                break
    
    # Build a concise text representation
    info = f"视频标题: {title}\n"
    if desc:
        info += f"视频简介: {desc[:500]}\n"
    if tags:
        info += f"标签: {tags}\n"
    
    return title, info


def _call_llm_for_analysis(content_text, content_type, user_scene='general'):
    """Call LLM to analyze and categorize content."""
    provider = SystemConfig.get('llm_provider', '')
    model = SystemConfig.get('llm_model', '')
    api_key = SystemConfig.get('llm_api_key', '')
    api_base = SystemConfig.get('llm_api_base', '')
    
    if not provider or not api_key:
        raise Exception('管理员尚未配置大模型')
    
    if not api_base:
        api_bases = {
            'openai': 'https://api.openai.com/v1',
            'deepseek': 'https://api.deepseek.com/v1',
            'zhipu': 'https://open.bigmodel.cn/api/paas/v4',
            'moonshot': 'https://api.moonshot.cn/v1',
            'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        }
        api_base = api_bases.get(provider, api_base)
    
    scene_desc = {
        'work': '上班族/职场工作',
        'study': '学生/学术学习',
        'life': '日常生活/兴趣爱好',
        'general': '通用'
    }
    
    system_prompt = f"""你是一个智能知识库助手。用户场景是: {scene_desc.get(user_scene, '通用')}。
请分析以下{'视频' if content_type == 'video' else '文章'}内容，返回 JSON 格式：
{{
    "title": "简洁的标题",
    "summary": "200字以内的摘要",
    "key_points": ["要点1", "要点2", "要点3"],
    "category": "work/study/life/tech/finance/health/other 中选一个最匹配的",
    "tags": ["标签1", "标签2", "标签3"],
    "folder": "建议的分类文件夹路径，如 /技术/Python 或 /工作/项目管理"
}}
只返回JSON，不要其他内容。"""

    url = f'{api_base.rstrip("/")}/chat/completions'
    
    payload = json.dumps({
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': content_text[:3000]}  # Limit to save tokens
        ],
        'temperature': 0.3,
        'max_tokens': 1000
    }).encode('utf-8')
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }
    
    req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
    
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        response_text = result['choices'][0]['message']['content']
    
    # Parse JSON from response (handle markdown code blocks)
    response_text = response_text.strip()
    if response_text.startswith('```'):
        response_text = re.sub(r'^```\w*\n?', '', response_text)
        response_text = re.sub(r'\n?```$', '', response_text)
    
    return json.loads(response_text)


@collect_bp.route('/')
@login_required
def collection_list():
    collections = ContentCollection.query.filter_by(user_id=current_user.id)\
        .order_by(ContentCollection.created_at.desc()).all()
    return render_template('collect/list.html', collections=collections)


@collect_bp.route('/add', methods=['POST'])
@login_required
def add_collection():
    """Add a new URL to the collection for AI processing."""
    url = request.form.get('url', '').strip()
    
    if not url:
        flash('请输入链接', 'error')
        return redirect(url_for('collect.collection_list'))
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    content_type = _detect_content_type(url)
    
    collection = ContentCollection(
        user_id=current_user.id,
        url=url,
        content_type=content_type,
        status='pending'
    )
    db.session.add(collection)
    db.session.commit()
    
    # Record activity
    activity = LearningActivity(
        user_id=current_user.id,
        activity_type='content_collected',
        content=f'收藏了一个{"视频" if content_type == "video" else "文章"}: {url[:100]}',
        topic=''
    )
    db.session.add(activity)
    db.session.commit()
    
    flash(f'已添加到收集队列，正在处理...', 'info')
    return redirect(url_for('collect.process_collection', collection_id=collection.id))


@collect_bp.route('/process/<int:collection_id>')
@login_required
def process_collection(collection_id):
    """Process a collected URL - fetch content and call AI."""
    collection = ContentCollection.query.get_or_404(collection_id)
    if collection.user_id != current_user.id:
        flash('无权操作', 'error')
        return redirect(url_for('collect.collection_list'))
    
    if collection.status == 'done':
        flash('该内容已处理完成', 'info')
        return redirect(url_for('collect.collection_list'))
    
    collection.status = 'processing'
    db.session.commit()
    
    try:
        # Step 1: Fetch page content
        title, description, keywords, html = _fetch_page_content(collection.url)
        
        # Step 2: Extract content based on type
        if collection.content_type == 'video':
            # Video: extract metadata only to save tokens
            extracted_title, content_text = _extract_video_info(collection.url, html)
            collection.title = extracted_title or title
        else:
            # Article: extract main text
            content_text = _extract_text_from_html(html)
            collection.title = title
            if description:
                content_text = f"描述: {description}\n\n正文: {content_text}"
        
        collection.raw_content = content_text[:5000]
        
        # Step 3: Call AI for analysis
        try:
            analysis = _call_llm_for_analysis(
                content_text, 
                collection.content_type,
                current_user.scene or 'general'
            )
            
            collection.title = analysis.get('title', collection.title)
            collection.summary = analysis.get('summary', '')
            collection.key_points = json.dumps(analysis.get('key_points', []), ensure_ascii=False)
            collection.category = analysis.get('category', 'other')
            collection.tags = ', '.join(analysis.get('tags', []))
            
            # Step 4: Auto-create a note
            folder = analysis.get('folder', f'/{collection.category}')
            
            # Build markdown note content
            note_content = f"# {collection.title}\n\n"
            note_content += f"> 来源: [{collection.url}]({collection.url})\n"
            note_content += f"> 类型: {'视频' if collection.content_type == 'video' else '文章'}\n"
            note_content += f"> 收集时间: {collection.created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            note_content += f"## 摘要\n\n{collection.summary}\n\n"
            
            key_points = analysis.get('key_points', [])
            if key_points:
                note_content += "## 要点\n\n"
                for point in key_points:
                    note_content += f"- {point}\n"
                note_content += "\n"
            
            if collection.raw_content and collection.content_type != 'video':
                note_content += f"## 原文摘录\n\n{collection.raw_content[:2000]}\n"
            
            note = Note(
                user_id=current_user.id,
                title=collection.title,
                content=note_content,
                folder=folder,
                tags=collection.tags,
                category=collection.category,
                source_url=collection.url,
                source_type=collection.content_type
            )
            db.session.add(note)
            db.session.flush()
            collection.note_id = note.id
            
            collection.status = 'done'
            collection.processed_at = datetime.utcnow()
            
            # Record activity
            activity = LearningActivity(
                user_id=current_user.id,
                activity_type='content_processed',
                content=f'AI整理了: {collection.title}',
                topic=collection.category
            )
            db.session.add(activity)
            
        except Exception as e:
            # AI failed but we still have basic info
            collection.status = 'error'
            collection.error_msg = str(e)[:500]
        
        db.session.commit()
        
        if collection.status == 'done':
            flash(f'内容已整理完成: {collection.title}', 'success')
            # Sync to obsidian
            from app.routes.notes import _sync_note_to_obsidian
            _sync_note_to_obsidian(note, current_user)
        else:
            flash(f'AI分析失败: {collection.error_msg}', 'error')
        
    except Exception as e:
        collection.status = 'error'
        collection.error_msg = str(e)[:500]
        db.session.commit()
        flash(f'处理失败: {str(e)}', 'error')
    
    return redirect(url_for('collect.collection_list'))


@collect_bp.route('/retry/<int:collection_id>')
@login_required
def retry_collection(collection_id):
    """Retry a failed collection."""
    collection = ContentCollection.query.get_or_404(collection_id)
    if collection.user_id != current_user.id:
        flash('无权操作', 'error')
        return redirect(url_for('collect.collection_list'))
    
    collection.status = 'pending'
    collection.error_msg = ''
    db.session.commit()
    
    return redirect(url_for('collect.process_collection', collection_id=collection.id))


@collect_bp.route('/delete/<int:collection_id>', methods=['POST'])
@login_required
def delete_collection(collection_id):
    collection = ContentCollection.query.get_or_404(collection_id)
    if collection.user_id != current_user.id:
        flash('无权操作', 'error')
        return redirect(url_for('collect.collection_list'))
    
    db.session.delete(collection)
    db.session.commit()
    flash('已删除', 'success')
    return redirect(url_for('collect.collection_list'))
