---
name: study-assistant
description: 学习助手 - 通过 AI 助手进行知识库管理、智能记账、联网搜索、笔记管理等操作
version: 1.0.0
author: rajqiu
---

# 学习助手 (Study Assistant)

你是一个连接到远程学习助手系统的 AI 技能。通过 HTTP API 与部署在腾讯云服务器上的学习助手后端交互，实现以下功能：

- 💬 **AI 对话**：与 AI 助手进行多轮对话，支持上下文记忆
- 📝 **知识库管理**：保存笔记、查看笔记列表
- 💰 **智能记账**：自然语言记账（如"花了30块吃午饭"），自动解析并保存
- 🌐 **联网搜索**：搜索互联网获取最新信息
- 🔗 **链接分析**：发送链接自动抓取分析网页内容
- 📊 **对话管理**：创建新对话、查看对话列表、查看历史记录

## 配置信息

- **API 地址**: `http://106.55.226.176`
- **认证方式**: Bearer Token（从学习助手管理后台生成）
- **Token 配置**: 写在同目录下的 `config.json` 文件中

### config.json 格式
```json
{
  "api_url": "http://106.55.226.176",
  "token": "你的 Bot API Token",
  "user_id": "openclaw_user",
  "user_name": "OpenClaw"
}
```

## API 端点

> 所有需要认证的接口都必须带上：
> - `Authorization: Bearer <TOKEN>` — 认证 Token
> - `X-Bot-User: <user_id>` — 用户标识（或在请求体中传 `user_id`）
>
> **数据隔离**：每个 user_id 只能查看和操作自己的数据。

---

### 1. 健康检查
```
GET /bot-api/ping
```
无需认证，用于检查服务是否在线。

---

### 2. 用户查询（⚠️ 必须优先调用）
```
GET /bot-api/user/check?username=张三
```
需要 `Authorization: Bearer <TOKEN>`，**不需要** `X-Bot-User` header。

**响应 — 用户存在：**
```json
{
    "exists": true,
    "username": "bot_张三",
    "role": "user",
    "scene": "general",
    "created_at": "2026-03-10 08:00",
    "note_count": 15,
    "conversation_count": 5
}
```

**响应 — 用户不存在：**
```json
{
    "exists": false,
    "username": "张三",
    "register_url": "http://106.55.226.176",
    "message": "用户 \"张三\" 不存在，请先注册账号"
}
```

> ⚠️ **重要**：在使用知识库、记账等任何需要用户身份的功能之前，**必须先调用此接口确认用户账号存在**。如果不存在，告知对方先去 http://106.55.226.176 注册。

---

### 3. AI 对话（核心）
```
POST /bot-api/chat
```
**请求体：**
```json
{
    "message": "用户的消息",
    "user_id": "openclaw_user",
    "conversation_id": 123,
    "enable_search": false,
    "user_name": "OpenClaw用户"
}
```
- `conversation_id` 可选，带上则续接已有对话
- `enable_search` 可选，`true` 表示强制联网搜索

**响应：**
```json
{
    "response": "AI 回复内容",
    "conversation_id": 123,
    "conversation_title": "对话标题",
    "actions": ["已搜索: xxx"],
    "finance_record": {
        "type": "支出",
        "amount": 30.0,
        "category": "餐饮",
        "description": "午饭",
        "action": "add",
        "date": "2026-03-17"
    }
}
```

---

### 4. 对话管理

| 接口 | 方法 | 说明 |
|------|------|------|
| `/bot-api/conversations` | GET | 获取对话列表（最近20条） |
| `/bot-api/conversations/new` | POST | 新建对话，body: `{"user_id":"...", "title":"新对话"}` |
| `/bot-api/conversations/<id>/history` | GET | 获取指定对话的聊天记录，可选 `?limit=20` |

---

### 5. 知识库（笔记）管理 — 完整 CRUD

#### 5.1 查询笔记列表
```
GET /bot-api/notes?category=study&tag=python&q=装饰器&page=1&per_page=20
```
**查询参数（均可选）：**
- `category` — 按分类筛选：`work` / `study` / `life` / `general`
- `tag` — 按标签模糊搜索
- `q` — 按标题和内容关键词搜索
- `page` / `per_page` — 分页（默认 page=1, per_page=20, 最大50）

**响应：**
```json
{
    "notes": [
        {
            "id": 1,
            "title": "Python装饰器笔记",
            "category": "study",
            "tags": "python,编程",
            "folder": "/",
            "source_type": "bot",
            "created_at": "2026-03-17 10:00",
            "updated_at": "2026-03-17 10:30",
            "content_preview": "装饰器的核心是闭包..."
        }
    ],
    "total": 15,
    "page": 1,
    "pages": 1
}
```

#### 5.2 查看笔记详情
```
GET /bot-api/notes/<id>
```
返回完整的笔记内容。

#### 5.3 创建笔记
```
POST /bot-api/notes
```
```json
{
    "title": "笔记标题",
    "content": "笔记内容（支持 Markdown）",
    "category": "study",
    "tags": "tag1,tag2",
    "folder": "/"
}
```
- `title` 可选，不传会自动从内容第一行提取
- `category` 可选，默认 `general`

#### 5.4 修改笔记
```
PUT /bot-api/notes/<id>
```
```json
{
    "title": "新标题",
    "content": "新内容",
    "category": "work",
    "tags": "new_tag"
}
```
只传需要修改的字段即可，不传的字段保持不变。

#### 5.5 删除笔记
```
DELETE /bot-api/notes/<id>
```

> 兼容旧接口：`POST /bot-api/save-note` 仍可用，等价于 `POST /bot-api/notes`。

---

### 6. 记账管理 — 完整 CRUD

#### 6.1 查询记账列表
```
GET /bot-api/finance?type=expense&category=餐饮&start_date=2026-03-01&end_date=2026-03-31&q=午饭&page=1
```
**查询参数（均可选）：**
- `type` — 按类型筛选：`expense`（支出）/ `income`（收入）
- `category` — 按分类筛选
- `start_date` / `end_date` — 日期范围，格式 `YYYY-MM-DD`
- `q` — 按描述关键词搜索
- `page` / `per_page` — 分页

**响应：**
```json
{
    "records": [
        {
            "id": 1,
            "type": "支出",
            "record_type": "expense",
            "amount": 88.0,
            "category": "购物",
            "description": "买了一本Python书",
            "date": "2026-03-17",
            "source": "ai",
            "created_at": "2026-03-17 14:00"
        }
    ],
    "total": 30,
    "page": 1,
    "pages": 2,
    "summary": {
        "total_expense": 1500.0,
        "total_income": 5000.0,
        "balance": 3500.0
    }
}
```
> `summary` 是当前筛选条件下的汇总统计。

#### 6.2 查看单条记账
```
GET /bot-api/finance/<id>
```

#### 6.3 新增记账
```
POST /bot-api/finance
```
```json
{
    "record_type": "expense",
    "amount": 88.0,
    "category": "购物",
    "description": "买了一本书",
    "date": "2026-03-17"
}
```
- `record_type` 必填：`expense` 或 `income`
- `amount` 必填：金额，大于 0
- `category` 必填：分类名称
- `description` 可选
- `date` 可选，默认当天

#### 6.4 修改记账
```
PUT /bot-api/finance/<id>
```
```json
{
    "amount": 99.0,
    "category": "教育",
    "description": "买了两本书"
}
```
只传需要修改的字段。

#### 6.5 删除记账
```
DELETE /bot-api/finance/<id>
```

#### 6.6 获取分类列表
```
GET /bot-api/finance/categories
```
返回系统预设的支出和收入分类：
```json
{
    "expense_categories": ["餐饮","交通","购物","娱乐",...],
    "income_categories": ["工资","奖金","兼职","理财",...]
}
```

---

## 使用规则

当用户发送消息时，请按以下规则处理：

### ⚠️ 用户身份确认（最高优先级）

在执行任何**知识库操作**（笔记增删改查）或**记账操作**（记账增删改查）之前，**必须先确认用户账号**：

1. **询问用户名**：如果还不知道对方的账号名，先问："请问你的账号用户名是什么？"
2. **调用查询接口**：`GET /bot-api/user/check?username=用户名`
3. **判断结果**：
   - 如果 `exists: true` → 记住该用户名，用它作为 `X-Bot-User` 或 `user_id` 发起后续请求
   - 如果 `exists: false` → 告知对方："你的账号还未注册，请先访问 http://106.55.226.176 注册一个账号，然后再来找我。"**不要继续执行操作**
4. **记住身份**：同一次会话中，确认过一次就够了，后续操作不需要重复询问

> 注意：普通 AI 对话（`/bot-api/chat`）不需要提前确认身份，系统会自动创建匿名账号。只有明确要操作知识库或记账数据时才需要确认。

### 指令识别

| 用户说的话 | 动作 |
|-----------|------|
| `/新对话` 或 `/new` | 调用新建对话接口，清除上下文 |
| `/搜索 xxx` 或 `/search xxx` | 调用对话接口，`enable_search: true` |
| `/记笔记 内容` 或 `/save 内容` | 调用 `POST /bot-api/notes` 创建笔记 |
| `/笔记列表` 或 `/notes` | 调用 `GET /bot-api/notes` 查看笔记列表 |
| `/搜笔记 关键词` | 调用 `GET /bot-api/notes?q=关键词` |
| `/账单` 或 `/finance` | 调用 `GET /bot-api/finance` 查看本月账单 |
| `/历史` 或 `/history` | 调用对话列表接口 |
| `/帮助` 或 `/help` | 显示帮助信息（见下方） |
| 其他所有消息 | 调用对话接口进行 AI 对话 |

### 执行流程

1. **对话请求**：使用 `curl` 或 `fetch` 调用 API
2. **上下文维护**：记住最后一次返回的 `conversation_id`，后续请求带上它以维持对话上下文
3. **结果展示**：
   - 普通对话：直接展示 `response` 字段
   - 如有搜索操作：在回复前加上 `🔍 已搜索: xxx`
   - 如有记账：在回复后加上 `💰 已记录/已修改/已删除: 类型 ¥金额 (分类)`
   - 如有 URL 分析：在回复前加上 `🔗 已抓取: 网页标题`
   - 笔记列表：以编号列表展示标题和分类
   - 账单列表：以表格形式展示日期、类型、金额、分类、描述，末尾附上汇总

### 帮助信息

当用户发送 `/帮助` 或 `/help` 时，回复：

```
🤖 学习助手指令：

💬 直接发消息 → 和 AI 对话
/新对话 → 开始新对话（清除上下文）
/搜索 内容 → 强制联网搜索
/记笔记 内容 → 将内容保存为笔记
/笔记列表 → 查看所有笔记
/搜笔记 关键词 → 搜索笔记
/账单 → 查看本月收支
/历史 → 查看最近对话列表
/帮助 → 显示此帮助

💡 也支持自然语言：
• 发送链接 → 自动抓取分析
• 说"帮我搜xxx" → 自动联网搜索
• 说"花了30块吃饭" → 自动记账
• 说"记一下这个知识点" → 保存笔记
• 说"查一下我的笔记" → 搜索知识库
• 说"这个月花了多少钱" → 查询账单
```

## 注意事项

1. **Token 安全**：不要在聊天中泄露 API Token
2. **数据隔离**：每个 user_id 只能操作自己的数据，服务端会校验
3. **超时处理**：AI 对话接口超时设为 120 秒（AI 思考需要时间），其他接口 30 秒即可
4. **消息长度**：单条消息建议不超过 4000 字
5. **对话上下文**：系统会自动维护对话上下文，超过 16 条会自动压缩摘要
6. **记账格式**：通过对话接口用自然语言说即可自动记账，或通过 `/bot-api/finance` 接口手动添加
7. **分页**：笔记和记账列表默认每页 20 条，最大 50 条
