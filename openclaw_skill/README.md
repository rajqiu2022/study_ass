# 学习助手 - OpenClaw Skill

通过 OpenClaw 对接学习助手系统，实现知识库管理、智能记账、联网搜索、AI 对话等功能。

## 安装

### 方式一：复制到 OpenClaw Skills 目录

```bash
# Linux/macOS
cp -r openclaw_skill/ ~/.openclaw/workspace/skills/study-assistant/

# Windows
xcopy openclaw_skill\* %USERPROFILE%\.openclaw\workspace\skills\study-assistant\ /E /I
```

### 方式二：软链接（方便更新）

```bash
# Linux/macOS
ln -s $(pwd)/openclaw_skill ~/.openclaw/workspace/skills/study-assistant

# Windows (管理员 PowerShell)
New-Item -ItemType SymbolicLink -Path "$env:USERPROFILE\.openclaw\workspace\skills\study-assistant" -Target "$(Get-Location)\openclaw_skill"
```

## 配置

### 1. 生成 Bot API Token

登录学习助手管理后台 → 系统设置 → 生成 Bot API Token

### 2. 编辑配置文件

编辑 `config.json`，填入你的 Token：

```json
{
  "api_url": "https://testcase.work:8088",
  "token": "把你的Token粘贴到这里",
  "user_id": "openclaw_user",
  "user_name": "OpenClaw"
}
```

> 💡 `config.json` 和 `SKILL.md`、`agent.py` 在同一目录下，复制到 OpenClaw 时会一起带过去。不需要设置任何环境变量。

### 3. 验证连接

```bash
python agent.py ping
# 输出: ✅ 服务状态: ok
```

## 使用

安装 Skill 后，直接在 OpenClaw 中对话即可触发：

```
你: 帮我讲讲Python的装饰器
AI: (调用学习助手API，返回详细讲解)

你: 花了88块买了一本Python书
AI: (自动记账) 💰 已记录: 支出 ¥88.0 (购物)

你: 搜一下2026年最新的AI新闻
AI: (联网搜索后回答)

你: 帮我记个笔记：装饰器的核心是闭包...
AI: (保存到知识库)

你: https://example.com/python-tips 帮我整理保存
AI: (抓取分析链接 → 自动保存到知识库)

你: 查一下我的笔记
AI: (列出知识库中的笔记)

你: 这个月花了多少钱
AI: (查询账单并展示汇总)
```

### 命令行使用（agent.py）

```bash
# ---- 用户查询 ----
python agent.py user-check 张三              # 查询用户是否存在

# ---- 指定目标用户操作（--user 参数） ----
# 记账和笔记数据归属于 --user 指定的用户账号
python agent.py --user 张三 finance          # 查看张三的记账
python agent.py --user 张三 notes            # 查看张三的笔记
python agent.py --user 张三 finance-add expense 30 餐饮 "午饭"  # 为张三记账

# ---- 对话 ----
python agent.py chat "你好"
python agent.py chat --search "最新AI新闻"
python agent.py chat-save "https://example.com 帮我整理保存"  # 分析+保存笔记
python agent.py new "学习Python"
python agent.py history
python agent.py switch 123

# ---- 知识库 ----
python agent.py notes                          # 查看笔记列表
python agent.py notes --search "装饰器"         # 搜索笔记
python agent.py notes --category study          # 按分类查看
python agent.py note 5                          # 查看笔记详情
python agent.py save "Python笔记" "装饰器是..."  # 创建笔记
python agent.py note-edit 5 --title "新标题"     # 修改笔记
python agent.py note-del 5                      # 删除笔记

# ---- 记账 ----
python agent.py finance                         # 查看记账列表
python agent.py finance --type expense           # 只看支出
python agent.py finance --start 2026-03-01 --end 2026-03-31  # 按日期
python agent.py finance-add expense 30 餐饮 "午饭"    # 添加记账
python agent.py finance-edit 10 --amount 35           # 修改记账
python agent.py finance-del 10                        # 删除记账
python agent.py finance-cat                           # 查看分类
```

## API 说明

| 接口 | 方法 | 功能 |
|------|------|------|
| `/bot-api/ping` | GET | 健康检查（无需认证） |
| `/bot-api/user/check?username=xxx` | GET | 查询用户是否存在（需 Token，不需 X-Bot-User） |
| `/bot-api/user/me` | GET | 获取当前登录用户信息（Web 前端用，基于 Session） |
| `/bot-api/chat` | POST | AI 对话（含搜索/记账/URL分析） |

> ⚠️ **链接保存注意**：`/bot-api/chat` 会抓取分析链接内容，但 **不会** 自动保存笔记。需要在 chat 之后显式调用 `POST /bot-api/notes` 保存。`chat-save` 命令已封装了这个两步流程。

| **对话管理** | | |
| `/bot-api/conversations` | GET | 对话列表 |
| `/bot-api/conversations/new` | POST | 新建对话 |
| `/bot-api/conversations/<id>/history` | GET | 对话历史 |
| **知识库 CRUD** | | |
| `/bot-api/notes` | GET | 笔记列表（支持搜索/分类/分页） |
| `/bot-api/notes/<id>` | GET | 笔记详情 |
| `/bot-api/notes` | POST | 创建笔记 |
| `/bot-api/notes/<id>` | PUT | 修改笔记 |
| `/bot-api/notes/<id>` | DELETE | 删除笔记 |
| **记账 CRUD** | | |
| `/bot-api/finance` | GET | 记账列表（支持类型/分类/日期/搜索/分页，含汇总统计） |
| `/bot-api/finance/<id>` | GET | 记账详情 |
| `/bot-api/finance` | POST | 新增记账 |
| `/bot-api/finance/<id>` | PUT | 修改记账 |
| `/bot-api/finance/<id>` | DELETE | 删除记账 |
| `/bot-api/finance/categories` | GET | 获取分类列表 |

认证: `Authorization: Bearer <token>` + `X-Bot-User: <用户名>`

> **数据归属**：记账和笔记数据归属于 `X-Bot-User` 所指向的用户。系统会按以下顺序匹配用户：① 精确匹配用户名 → ② 匹配 `bot_` 前缀 → ③ 自动创建。传入注册的真实用户名可直接操作该账号。

## 架构

```
OpenClaw 用户 → SKILL.md 触发 → agent.py 执行 → config.json 读取 Token → HTTP API → 学习助手后端
                                                                                         ↓
                                                                                     AI 对话 / 记账 / 搜索 / 笔记 / 查询
```
