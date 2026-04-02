# conversations.py - 对话归档模块
# 负责将用户与 AI 的对话保存到 Markdown 文件
# 按日期组织文件，用于长期记忆和历史查询

"""Conversation archiving for long-term memory."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from xinyiclaw.config import WORKSPACE_DIR

logger = logging.getLogger(__name__)

# 对话存储目录：workspace/conversations/
CONVERSATIONS_DIR = WORKSPACE_DIR / "conversations"


def ensure_conversations_dir() -> None:
    """确保对话目录存在
    
    功能:
        如果 conversations 目录不存在则创建
        使用 mkdir 的 parents 和 exist_ok 参数确保安全性
    """
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)


def _get_today_file() -> Path:
    """获取今天的对话文件路径
    
    返回:
        Path: 今天的对话文件路径（格式：conversations/YYYY-MM-DD.md）
    
    说明:
        每天的对话存储在单独的文件中
        便于管理和查找历史记录
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return CONVERSATIONS_DIR / f"{today}.md"


async def archive_exchange(user_message: str, assistant_response: str, chat_id: int) -> None:
    """归档一次用户与助手的对话
    
    参数:
        user_message: 用户发送的消息
        assistant_response: 助手的回复
        chat_id: 聊天 ID（当前未使用，预留多用户支持）
    
    文件格式:
        # Conversations - YYYY-MM-DD
        
        ## HH:MM:SS UTC
        
        **User**: <message>
        
        **Ape**: <response>
        
        ---
    
    说明:
        - 追加模式：每次对话追加到当天文件末尾
        - 如果文件不存在，先创建文件头
        - 使用 UTF-8 编码支持多语言
    """
    # 确保目录存在
    ensure_conversations_dir()

    # 获取今天的文件路径
    filepath = _get_today_file()
    # 生成 UTC 时间戳
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    # 构建对话条目
    entry = f"""## {timestamp}

**User**: {user_message}

**Ape**: {assistant_response}

---

"""

    # 追加到文件（如果文件不存在则先创建文件头）
    try:
        if filepath.exists():
            # 文件已存在，直接读取内容
            content = filepath.read_text(encoding="utf-8")
        else:
            # 文件不存在，创建带文件头的内容
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            content = f"# Conversations - {date_str}\n\n"

        # 追加对话条目
        content += entry
        # 写回文件
        filepath.write_text(content, encoding="utf-8")
        logger.debug(f"Archived exchange to {filepath}")
    except Exception:
        # 异常处理：记录错误但不中断程序
        logger.exception(f"Failed to archive exchange to {filepath}")
