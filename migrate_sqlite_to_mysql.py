#!/usr/bin/env python3
"""
SQLite to MySQL 数据迁移脚本
用法：python migrate_sqlite_to_mysql.py <sqlite_db_path>

步骤：
1. 先从老服务器下载 SQLite 数据库文件（通常是 app.db 或 study_assistant.db）
2. 放到项目根目录或指定路径
3. 运行此脚本进行迁移
"""

import sys
import sqlite3
from datetime import datetime
from flask import Flask
from app import db
from app.models import User, Note, ContentCollection, LearningActivity, Conversation, ChatMessage, FinanceRecord, SystemConfig

# 创建 Flask 应用
app = Flask(__name__)
app.config.from_object('config.Config')
db.init_app(app)


def parse_datetime(dt_str):
    """解析 SQLite 中的 datetime 字符串"""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(str(dt_str).replace('Z', '+00:00'))
    except:
        try:
            return datetime.strptime(str(dt_str), '%Y-%m-%d %H:%M:%S.%f')
        except:
            try:
                return datetime.strptime(str(dt_str), '%Y-%m-%d %H:%M:%S')
            except:
                return None


def parse_date(d_str):
    """解析 SQLite 中的 date 字符串"""
    if not d_str:
        return None
    try:
        return datetime.strptime(str(d_str), '%Y-%m-%d').date()
    except:
        return None


def migrate_users(sqlite_conn, mysql_conn):
    """迁移用户表"""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    
    # 获取列名
    columns = [description[0] for description in cursor.description]
    
    migrated = 0
    for row in users:
        user_dict = dict(zip(columns, row))
        
        # 检查是否已存在
        existing = User.query.filter_by(username=user_dict['username']).first()
        if existing:
            print(f"  用户 {user_dict['username']} 已存在，跳过")
            continue
        
        user = User(
            id=user_dict['id'],
            username=user_dict['username'],
            password_hash=user_dict['password_hash'],
            role=user_dict.get('role', 'user'),
            created_at=parse_datetime(user_dict.get('created_at')),
            last_login=parse_datetime(user_dict.get('last_login')),
            interests=user_dict.get('interests', ''),
            current_learning=user_dict.get('current_learning', ''),
            bio=user_dict.get('bio', ''),
            scene=user_dict.get('scene', 'general')
        )
        db.session.add(user)
        migrated += 1
    
    db.session.commit()
    print(f"  ✅ 迁移用户: {migrated} 条")
    return len(users), migrated


def migrate_notes(sqlite_conn):
    """迁移笔记表"""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM notes")
    notes = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    
    migrated = 0
    for row in notes:
        note_dict = dict(zip(columns, row))
        
        existing = Note.query.filter_by(id=note_dict['id']).first()
        if existing:
            continue
        
        note = Note(
            id=note_dict['id'],
            user_id=note_dict['user_id'],
            title=note_dict['title'],
            content=note_dict.get('content', ''),
            folder=note_dict.get('folder', '/'),
            tags=note_dict.get('tags', ''),
            category=note_dict.get('category', 'general'),
            source_url=note_dict.get('source_url', ''),
            source_type=note_dict.get('source_type', 'manual'),
            created_at=parse_datetime(note_dict.get('created_at')),
            updated_at=parse_datetime(note_dict.get('updated_at'))
        )
        db.session.add(note)
        migrated += 1
    
    db.session.commit()
    print(f"  ✅ 迁移笔记: {migrated} 条")
    return len(notes), migrated


def migrate_content_collections(sqlite_conn):
    """迁移收藏内容表"""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM content_collections")
    items = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    
    migrated = 0
    for row in items:
        item_dict = dict(zip(columns, row))
        
        existing = ContentCollection.query.filter_by(id=item_dict['id']).first()
        if existing:
            continue
        
        collection = ContentCollection(
            id=item_dict['id'],
            user_id=item_dict['user_id'],
            url=item_dict['url'],
            content_type=item_dict.get('content_type', 'article'),
            title=item_dict.get('title', ''),
            summary=item_dict.get('summary', ''),
            key_points=item_dict.get('key_points', ''),
            category=item_dict.get('category', ''),
            tags=item_dict.get('tags', ''),
            raw_content=item_dict.get('raw_content', ''),
            status=item_dict.get('status', 'pending'),
            error_msg=item_dict.get('error_msg', ''),
            note_id=item_dict.get('note_id'),
            created_at=parse_datetime(item_dict.get('created_at')),
            processed_at=parse_datetime(item_dict.get('processed_at'))
        )
        db.session.add(collection)
        migrated += 1
    
    db.session.commit()
    print(f"  ✅ 迁移收藏内容: {migrated} 条")
    return len(items), migrated


def migrate_learning_activities(sqlite_conn):
    """迁移学习活动表"""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM learning_activities")
    items = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    
    migrated = 0
    for row in items:
        item_dict = dict(zip(columns, row))
        
        existing = LearningActivity.query.filter_by(id=item_dict['id']).first()
        if existing:
            continue
        
        activity = LearningActivity(
            id=item_dict['id'],
            user_id=item_dict['user_id'],
            activity_type=item_dict['activity_type'],
            content=item_dict.get('content', ''),
            topic=item_dict.get('topic', ''),
            is_learning=item_dict.get('is_learning', True),
            created_at=parse_datetime(item_dict.get('created_at'))
        )
        db.session.add(activity)
        migrated += 1
    
    db.session.commit()
    print(f"  ✅ 迁移学习活动: {migrated} 条")
    return len(items), migrated


def migrate_conversations(sqlite_conn):
    """迁移对话表"""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM conversations")
    items = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    
    migrated = 0
    for row in items:
        item_dict = dict(zip(columns, row))
        
        existing = Conversation.query.filter_by(id=item_dict['id']).first()
        if existing:
            continue
        
        conv = Conversation(
            id=item_dict['id'],
            user_id=item_dict['user_id'],
            title=item_dict.get('title', '新对话'),
            summary=item_dict.get('summary', ''),
            message_count=item_dict.get('message_count', 0),
            created_at=parse_datetime(item_dict.get('created_at')),
            updated_at=parse_datetime(item_dict.get('updated_at'))
        )
        db.session.add(conv)
        migrated += 1
    
    db.session.commit()
    print(f"  ✅ 迁移对话: {migrated} 条")
    return len(items), migrated


def migrate_chat_messages(sqlite_conn):
    """迁移聊天消息表"""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM chat_messages")
    items = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    
    migrated = 0
    batch_size = 1000
    
    for i, row in enumerate(items):
        item_dict = dict(zip(columns, row))
        
        existing = ChatMessage.query.filter_by(id=item_dict['id']).first()
        if existing:
            continue
        
        msg = ChatMessage(
            id=item_dict['id'],
            conversation_id=item_dict['conversation_id'],
            role=item_dict['role'],
            content=item_dict['content'],
            created_at=parse_datetime(item_dict.get('created_at'))
        )
        db.session.add(msg)
        migrated += 1
        
        # 批量提交
        if migrated % batch_size == 0:
            db.session.commit()
            print(f"  📝 已迁移聊天消息: {migrated} 条...")
    
    db.session.commit()
    print(f"  ✅ 迁移聊天消息: {migrated} 条")
    return len(items), migrated


def migrate_finance_records(sqlite_conn):
    """迁移财务记录表"""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM finance_records")
    items = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    
    migrated = 0
    for row in items:
        item_dict = dict(zip(columns, row))
        
        existing = FinanceRecord.query.filter_by(id=item_dict['id']).first()
        if existing:
            continue
        
        record = FinanceRecord(
            id=item_dict['id'],
            user_id=item_dict['user_id'],
            record_type=item_dict['record_type'],
            amount=item_dict['amount'],
            category=item_dict['category'],
            description=item_dict.get('description', ''),
            record_date=parse_date(item_dict.get('record_date')),
            source=item_dict.get('source', 'ai'),
            created_at=parse_datetime(item_dict.get('created_at'))
        )
        db.session.add(record)
        migrated += 1
    
    db.session.commit()
    print(f"  ✅ 迁移财务记录: {migrated} 条")
    return len(items), migrated


def migrate_system_config(sqlite_conn):
    """迁移系统配置表"""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT * FROM system_config")
    items = cursor.fetchall()
    columns = [description[0] for description in cursor.description]
    
    migrated = 0
    for row in items:
        item_dict = dict(zip(columns, row))
        
        existing = SystemConfig.query.filter_by(key=item_dict['key']).first()
        if existing:
            continue
        
        config = SystemConfig(
            key=item_dict['key'],
            value=item_dict.get('value', ''),
            updated_at=parse_datetime(item_dict.get('updated_at')),
            updated_by=item_dict.get('updated_by')
        )
        db.session.add(config)
        migrated += 1
    
    db.session.commit()
    print(f"  ✅ 迁移系统配置: {migrated} 条")
    return len(items), migrated


def main():
    if len(sys.argv) < 2:
        print("用法: python migrate_sqlite_to_mysql.py <sqlite_db_path>")
        print("\n示例:")
        print("  python migrate_sqlite_to_mysql.py app.db")
        print("  python migrate_sqlite_to_mysql.py /path/to/study_assistant.db")
        sys.exit(1)
    
    sqlite_path = sys.argv[1]
    print(f"\n{'='*50}")
    print(f"SQLite → MySQL 数据迁移")
    print(f"{'='*50}")
    print(f"源数据库: {sqlite_path}")
    print(f"目标数据库: MySQL (腾讯云)")
    print(f"{'='*50}\n")
    
    # 连接 SQLite
    try:
        sqlite_conn = sqlite3.connect(sqlite_path)
        print("✅ SQLite 连接成功")
    except Exception as e:
        print(f"❌ SQLite 连接失败: {e}")
        sys.exit(1)
    
    # 在 Flask 应用上下文中执行迁移
    with app.app_context():
        print("\n开始迁移数据...\n")
        
        total_stats = {}
        
        # 按依赖顺序迁移
        migrations = [
            ("users", migrate_users),
            ("notes", migrate_notes),
            ("content_collections", migrate_content_collections),
            ("learning_activities", migrate_learning_activities),
            ("conversations", migrate_conversations),
            ("chat_messages", migrate_chat_messages),
            ("finance_records", migrate_finance_records),
            ("system_config", migrate_system_config),
        ]
        
        for table_name, migrate_func in migrations:
            try:
                print(f"📋 迁移表: {table_name}")
                total, migrated = migrate_func(sqlite_conn)
                total_stats[table_name] = (total, migrated)
            except Exception as e:
                print(f"  ❌ 迁移失败: {e}")
                db.session.rollback()
        
        print(f"\n{'='*50}")
        print("迁移完成统计:")
        print(f"{'='*50}")
        total_all = 0
        migrated_all = 0
        for table, (total, migrated) in total_stats.items():
            print(f"  {table}: {migrated}/{total} 条")
            total_all += total
            migrated_all += migrated
        print(f"{'='*50}")
        print(f"  总计: {migrated_all}/{total_all} 条")
        print(f"{'='*50}\n")
    
    sqlite_conn.close()
    print("✅ 迁移完成！")


if __name__ == '__main__':
    main()
