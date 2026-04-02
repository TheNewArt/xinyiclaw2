# __main__.py - 程序入口点
# 负责初始化运行时环境并启动 Telegram Bot
# 使用 python -m xinyiclaw 或 python __main__.py 运行

import asyncio
import logging

from xinyiclaw.bot import setup_bot
from xinyiclaw.config import ASSISTANT_NAME, DATA_DIR, DB_PATH, STORE_DIR, WORKSPACE_DIR
from xinyiclaw.db import init_db
from xinyiclaw.memory import ensure_workspace

# 配置日志格式：时间 - 模块名 - 级别 - 消息
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _prepare_runtime() -> None:
    """准备运行时环境（异步初始化）
    
    执行顺序:
    1. 创建必要的目录（工作区、存储、数据）
    2. 初始化 SQLite 数据库
    3. 确保工作区配置文件 CLAUDE.md 存在
    """
    # 创建所有必需的目录
    # parents=True: 如果父目录不存在也一并创建
    # exist_ok=True: 如果目录已存在不报错
    for d in (WORKSPACE_DIR, STORE_DIR, DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # 初始化数据库（创建表和索引）
    await init_db(str(DB_PATH))
    logger.info("Database initialized at %s", DB_PATH)

    # 确保工作区目录和 CLAUDE.md 文件存在
    # CLAUDE.md 包含 AI 助手的系统提示和使用指南
    ensure_workspace()
    logger.info("Workspace ready at %s", WORKSPACE_DIR)


def _run_bot() -> None:
    """启动 Telegram Bot
    
    使用轮询模式（polling）接收消息
    适合开发环境，不需要配置 webhook
    """
    app = setup_bot()
    logger.info("%s is starting...", ASSISTANT_NAME)
    app.run_polling()


def main() -> None:
    """主函数：协调初始化和 Bot 启动
    
    执行流程:
    1. 使用 asyncio.run() 运行异步初始化函数
    2. 同步运行 Bot 轮询（阻塞直到停止）
    """
    # 运行异步初始化（目录创建、数据库初始化等）
    asyncio.run(_prepare_runtime())
    # 启动 Bot（同步阻塞调用）
    _run_bot()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # 优雅处理 Ctrl+C 退出
        logger.info("Shutting down...")
