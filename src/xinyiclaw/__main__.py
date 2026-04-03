# __main__.py - 程序入口点
# 负责初始化运行时环境并启动 Web 服务

import asyncio
import logging

from xinyiclaw.config import DATA_DIR, DB_PATH, STORE_DIR, WORKSPACE_DIR
from xinyiclaw.db import init_db
from xinyiclaw.memory import ensure_workspace

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _prepare_runtime() -> None:
    """准备运行时环境"""
    for d in (WORKSPACE_DIR, STORE_DIR, DATA_DIR):
        d.mkdir(parents=True, exist_ok=True)
    await init_db(str(DB_PATH))
    logger.info("Database initialized at %s", DB_PATH)
    ensure_workspace()
    logger.info("Workspace ready at %s", WORKSPACE_DIR)


def main() -> None:
    """启动 Web 服务"""
    asyncio.run(_prepare_runtime())
    from xinyiclaw.web_app import app
    logger.info("Starting web server on port 5002...")
    app.run(host='0.0.0.0', port=5002, debug=False)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
