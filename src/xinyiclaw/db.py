# db.py - 数据库操作模块
# 负责 SQLite 数据库的初始化和定时任务的 CRUD 操作
# 消息历史存储在 conversations/ 文件夹（不在数据库中）

"""Database operations for scheduled tasks.

Note: Message history is stored in conversations/ folder (not in DB).
The DB is only used for structured data that needs querying (scheduled tasks).
"""

import uuid
from datetime import datetime, timezone

import aiosqlite

# 数据库表结构定义
_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    schedule_value TEXT NOT NULL,
    next_run TEXT,
    last_run TEXT,
    last_result TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run ON scheduled_tasks(next_run);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status ON scheduled_tasks(status);

CREATE TABLE IF NOT EXISTS task_run_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    run_at TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id)
);
CREATE INDEX IF NOT EXISTS idx_task_run_logs_task_id ON task_run_logs(task_id);
"""


async def init_db(db_path: str) -> None:
    """初始化数据库（创建表和索引）
    
    参数:
        db_path: SQLite 数据库文件路径
    
    功能:
        1. 创建 scheduled_tasks 表（定时任务）
        2. 创建 task_run_logs 表（执行日志）
        3. 创建索引优化查询性能
    
    注意:
        使用 executescript 一次性执行所有 SQL 语句
        如果表已存在则跳过创建（IF NOT EXISTS）
    """
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_CREATE_TABLES)
        await db.commit()


# ==================== 任务 CRUD 操作 ====================

async def create_task(db_path: str, chat_id: int, prompt: str, schedule_type: str, schedule_value: str, next_run: str) -> str:
    """创建新的定时任务
    
    参数:
        db_path: 数据库路径
        chat_id: 聊天 ID（任务所属用户）
        prompt: 任务提示词（AI 执行的内容）
        schedule_type: 调度类型（cron/interval/once）
        schedule_value: 调度值（cron 表达式/毫秒数/时间戳）
        next_run: 下次执行时间（ISO 格式）
    
    返回:
        str: 任务 ID（8 位随机十六进制字符串）
    
    说明:
        任务 ID 使用 uuid 的前 8 位，足够唯一且简洁
    """
    task_id = uuid.uuid4().hex[:8]
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO scheduled_tasks (id, chat_id, prompt, schedule_type, schedule_value, next_run, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, chat_id, prompt, schedule_type, schedule_value, next_run, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()
    return task_id


async def get_all_tasks(db_path: str) -> list[dict]:
    """获取所有任务
    
    参数:
        db_path: 数据库路径
    
    返回:
        list[dict]: 所有任务的字典列表
    """
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row  # 返回字典格式的行
        cursor = await db.execute("SELECT * FROM scheduled_tasks")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_due_tasks(db_path: str) -> list[dict]:
    """获取所有到期的任务
    
    参数:
        db_path: 数据库路径
    
    返回:
        list[dict]: 到期任务的字典列表
    
    查询条件:
        - status = 'active'（仅活跃任务）
        - next_run <= 当前时间（已到期）
    
    说明:
        此函数被调度器定期调用（默认每 60 秒）
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM scheduled_tasks WHERE status = 'active' AND next_run <= ?",
            (now,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_task_status(db_path: str, task_id: str, status: str) -> bool:
    """更新任务状态
    
    参数:
        db_path: 数据库路径
        task_id: 任务 ID
        status: 新状态（'active', 'paused', 'completed'）
    
    返回:
        bool: 是否成功更新（任务是否存在）
    
    使用场景:
        - 暂停任务：status='paused'
        - 恢复任务：status='active'
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "UPDATE scheduled_tasks SET status = ? WHERE id = ?",
            (status, task_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_task(db_path: str, task_id: str) -> bool:
    """删除任务
    
    参数:
        db_path: 数据库路径
        task_id: 任务 ID
    
    返回:
        bool: 是否成功删除（任务是否存在）
    
    使用场景:
        - 取消任务
        - 清理已完成的一次性任务
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        await db.commit()
        return cursor.rowcount > 0


async def update_task_after_run(db_path: str, task_id: str, last_result: str, next_run: str | None, status: str = "active") -> None:
    """任务执行后更新任务记录
    
    参数:
        db_path: 数据库路径
        task_id: 任务 ID
        last_result: 执行结果
        next_run: 下次执行时间（一次性任务为 None）
        status: 任务状态（默认'active'）
    
    更新字段:
        - last_run: 最后执行时间
        - last_result: 最后执行结果
        - next_run: 下次执行时间
        - status: 任务状态
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE scheduled_tasks SET last_run = ?, last_result = ?, next_run = ?, status = ? WHERE id = ?",
            (now, last_result, next_run, status, task_id),
        )
        await db.commit()


async def log_task_run(db_path: str, task_id: str, duration_ms: int, status: str, result: str | None = None, error: str | None = None) -> None:
    """记录任务执行日志
    
    参数:
        db_path: 数据库路径
        task_id: 任务 ID
        duration_ms: 执行耗时（毫秒）
        status: 执行状态（'success' 或 'error'）
        result: 执行结果（可选）
        error: 错误信息（可选）
    
    说明:
        日志存储在 task_run_logs 表
        用于追踪任务执行历史和分析性能
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO task_run_logs (task_id, run_at, duration_ms, status, result, error) VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, datetime.now(timezone.utc).isoformat(), duration_ms, status, result, error),
        )
        await db.commit()
