# bot.py - Telegram Bot 设置和消息处理
# 负责配置 Bot 命令处理器、消息过滤器和权限控制
# 集成 AI Agent 和任务调度器

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from xinyiclaw.agent import run_agent, clear_session_id
from xinyiclaw.conversations import archive_exchange
from xinyiclaw.config import ASSISTANT_NAME, DB_PATH, OWNER_ID, TELEGRAM_BOT_TOKEN
from xinyiclaw.scheduler import setup_scheduler

logger = logging.getLogger(__name__)

# Telegram 单条消息最大字符数限制
_TELEGRAM_MAX_LENGTH = 4096


def _is_owner(update: Update) -> bool:
    """检查用户是否为 Bot 所有者（权限控制）
    
    参数:
        update: Telegram 更新对象，包含用户信息
    
    返回:
        bool: 如果是所有者返回 True，否则 False
    
    安全说明:
        只有 OWNER_ID 对应的用户可以访问 Bot
        防止未授权用户调用 AI 功能（避免 API 费用）
    """
    return update.effective_user is not None and update.effective_user.id == OWNER_ID


async def _start(update: Update, context) -> None:
    """处理 /start 命令 - Bot 启动欢迎消息
    
    参数:
        update: Telegram 更新对象
        context: Bot 上下文（包含 bot 对象等）
    
    功能:
        1. 验证用户权限
        2. 发送欢迎消息和使用说明
        3. 介绍可用命令
    """
    if not _is_owner(update):
        return
    await update.message.reply_text(
        f"Hi! I'm {ASSISTANT_NAME}, your personal AI assistant. Send me a message to get started.\n\n"
        "Commands:\n"
        "/clear - Reset conversation session"
    )


async def _clear(update: Update, context) -> None:
    """处理 /clear 命令 - 重置会话
    
    参数:
        update: Telegram 更新对象
        context: Bot 上下文
    
    功能:
        1. 验证用户权限
        2. 清除 session_id（删除 state.json）
        3. 下次对话将开启新会话（无历史上下文）
    
    使用场景:
        - 会话状态异常时
        - 想要完全重置对话上下文时
    """
    if not _is_owner(update):
        return
    clear_session_id()
    await update.message.reply_text("Session cleared. Starting fresh!")


async def _handle_message(update: Update, context) -> None:
    """处理普通文本消息（非命令）
    
    参数:
        update: Telegram 更新对象
        context: Bot 上下文（包含 bot 对象、chat_id 等）
    
    处理流程:
        1. 权限验证
        2. 发送"正在输入"状态（提升用户体验）
        3. 调用 AI Agent 处理消息
        4. 归档对话到 conversations/（长期记忆）
        5. 分割长消息并回复（避免超出 Telegram 限制）
    """
    if not _is_owner(update) or not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text

    # 发送"正在输入"状态，让用户知道 Bot 在处理
    # 避免用户等待时不知道 Bot 是否在工作
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # 调用 AI Agent 处理用户消息
    # run_agent 会调用 Claude AI 并返回响应
    response = await run_agent(user_text, context.bot, chat_id, str(DB_PATH))

    # 归档对话到 conversations/ 目录
    # 用于长期记忆和历史查询（AI 可以通过搜索历史对话回忆之前的交流）
    await archive_exchange(user_text, response, chat_id)

    # 分割长消息（Telegram 限制单条消息最多 4096 字符）
    # 如果响应超过限制，分割成多条消息发送
    for i in range(0, len(response), _TELEGRAM_MAX_LENGTH):
        chunk = response[i : i + _TELEGRAM_MAX_LENGTH]
        await update.message.reply_text(chunk)


async def _post_init(application: Application) -> None:
    """Bot 初始化后回调函数
    
    参数:
        application: Telegram Application 对象
    
    功能:
        1. 设置并启动任务调度器
        2. 调度器会定期检查并执行到期的定时任务
    
    注意:
        此函数在 Bot 启动后自动调用一次
    """
    scheduler = setup_scheduler(application.bot, str(DB_PATH))
    scheduler.start()
    logger.info("Scheduler started")


def setup_bot() -> Application:
    """创建并配置 Telegram Bot 应用
    
    返回:
        Application: 配置好的 Telegram 应用对象
    
    配置内容:
        1. 设置 Bot Token（身份验证）
        2. 注册 post_init 回调（启动调度器）
        3. 添加命令处理器（/start, /clear）
        4. 添加消息处理器（文本消息）
    
    过滤器说明:
        filters.TEXT & ~filters.COMMAND: 只处理纯文本消息，排除命令
        （命令由 CommandHandler 处理）
    """
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", _start))
    app.add_handler(CommandHandler("clear", _clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
    return app
