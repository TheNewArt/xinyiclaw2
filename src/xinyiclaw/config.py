# config.py - 配置管理模块 (MiniMax 版本)

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ==================== MiniMax API 配置 ====================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "sk-W5akWonczJnMq95RTjVANPSuuYCPBtt7S0DOKzFBwTle765L")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://llm.hytriu.cn/v1")

# ==================== 可选配置 ====================
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "XinyiClaw")
SCHEDULER_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL", "60"))

# ==================== 路径配置 ====================
BASE_DIR = Path(__file__).resolve().parent.parent.parent
WORKSPACE_DIR = BASE_DIR / "workspace"
STORE_DIR = BASE_DIR / "store"
DATA_DIR = BASE_DIR / "data"
DB_PATH = STORE_DIR / "xinyiclaw.db"
STATE_FILE = DATA_DIR / "state.json"


def get_chat_workspace(chat_id: int) -> Path:
    return WORKSPACE_DIR
