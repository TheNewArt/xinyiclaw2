# XinyiClaw Web

基于 MiniMax API 的 AI 助手 Web 版本，移除 Telegram 依赖，使用浏览器控制。

## 快速开始

1. **安装依赖**
   ```bash
   uv sync
   ```

2. **启动**
   ```bash
   # 方式一：双击运行
   启动Web.bat

   # 方式二：命令行
   uv run python -m src.web_app
   ```

3. **打开浏览器**
   访问 http://localhost:5000

## 功能

- 🌐 Web 界面聊天
- 📁 文件读写（workspace/ 目录）
- 💻 命令执行
- 🗑️ 清除会话

## 目录结构

```
xinyiclaw-py-web/
├── src/
│   ├── xinyiclaw/
│   │   ├── agent.py      # AI Agent（MiniMax 版）
│   │   ├── config.py     # 配置
│   │   └── ...
│   ├── web_app.py        # Web 服务器
│   └── templates/
│       └── index.html    # 前端页面
├── workspace/            # AI 工作目录
├── store/               # 数据库
├── data/                # 状态文件
└── 启动Web.bat          # Windows 启动脚本
```

## 配置

编辑 `.env` 文件：

```
ANTHROPIC_API_KEY=your_api_key
ANTHROPIC_BASE_URL=https://llm.hytriu.cn/v1
ASSISTANT_NAME=XinyiClaw
```

## 限制

- MiniMax API 不支持原生 tool_use
- 工具调用通过正则解析模拟，能力有限
- 生产环境建议使用官方 Anthropic API
