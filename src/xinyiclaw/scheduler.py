# scheduler.py - 定时任务调度器
# 基于 APScheduler 实现，定期检查并执行到期的任务
# 支持 cron、interval、once 三种调度方式

import logging
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from croniter import croniter

from xinyiclaw import db
from xinyiclaw.agent import run_task_agent
from xinyiclaw.config import SCHEDULER_INTERVAL

logger = logging.getLogger(__name__)

# 全局调度器实例
_scheduler: AsyncIOScheduler | None = None


def setup_scheduler(bot, db_path: str) -> AsyncIOScheduler:
    """设置并配置任务调度器
    
    参数:
        bot: Bot 对象，用于发送通知
        db_path: 数据库路径
    
    返回:
        AsyncIOScheduler: 配置好的调度器实例
    
    配置说明:
        - 每隔 SCHEDULER_INTERVAL 秒检查一次到期任务
        - 默认间隔为 60 秒（可通过环境变量配置）
        - 使用 _check_tasks 作为检查函数
    """
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _check_tasks,
        "interval",  # 间隔触发
        seconds=SCHEDULER_INTERVAL,
        args=[bot, db_path],
        id="check_tasks",
        replace_existing=True,  # 如果已存在同名任务则替换
    )
    return _scheduler


async def _check_tasks(bot, db_path: str) -> None:
    """定期检查并执行到期的任务
    
    参数:
        bot: Bot 对象
        db_path: 数据库路径
    
    执行流程:
        1. 查询所有到期的任务（next_run <= 当前时间）
        2. 遍历每个任务并执行
        3. 捕获异常避免单个任务失败影响其他任务
    
    注意:
        此函数由调度器定期调用（默认每 60 秒）
    """
    try:
        tasks = await db.get_due_tasks(db_path)
    except Exception:
        logger.exception("Failed to query due tasks")
        return

    for task in tasks:
        try:
            await _execute_task(task, bot, db_path)
        except Exception:
            logger.exception("Failed to execute task %s", task["id"])


async def _execute_task(task: dict, bot, db_path: str) -> None:
    """执行单个定时任务
    
    参数:
        task: 任务字典（包含 id, chat_id, prompt, schedule_type 等）
        bot: Bot 对象
        db_path: 数据库路径
    
    执行流程:
        1. 提取任务信息
        2. 调用 run_task_agent 执行任务
        3. 如果 AI 忘记发送消息，使用回退方案
        4. 记录执行日志（成功/失败）
        5. 计算下次执行时间并更新任务
    
    回退方案:
        如果 AI 模型忘记调用 send_message 工具
        直接发送简单的提醒消息，避免任务静默失败
    """
    task_id = task["id"]
    task_chat_id = task["chat_id"]  # 使用任务中的 chat_id，而不是全局 OWNER_ID
    prompt = task["prompt"]
    logger.info("Executing task %s for chat %s: %s", task_id, task_chat_id, prompt[:80])

    # 包装提示词，强制 AI 使用 send_message 工具通知用户
    wrapped_prompt = f"You are executing a scheduled task. You MUST use the send_message tool to notify the user. Task: {prompt}"
    notify_state = {"sent": False}  # 跟踪消息是否已发送

    start = time.monotonic()
    try:
        # 运行任务 Agent
        result = await run_task_agent(wrapped_prompt, bot, task_chat_id, db_path, notify_state)

        # 回退方案：如果 AI 忘记调用 send_message，直接发送提醒
        if not notify_state["sent"]:
            await bot.send_message(chat_id=task_chat_id, text=f"⏰ 定时提醒：{prompt}")

        duration_ms = int((time.monotonic() - start) * 1000)
        await db.log_task_run(db_path, task_id, duration_ms, "success", result=result)
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        await db.log_task_run(db_path, task_id, duration_ms, "error", error=str(e))
        result = f"Error: {e}"

    # 计算下次执行时间
    stype = task["schedule_type"]
    svalue = task["schedule_value"]
    now = datetime.now(timezone.utc)

    if stype == "cron":
        # cron 表达式：计算下一个匹配的时间点
        next_run = croniter(svalue, now).get_next(datetime).isoformat()
        await db.update_task_after_run(db_path, task_id, result, next_run, "active")
    elif stype == "interval":
        # 间隔：当前时间 + 毫秒数
        next_run = (now + timedelta(milliseconds=int(svalue))).isoformat()
        await db.update_task_after_run(db_path, task_id, result, next_run, "active")
    elif stype == "once":
        # 一次性任务：标记为完成，不计算下次执行时间
        await db.update_task_after_run(db_path, task_id, result, None, "completed")
    else:
        logger.warning("Unknown schedule_type %s for task %s", stype, task_id)

