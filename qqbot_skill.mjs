/**
 * QQ 机器人 Skill - 对接 AI 助手 Bot API
 *
 * 功能：
 * 1. 接收 QQ 消息（私信 / @机器人），转发给 AI 助手
 * 2. AI 回复自动发回 QQ
 * 3. 支持完整功能：联网搜索、记账、URL 分析、笔记保存
 * 4. 每个 QQ 用户自动维护独立对话上下文
 *
 * 使用方法：
 * 1. 在管理后台生成 Bot API Token
 * 2. 配置下方常量
 * 3. node qqbot_skill.mjs
 *
 * 指令：
 *   /新对话    - 开始新对话（清除上下文）
 *   /搜索 xxx  - 强制联网搜索
 *   /记笔记    - 将上一条 AI 回复保存为笔记
 *   /历史      - 查看最近对话列表
 *   其他消息   - 直接和 AI 对话
 */

import https from 'https';
import http from 'http';
import WebSocket from 'ws';

// ===================== 配置区 =====================
const QQ_APP_ID = '1903238384';
const QQ_APP_SECRET = 'K5qcPC0odSI90skdWQKFB741zxwvvwxz';

// AI 助手 Bot API 配置
const BOT_API_BASE = 'http://127.0.0.1';  // 你的知识库服务地址
const BOT_API_TOKEN = '';  // 从管理后台生成，填在这里

// ===================== 状态管理 =====================
// 每个用户维护一个 conversation_id
const userConversations = new Map();  // qq_user_id -> conversation_id
const lastAIResponse = new Map();    // qq_user_id -> last AI response text

// ===================== HTTP 工具 =====================

function httpRequest(url, options = {}) {
    return new Promise((resolve, reject) => {
        const isHttps = url.startsWith('https');
        const lib = isHttps ? https : http;
        const parsedUrl = new URL(url);

        const reqOpts = {
            hostname: parsedUrl.hostname,
            port: parsedUrl.port || (isHttps ? 443 : 80),
            path: parsedUrl.pathname + parsedUrl.search,
            method: options.method || 'GET',
            headers: options.headers || {},
        };

        const req = lib.request(reqOpts, (res) => {
            let body = '';
            res.on('data', (chunk) => body += chunk);
            res.on('end', () => {
                try {
                    resolve({ status: res.statusCode, data: JSON.parse(body) });
                } catch {
                    resolve({ status: res.statusCode, data: body });
                }
            });
        });

        req.on('error', reject);
        req.setTimeout(120000, () => {
            req.destroy(new Error('Request timeout'));
        });

        if (options.body) {
            req.write(typeof options.body === 'string' ? options.body : JSON.stringify(options.body));
        }
        req.end();
    });
}

// ===================== Bot API 调用 =====================

async function callBotAPI(endpoint, data = {}, method = 'POST') {
    if (!BOT_API_TOKEN) {
        return { error: '未配置 BOT_API_TOKEN，请先在管理后台生成 Token' };
    }

    const url = `${BOT_API_BASE}/bot-api${endpoint}`;
    try {
        const res = await httpRequest(url, {
            method,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${BOT_API_TOKEN}`,
            },
            body: method !== 'GET' ? JSON.stringify(data) : undefined,
        });
        return res.data;
    } catch (e) {
        console.error(`[Bot API] Error calling ${endpoint}:`, e.message);
        return { error: `API 调用失败: ${e.message}` };
    }
}

/**
 * 发消息给 AI 助手
 */
async function chatWithAI(qqUserId, message, options = {}) {
    const convId = userConversations.get(qqUserId);
    const payload = {
        message,
        user_id: qqUserId,
        user_name: options.userName || '',
        enable_search: options.enableSearch || false,
    };
    if (convId) {
        payload.conversation_id = convId;
    }

    const result = await callBotAPI('/chat', payload);

    if (result.conversation_id) {
        userConversations.set(qqUserId, result.conversation_id);
    }
    if (result.response) {
        lastAIResponse.set(qqUserId, result.response);
    }

    return result;
}

/**
 * 新建对话
 */
async function newConversation(qqUserId) {
    userConversations.delete(qqUserId);
    const result = await callBotAPI('/conversations/new', { user_id: qqUserId });
    if (result.id) {
        userConversations.set(qqUserId, result.id);
    }
    return result;
}

/**
 * 保存笔记
 */
async function saveNote(qqUserId, content, title = '') {
    return await callBotAPI('/save-note', {
        user_id: qqUserId,
        content,
        title,
    });
}

/**
 * 获取对话列表
 */
async function getConversations(qqUserId) {
    return await callBotAPI('/conversations', { user_id: qqUserId }, 'GET');
}

// ===================== 消息处理 =====================

/**
 * 处理用户消息，返回回复文本
 */
async function handleMessage(qqUserId, messageText, userName = '') {
    const text = messageText.trim();

    // 指令处理
    if (text === '/新对话' || text === '/new') {
        await newConversation(qqUserId);
        return '✅ 已开始新对话，之前的上下文已清除。';
    }

    if (text === '/历史' || text === '/history') {
        const result = await getConversations(qqUserId);
        if (result.error) return `❌ ${result.error}`;
        const convs = result.conversations || [];
        if (convs.length === 0) return '📭 还没有对话记录。';
        const lines = convs.slice(0, 10).map((c, i) =>
            `${i + 1}. ${c.title} (${c.message_count}条, ${c.updated_at})`
        );
        return `📋 最近对话：\n${lines.join('\n')}`;
    }

    if (text === '/记笔记' || text === '/save') {
        const lastResp = lastAIResponse.get(qqUserId);
        if (!lastResp) return '❌ 没有可保存的 AI 回复。先聊几句吧！';
        const result = await saveNote(qqUserId, lastResp);
        if (result.error) return `❌ 保存失败: ${result.error}`;
        return `📝 已保存笔记：${result.title}`;
    }

    if (text === '/帮助' || text === '/help') {
        return [
            '🤖 AI 助手指令：',
            '',
            '💬 直接发消息 → 和 AI 对话',
            '/新对话 → 开始新对话（清除上下文）',
            '/搜索 内容 → 强制联网搜索',
            '/记笔记 → 将上条 AI 回复保存为笔记',
            '/历史 → 查看最近对话列表',
            '/帮助 → 显示此帮助',
            '',
            '💡 也支持自然语言：',
            '• 发送链接 → 自动抓取分析',
            '• 说"帮我搜xxx" → 自动联网搜索',
            '• 说"花了30块吃饭" → 自动记账',
        ].join('\n');
    }

    // 搜索指令
    let enableSearch = false;
    let actualMessage = text;
    if (text.startsWith('/搜索 ') || text.startsWith('/search ')) {
        enableSearch = true;
        actualMessage = text.replace(/^\/(搜索|search)\s+/, '');
    }

    // 普通对话
    const result = await chatWithAI(qqUserId, actualMessage, {
        userName,
        enableSearch,
    });

    if (result.error) {
        return `❌ ${result.error}`;
    }

    let reply = result.response || '(AI 未返回内容)';

    // 附加操作提示
    const actions = result.actions || [];
    if (actions.length > 0) {
        reply = `🔍 ${actions.join(' | ')}\n\n${reply}`;
    }

    // 记账提示
    if (result.finance_record) {
        const fr = result.finance_record;
        const actionLabel = { add: '已记录', update: '已修改', delete: '已删除' }[fr.action] || '已处理';
        reply += `\n\n💰 ${actionLabel}: ${fr.type} ¥${fr.amount} (${fr.category})`;
    }

    return reply;
}

// ===================== QQ Bot WebSocket =====================

async function getAccessToken() {
    const data = JSON.stringify({ appId: QQ_APP_ID, clientSecret: QQ_APP_SECRET });
    const res = await httpRequest('https://bots.qq.com/app/getAppAccessToken', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: data,
    });
    return res.data.access_token;
}

async function getGateway(token) {
    const res = await httpRequest('https://api.sgroup.qq.com/gateway', {
        headers: { Authorization: `QQBot ${token}` },
    });
    return res.data.url;
}

/**
 * 通过 QQ API 回复消息
 */
async function replyQQMessage(token, channelId, msgId, content, eventId) {
    const url = `https://api.sgroup.qq.com/channels/${channelId}/messages`;
    const body = {
        content: content.slice(0, 2000),  // QQ 消息长度限制
        msg_id: msgId,
    };
    if (eventId) {
        body.event_id = eventId;
    }
    try {
        await httpRequest(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `QQBot ${token}`,
            },
            body: JSON.stringify(body),
        });
    } catch (e) {
        console.error('[QQ] Reply failed:', e.message);
    }
}

/**
 * 通过 QQ API 回复 C2C (私信) 消息
 */
async function replyC2CMessage(token, openid, msgId, content, eventId) {
    const url = `https://api.sgroup.qq.com/v2/users/${openid}/messages`;
    const body = {
        content: content.slice(0, 2000),
        msg_type: 0,  // 文本
        msg_id: msgId,
    };
    if (eventId) {
        body.event_id = eventId;
    }
    try {
        await httpRequest(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `QQBot ${token}`,
            },
            body: JSON.stringify(body),
        });
    } catch (e) {
        console.error('[QQ] C2C Reply failed:', e.message);
    }
}

/**
 * 通过 QQ API 回复群消息
 */
async function replyGroupMessage(token, groupOpenid, msgId, content, eventId) {
    const url = `https://api.sgroup.qq.com/v2/groups/${groupOpenid}/messages`;
    const body = {
        content: content.slice(0, 2000),
        msg_type: 0,
        msg_id: msgId,
    };
    if (eventId) {
        body.event_id = eventId;
    }
    try {
        await httpRequest(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `QQBot ${token}`,
            },
            body: JSON.stringify(body),
        });
    } catch (e) {
        console.error('[QQ] Group Reply failed:', e.message);
    }
}

/**
 * 启动 QQ 机器人
 */
async function startBot() {
    console.log('[Bot] Starting QQ Bot Skill...');

    if (!BOT_API_TOKEN) {
        console.error('[Bot] ⚠️  BOT_API_TOKEN 未配置！请先在管理后台生成 Token，然后填入本文件。');
    }

    // 检查 Bot API 是否可用
    try {
        const ping = await callBotAPI('/ping', {}, 'GET');
        console.log('[Bot] API Status:', ping.status || 'unknown');
    } catch (e) {
        console.error('[Bot] ⚠️  Bot API 不可达:', e.message);
    }

    const token = await getAccessToken();
    console.log('[Bot] QQ Token obtained');

    const gatewayUrl = await getGateway(token);
    console.log('[Bot] Gateway:', gatewayUrl);

    const ws = new WebSocket(gatewayUrl);
    let lastSeq = null;
    let hbTimer = null;
    let sessionId = null;

    ws.on('open', () => console.log('[Bot]', new Date().toISOString(), 'WebSocket Connected'));

    ws.on('close', (code, reason) => {
        console.log('[Bot]', new Date().toISOString(), `WebSocket Closed: code=${code}`, reason?.toString());
        clearInterval(hbTimer);
        // Auto-reconnect after 5s
        console.log('[Bot] Reconnecting in 5s...');
        setTimeout(startBot, 5000);
    });

    ws.on('error', (e) => console.error('[Bot] WebSocket Error:', e.message));

    ws.on('message', async (raw) => {
        const msg = JSON.parse(raw);
        if (msg.s) lastSeq = msg.s;

        switch (msg.op) {
            case 10: {
                // Hello - start heartbeat & identify
                ws.send(JSON.stringify({ op: 1, d: lastSeq }));

                // Intents: GUILDS(1<<0) | GUILD_MESSAGES(1<<9) | DIRECT_MESSAGE(1<<12)
                // | PUBLIC_GUILD_MESSAGES(1<<30) | GROUP_AND_C2C_EVENT(1<<25)
                const intents = (1 << 0) | (1 << 9) | (1 << 12) | (1 << 25) | (1 << 30);
                ws.send(JSON.stringify({
                    op: 2,
                    d: {
                        token: `QQBot ${token}`,
                        intents,
                        shard: [0, 1],
                    },
                }));

                const interval = msg.d.heartbeat_interval;
                console.log('[Bot] Heartbeat interval:', interval, 'ms');
                hbTimer = setInterval(() => {
                    if (ws.readyState === 1) {
                        ws.send(JSON.stringify({ op: 1, d: lastSeq }));
                    }
                }, interval);
                break;
            }

            case 0: {
                // Dispatch event
                const eventType = msg.t;
                const eventData = msg.d;
                sessionId = eventData?.session_id || sessionId;

                console.log('[Bot] Event:', eventType);

                // 频道 @机器人 消息
                if (eventType === 'AT_MESSAGE_CREATE') {
                    const content = (eventData.content || '').replace(/<@!\d+>/g, '').trim();
                    const userId = eventData.author?.id || 'unknown';
                    const userName = eventData.author?.username || '';
                    const channelId = eventData.channel_id;
                    const msgId = eventData.id;

                    console.log(`[Bot] Channel msg from ${userName}(${userId}): ${content.slice(0, 50)}`);

                    const reply = await handleMessage(userId, content, userName);
                    await replyQQMessage(token, channelId, msgId, reply);
                }

                // 私信消息
                if (eventType === 'DIRECT_MESSAGE_CREATE') {
                    const content = (eventData.content || '').trim();
                    const userId = eventData.author?.id || 'unknown';
                    const userName = eventData.author?.username || '';
                    const guildId = eventData.guild_id;
                    const msgId = eventData.id;

                    console.log(`[Bot] DM from ${userName}(${userId}): ${content.slice(0, 50)}`);

                    const reply = await handleMessage(userId, content, userName);
                    // 私信回复使用 DMS 端点
                    const dmUrl = `https://api.sgroup.qq.com/dms/${guildId}/messages`;
                    try {
                        await httpRequest(dmUrl, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'Authorization': `QQBot ${token}`,
                            },
                            body: JSON.stringify({
                                content: reply.slice(0, 2000),
                                msg_id: msgId,
                            }),
                        });
                    } catch (e) {
                        console.error('[Bot] DM reply failed:', e.message);
                    }
                }

                // QQ 群消息（单聊 C2C）
                if (eventType === 'C2C_MESSAGE_CREATE') {
                    const content = (eventData.content || '').trim();
                    const openid = eventData.author?.user_openid || 'unknown';
                    const msgId = eventData.id;

                    console.log(`[Bot] C2C from ${openid}: ${content.slice(0, 50)}`);

                    const reply = await handleMessage(`c2c_${openid}`, content);
                    await replyC2CMessage(token, openid, msgId, reply);
                }

                // QQ 群 @机器人
                if (eventType === 'GROUP_AT_MESSAGE_CREATE') {
                    const content = (eventData.content || '').replace(/<@!\d+>/g, '').trim();
                    const openid = eventData.author?.member_openid || 'unknown';
                    const groupOpenid = eventData.group_openid;
                    const msgId = eventData.id;

                    console.log(`[Bot] Group msg from ${openid} in ${groupOpenid}: ${content.slice(0, 50)}`);

                    const reply = await handleMessage(`grp_${openid}`, content);
                    await replyGroupMessage(token, groupOpenid, msgId, reply);
                }

                break;
            }

            case 11:
                // Heartbeat ACK
                break;

            default:
                console.log('[Bot] Unknown op:', msg.op);
        }
    });
}

// ===================== 启动 =====================
startBot().catch((e) => {
    console.error('[Bot] Fatal error:', e);
    process.exit(1);
});
