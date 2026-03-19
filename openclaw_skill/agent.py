#!/usr/bin/env python3
"""
OpenClaw Skill Agent - 学习助手
通过 HTTP API 与学习助手后端交互，实现对话、记账、笔记、搜索等功能。

使用方式:
  python agent.py chat "你好，帮我讲讲Python装饰器"
  python agent.py chat --search "最新AI新闻"
  python agent.py new                          # 新建对话
  python agent.py history                      # 对话列表
  python agent.py save "笔记标题" "笔记内容"    # 保存笔记
  python agent.py ping                         # 健康检查

配置方式:
  在同目录下的 config.json 中设置 token 和其他参数
"""

import os
import sys
import json
import urllib.request
import urllib.error
import urllib.parse

# ===================== 读取配置文件 =====================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILE = os.path.join(_SCRIPT_DIR, 'config.json')


def _load_config():
    """从 config.json 加载配置"""
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f'⚠️ 读取配置文件失败: {e}，将使用默认值')
    return {}


_config = _load_config()

API_BASE = _config.get('api_url', 'https://testcase.work:8088')
API_TOKEN = _config.get('token', '')
USER_ID = _config.get('user_id', 'openclaw_user')
USER_NAME = _config.get('user_name', 'OpenClaw')

# 本地状态文件（记住对话 ID）
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.state.json')


def _load_state():
    """加载本地状态（conversation_id 等）"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state):
    """保存本地状态"""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _api_request(endpoint, data=None, method='POST', target_user=None):
    """发送 HTTP 请求到学习助手 API

    Args:
        endpoint: API 路径（不含 /bot-api 前缀）
        data: 请求体数据
        method: HTTP 方法
        target_user: 目标用户名（覆盖默认 USER_ID），用于操作指定用户的数据
    """
    if not API_TOKEN or API_TOKEN == '在这里填入你的 Bot API Token':
        print('❌ 错误: 未配置 API Token')
        print(f'请编辑配置文件 {_CONFIG_FILE}')
        print('将 "token" 字段设置为你的 Bot API Token')
        print('（Token 可在学习助手管理后台 → 系统设置 → Bot API 中生成）')
        sys.exit(1)

    url = f'{API_BASE}/bot-api{endpoint}'
    effective_user = target_user or USER_ID
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_TOKEN}',
        'X-Bot-User': effective_user,
    }

    if data and method != 'GET':
        body = json.dumps(data).encode('utf-8')
    else:
        body = None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='replace')
        try:
            error_data = json.loads(error_body)
            print(f'❌ API 错误 ({e.code}): {error_data.get("error", error_body)}')
        except Exception:
            print(f'❌ API 错误 ({e.code}): {error_body}')
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f'❌ 无法连接到服务器: {e.reason}')
        print(f'   请确认服务地址 {API_BASE} 是否正确且服务正在运行')
        sys.exit(1)
    except Exception as e:
        print(f'❌ 请求失败: {e}')
        sys.exit(1)


def cmd_ping():
    """健康检查"""
    try:
        url = f'{API_BASE}/bot-api/ping'
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            print(f'✅ 服务状态: {result.get("status", "unknown")}')
            print(f'   服务名: {result.get("service", "unknown")}')
    except Exception as e:
        print(f'❌ 服务不可达: {e}')
        sys.exit(1)


def cmd_user_check(username):
    """查询用户是否存在"""
    if not API_TOKEN or API_TOKEN == '在这里填入你的 Bot API Token':
        print(f'❌ 错误: 未配置 API Token')
        print(f'请编辑配置文件 {_CONFIG_FILE}')
        sys.exit(1)

    encoded_name = urllib.parse.quote(username)
    url = f'{API_BASE}/bot-api/user/check?username={encoded_name}'
    headers = {
        'Authorization': f'Bearer {API_TOKEN}',
    }
    req = urllib.request.Request(url, headers=headers, method='GET')

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))

            if result.get('exists'):
                print(f'✅ 用户存在: {result["username"]}')
                print(f'   角色: {result.get("role", "")}')
                print(f'   场景: {result.get("scene", "")}')
                print(f'   注册时间: {result.get("created_at", "")}')
                print(f'   笔记数: {result.get("note_count", 0)}')
                print(f'   对话数: {result.get("conversation_count", 0)}')
            else:
                print(f'❌ 用户 "{username}" 不存在')
                print(f'   请先访问 {result.get("register_url", "https://testcase.work:8088")} 注册账号')

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='replace')
        print(f'❌ API 错误 ({e.code}): {error_body}')
        sys.exit(1)
    except Exception as e:
        print(f'❌ 请求失败: {e}')
        sys.exit(1)


def cmd_chat(message, enable_search=False, target_user=None):
    """发送消息给 AI 助手"""
    state = _load_state()

    payload = {
        'message': message,
        'user_id': target_user or USER_ID,
        'user_name': 'OpenClaw',
        'enable_search': enable_search,
    }

    conv_id = state.get('conversation_id')
    if conv_id:
        payload['conversation_id'] = conv_id

    result = _api_request('/chat', payload, target_user=target_user)

    # 更新状态
    if result.get('conversation_id'):
        state['conversation_id'] = result['conversation_id']
        state['conversation_title'] = result.get('conversation_title', '')
        _save_state(state)

    # 显示结果
    actions = result.get('actions', [])
    if actions:
        print(f'🔍 {" | ".join(actions)}')
        print()

    response = result.get('response', '(无回复)')
    print(response)

    # 记账信息
    finance = result.get('finance_record')
    if finance:
        action_label = {'add': '已记录', 'update': '已修改', 'delete': '已删除'}.get(
            finance.get('action', 'add'), '已处理'
        )
        print(f'\n💰 {action_label}: {finance["type"]} ¥{finance["amount"]} ({finance["category"]})')

    # 显示对话信息
    print(f'\n--- 对话: {result.get("conversation_title", "新对话")} (ID: {result.get("conversation_id")}) ---')


def cmd_new(title='新对话', target_user=None):
    """新建对话"""
    state = _load_state()
    result = _api_request('/conversations/new', {'user_id': target_user or USER_ID, 'title': title}, target_user=target_user)

    if result.get('id'):
        state['conversation_id'] = result['id']
        state['conversation_title'] = result.get('title', title)
        _save_state(state)
        print(f'✅ 已创建新对话: {result["title"]} (ID: {result["id"]})')
    else:
        print(f'❌ 创建失败: {result}')


def cmd_history(target_user=None):
    """查看对话列表"""
    result = _api_request('/conversations', method='GET', target_user=target_user)

    convs = result.get('conversations', [])
    if not convs:
        print('📭 还没有对话记录。')
        return

    state = _load_state()
    current_id = state.get('conversation_id')

    print('📋 对话列表:')
    print()
    for i, c in enumerate(convs, 1):
        marker = ' 👈 当前' if c['id'] == current_id else ''
        print(f'  {i}. {c["title"]} ({c["message_count"]}条, {c["updated_at"]}){marker}')


def cmd_save(title, content, category='general', tags='', target_user=None):
    """保存笔记"""
    payload = {
        'user_id': target_user or USER_ID,
        'title': title,
        'content': content,
        'category': category,
        'tags': tags,
    }
    result = _api_request('/save-note', payload, target_user=target_user)

    if result.get('ok'):
        print(f'📝 已保存笔记: {result["title"]} (ID: {result["note_id"]})')
    else:
        print(f'❌ 保存失败: {result.get("error", "未知错误")}')


def cmd_chat_save(message, enable_search=False, target_user=None):
    """发送消息给 AI 并自动保存回复为笔记（两步操作）
    
    适用于：发送链接 + 保存意图的场景。
    第一步：调用 /bot-api/chat 获取 AI 分析内容
    第二步：调用 POST /bot-api/notes 真正保存笔记
    """
    # 第一步：调用 chat 获取 AI 分析
    state = _load_state()
    payload = {
        'message': message,
        'user_id': target_user or USER_ID,
        'user_name': 'OpenClaw',
        'enable_search': enable_search,
    }
    conv_id = state.get('conversation_id')
    if conv_id:
        payload['conversation_id'] = conv_id

    print('📡 正在分析内容...')
    result = _api_request('/chat', payload, target_user=target_user)

    # 更新状态
    if result.get('conversation_id'):
        state['conversation_id'] = result['conversation_id']
        state['conversation_title'] = result.get('conversation_title', '')
        _save_state(state)

    actions = result.get('actions', [])
    if actions:
        print(f'🔍 {" | ".join(actions)}')

    response = result.get('response', '')
    if not response:
        print('❌ AI 未返回内容，无法保存')
        return

    print(response)
    print()

    # 第二步：从 AI 回复中提取标题并保存笔记
    # 标题提取优先级：Markdown # 标题行 > 内容第一行
    title = ''
    for line in response.split('\n'):
        line = line.strip()
        if line.startswith('# '):
            title = line[2:].strip()
            break
    if not title:
        # 使用第一行非空内容
        for line in response.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                import re as _re
                title = _re.sub(r'[#*\-\[\]()（）]', '', line).strip()[:80]
                break
    if not title:
        title = 'AI 笔记'

    # 简单分类判断
    category = 'general'
    msg_lower = message.lower()
    if any(kw in msg_lower for kw in ['代码', '编程', '开发', 'python', 'java', 'code', '技术', 'api']):
        category = 'study'
    elif any(kw in msg_lower for kw in ['工作', '项目', '会议', '方案']):
        category = 'work'

    note_payload = {
        'title': title,
        'content': response,
        'category': category,
        'tags': '',
    }

    print(f'💾 正在保存笔记: {title}...')
    note_result = _api_request('/notes', note_payload, target_user=target_user)

    if note_result.get('ok'):
        print(f'✅ 已保存笔记: {note_result["title"]} (ID: {note_result["note_id"]})')
    else:
        print(f'❌ 保存失败: {note_result.get("error", "未知错误")}')

    # 记账信息
    finance = result.get('finance_record')
    if finance:
        action_label = {'add': '已记录', 'update': '已修改', 'delete': '已删除'}.get(
            finance.get('action', 'add'), '已处理'
        )
        print(f'\n💰 {action_label}: {finance["type"]} ¥{finance["amount"]} ({finance["category"]})')

    print(f'\n--- 对话: {result.get("conversation_title", "新对话")} (ID: {result.get("conversation_id")}) ---')


def cmd_switch(conv_id):
    """切换到指定对话"""
    state = _load_state()
    state['conversation_id'] = int(conv_id)
    _save_state(state)
    print(f'✅ 已切换到对话 ID: {conv_id}')


# ===================== 知识库（笔记）命令 =====================

def cmd_notes(keyword='', category='', page=1, target_user=None):
    """查看笔记列表"""
    params = f'?page={page}&per_page=20'
    if keyword:
        params += f'&q={urllib.parse.quote(keyword)}'
    if category:
        params += f'&category={urllib.parse.quote(category)}'

    result = _api_request(f'/notes{params}', method='GET', target_user=target_user)

    notes = result.get('notes', [])
    total = result.get('total', 0)
    if not notes:
        print('📭 没有找到笔记。')
        return

    print(f'📝 笔记列表 (共 {total} 条, 第 {result.get("page",1)}/{result.get("pages",1)} 页):')
    print()
    for i, n in enumerate(notes, 1):
        tags_str = f' [{n["tags"]}]' if n.get('tags') else ''
        print(f'  {i}. [{n["category"]}] {n["title"]}{tags_str}')
        print(f'     ID: {n["id"]}  |  更新: {n["updated_at"]}')
        if n.get('content_preview'):
            preview = n['content_preview'].replace('\n', ' ')[:80]
            print(f'     {preview}')
        print()


def cmd_note_view(note_id, target_user=None):
    """查看笔记详情"""
    result = _api_request(f'/notes/{note_id}', method='GET', target_user=target_user)

    print(f'📝 {result["title"]}')
    print(f'   分类: {result["category"]}  |  标签: {result.get("tags", "")}  |  ID: {result["id"]}')
    print(f'   创建: {result["created_at"]}  |  更新: {result["updated_at"]}')
    print(f'{"─" * 50}')
    print(result.get('content', ''))


def cmd_note_edit(note_id, target_user=None, **kwargs):
    """修改笔记"""
    data = {k: v for k, v in kwargs.items() if v is not None}
    if not data:
        print('❌ 请提供要修改的字段（--title / --content / --category / --tags）')
        sys.exit(1)

    result = _api_request(f'/notes/{note_id}', data, method='PUT', target_user=target_user)

    if result.get('ok'):
        print(f'✅ 已更新笔记: {result["title"]} (ID: {result["note_id"]})')
    else:
        print(f'❌ 更新失败: {result.get("error", "未知错误")}')


def cmd_note_delete(note_id, target_user=None):
    """删除笔记"""
    result = _api_request(f'/notes/{note_id}', method='DELETE', target_user=target_user)
    if result.get('ok'):
        print(f'🗑️ {result["message"]}')
    else:
        print(f'❌ 删除失败: {result.get("error", "未知错误")}')


# ===================== 记账命令 =====================

def cmd_finance_list(record_type='', category='', start_date='', end_date='', keyword='', page=1, target_user=None):
    """查看记账列表"""
    params = f'?page={page}&per_page=20'
    if record_type:
        params += f'&type={record_type}'
    if category:
        params += f'&category={urllib.parse.quote(category)}'
    if start_date:
        params += f'&start_date={start_date}'
    if end_date:
        params += f'&end_date={end_date}'
    if keyword:
        params += f'&q={urllib.parse.quote(keyword)}'

    result = _api_request(f'/finance{params}', method='GET', target_user=target_user)

    records = result.get('records', [])
    total = result.get('total', 0)
    summary = result.get('summary', {})

    if not records:
        print('📭 没有找到记账记录。')
        return

    print(f'💰 记账列表 (共 {total} 条, 第 {result.get("page",1)}/{result.get("pages",1)} 页):')
    print()
    print(f'  {"日期":<12} {"类型":<5} {"金额":>10} {"分类":<8} {"描述"}')
    print(f'  {"─"*60}')
    for r in records:
        type_icon = '📉' if r['record_type'] == 'expense' else '📈'
        print(f'  {r["date"]:<12} {type_icon}{r["type"]:<3} ¥{r["amount"]:>8.2f} {r["category"]:<8} {r["description"]}  (ID:{r["id"]})')

    print(f'\n  ── 汇总 ──')
    print(f'  💸 总支出: ¥{summary.get("total_expense", 0):.2f}')
    print(f'  💰 总收入: ¥{summary.get("total_income", 0):.2f}')
    print(f'  📊 结余:   ¥{summary.get("balance", 0):.2f}')


def cmd_finance_add(record_type, amount, category, description='', date='', target_user=None):
    """新增记账"""
    data = {
        'record_type': record_type,
        'amount': float(amount),
        'category': category,
        'description': description,
    }
    if date:
        data['date'] = date

    result = _api_request('/finance', data, target_user=target_user)

    if result.get('ok'):
        print(f'✅ {result["message"]} (ID: {result["record_id"]})')
    else:
        print(f'❌ 添加失败: {result.get("error", "未知错误")}')


def cmd_finance_edit(record_id, target_user=None, **kwargs):
    """修改记账"""
    data = {k: v for k, v in kwargs.items() if v is not None}
    if not data:
        print('❌ 请提供要修改的字段')
        sys.exit(1)

    result = _api_request(f'/finance/{record_id}', data, method='PUT', target_user=target_user)

    if result.get('ok'):
        print(f'✅ {result["message"]}')
    else:
        print(f'❌ 修改失败: {result.get("error", "未知错误")}')


def cmd_finance_delete(record_id, target_user=None):
    """删除记账"""
    result = _api_request(f'/finance/{record_id}', method='DELETE', target_user=target_user)
    if result.get('ok'):
        print(f'🗑️ {result["message"]}')
    else:
        print(f'❌ 删除失败: {result.get("error", "未知错误")}')


def cmd_finance_categories(target_user=None):
    """查看记账分类"""
    result = _api_request('/finance/categories', method='GET', target_user=target_user)
    print('💰 支出分类:')
    for c in result.get('expense_categories', []):
        print(f'  • {c}')
    print()
    print('💰 收入分类:')
    for c in result.get('income_categories', []):
        print(f'  • {c}')


def cmd_help():
    """显示帮助"""
    print(f"""🤖 学习助手 - OpenClaw Skill

用法:
  python agent.py <command> [arguments] [--user <username>]

全局参数:
  --user <username>           指定操作的目标用户（记账/笔记会写入该用户账号）
                              不指定则使用 config.json 中的默认 user_id

⚠️ 数据归属说明:
  记账和笔记数据归属于 --user 指定的用户账号。
  操作他人数据前，请先用 user-check 确认用户存在。
  示例: python agent.py --user 张三 finance

对话命令:
  chat <message>              和 AI 对话
  chat --search <message>     强制联网搜索后对话
  chat-save <message>         对话 + 自动保存回复为笔记（链接保存专用）
  new [title]                 新建对话
  history                     查看对话列表
  switch <id>                 切换到指定对话

知识库命令:
  notes                       查看笔记列表
  notes --search <keyword>    搜索笔记
  notes --category <cat>      按分类查看 (work/study/life/general)
  note <id>                   查看笔记详情
  save <title> <content>      创建笔记
  note-edit <id> --title "新标题" --content "新内容"  修改笔记
  note-del <id>               删除笔记

记账命令:
  finance                     查看记账列表
  finance --type expense      只看支出
  finance --type income       只看收入
  finance --start 2026-03-01 --end 2026-03-31  按日期范围
  finance --category 餐饮     按分类查看
  finance-add expense 88 购物 "买了一本书" 2026-03-17  添加记账
  finance-edit <id> --amount 99 --category 教育        修改记账
  finance-del <id>            删除记账
  finance-cat                 查看分类列表

其他:
  user-check <username>       查询用户是否存在
  ping                        检查服务状态
  help                        显示此帮助

配置文件: {_CONFIG_FILE}

示例:
  python agent.py chat "帮我讲讲Python的装饰器"
  python agent.py --user 张三 notes --search "装饰器"
  python agent.py --user 张三 finance --start 2026-03-01
  python agent.py --user 张三 finance-add expense 30 餐饮 "午饭"
""")


def _parse_named_args(argv, known_args):
    """解析命名参数，如 --title "xxx" --content "yyy" """
    result = {}
    i = 0
    while i < len(argv):
        if argv[i].startswith('--') and argv[i][2:] in known_args:
            key = argv[i][2:]
            if i + 1 < len(argv):
                result[key] = argv[i + 1]
                i += 2
            else:
                i += 1
        else:
            i += 1
    return result


def main():
    if len(sys.argv) < 2:
        cmd_help()
        return

    # Parse global --user argument (can appear anywhere before the command)
    argv = list(sys.argv[1:])
    target_user = None
    if '--user' in argv:
        idx = argv.index('--user')
        if idx + 1 < len(argv):
            target_user = argv[idx + 1]
            argv = argv[:idx] + argv[idx + 2:]  # remove --user and its value
        else:
            print('❌ --user 需要指定用户名')
            sys.exit(1)

    if not argv:
        cmd_help()
        return

    command = argv[0].lower()

    if command == 'ping':
        cmd_ping()
    elif command == 'user-check':
        if len(argv) < 2:
            print('❌ 用法: python agent.py user-check <username>')
            sys.exit(1)
        cmd_user_check(argv[1])
    elif command == 'chat':
        if len(argv) < 2:
            print('❌ 用法: python agent.py chat <message>')
            sys.exit(1)
        enable_search = False
        msg_start = 1
        if argv[1] == '--search':
            enable_search = True
            msg_start = 2
        if len(argv) <= msg_start:
            print('❌ 请提供消息内容')
            sys.exit(1)
        message = ' '.join(argv[msg_start:])
        cmd_chat(message, enable_search, target_user=target_user)
    elif command == 'chat-save':
        if len(argv) < 2:
            print('❌ 用法: python agent.py chat-save <message>')
            print('   示例: python agent.py chat-save "https://example.com 帮我整理保存"')
            sys.exit(1)
        enable_search = False
        msg_start = 1
        if argv[1] == '--search':
            enable_search = True
            msg_start = 2
        if len(argv) <= msg_start:
            print('❌ 请提供消息内容')
            sys.exit(1)
        message = ' '.join(argv[msg_start:])
        cmd_chat_save(message, enable_search, target_user=target_user)
    elif command == 'new':
        title = ' '.join(argv[1:]) if len(argv) > 1 else '新对话'
        cmd_new(title, target_user=target_user)
    elif command in ('history', 'list'):
        cmd_history(target_user=target_user)
    elif command == 'switch':
        if len(argv) < 2:
            print('❌ 用法: python agent.py switch <conversation_id>')
            sys.exit(1)
        cmd_switch(argv[1])
    elif command == 'save':
        if len(argv) < 3:
            print('❌ 用法: python agent.py save <title> <content>')
            sys.exit(1)
        title = argv[1]
        content = ' '.join(argv[2:])
        cmd_save(title, content, target_user=target_user)

    # ---- 知识库命令 ----
    elif command == 'notes':
        args = _parse_named_args(argv[1:], ['search', 'category', 'page'])
        cmd_notes(
            keyword=args.get('search', ''),
            category=args.get('category', ''),
            page=int(args.get('page', 1)),
            target_user=target_user
        )
    elif command == 'note':
        if len(argv) < 2:
            print('❌ 用法: python agent.py note <id>')
            sys.exit(1)
        cmd_note_view(int(argv[1]), target_user=target_user)
    elif command == 'note-edit':
        if len(argv) < 2:
            print('❌ 用法: python agent.py note-edit <id> --title "新标题" --content "新内容"')
            sys.exit(1)
        note_id = int(argv[1])
        args = _parse_named_args(argv[2:], ['title', 'content', 'category', 'tags', 'folder'])
        cmd_note_edit(note_id, target_user=target_user, **args)
    elif command == 'note-del':
        if len(argv) < 2:
            print('❌ 用法: python agent.py note-del <id>')
            sys.exit(1)
        cmd_note_delete(int(argv[1]), target_user=target_user)

    # ---- 记账命令 ----
    elif command == 'finance':
        args = _parse_named_args(argv[1:], ['type', 'category', 'start', 'end', 'search', 'page'])
        cmd_finance_list(
            record_type=args.get('type', ''),
            category=args.get('category', ''),
            start_date=args.get('start', ''),
            end_date=args.get('end', ''),
            keyword=args.get('search', ''),
            page=int(args.get('page', 1)),
            target_user=target_user
        )
    elif command == 'finance-add':
        # finance-add <type> <amount> <category> [description] [date]
        if len(argv) < 4:
            print('❌ 用法: python agent.py finance-add <expense|income> <金额> <分类> [描述] [日期YYYY-MM-DD]')
            sys.exit(1)
        rt = argv[1]
        amount = argv[2]
        cat = argv[3]
        desc = argv[4] if len(argv) > 4 else ''
        dt = argv[5] if len(argv) > 5 else ''
        cmd_finance_add(rt, amount, cat, desc, dt, target_user=target_user)
    elif command == 'finance-edit':
        if len(argv) < 2:
            print('❌ 用法: python agent.py finance-edit <id> --amount 99 --category 教育')
            sys.exit(1)
        record_id = int(argv[1])
        args = _parse_named_args(argv[2:], ['record_type', 'amount', 'category', 'description', 'date'])
        if 'amount' in args:
            args['amount'] = float(args['amount'])
        cmd_finance_edit(record_id, target_user=target_user, **args)
    elif command == 'finance-del':
        if len(argv) < 2:
            print('❌ 用法: python agent.py finance-del <id>')
            sys.exit(1)
        cmd_finance_delete(int(argv[1]), target_user=target_user)
    elif command in ('finance-cat', 'finance-categories'):
        cmd_finance_categories(target_user=target_user)

    elif command in ('help', '-h', '--help'):
        cmd_help()
    else:
        # 当作聊天消息处理
        message = ' '.join(argv)
        cmd_chat(message, target_user=target_user)


if __name__ == '__main__':
    main()
