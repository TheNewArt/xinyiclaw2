# web_app.py - Web 前端入口
# 提供 Web 界面控制 XinyiClaw
# 使用 Flask 提供 HTTP API

import asyncio
import logging
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

from xinyiclaw.agent import run_agent
from xinyiclaw.config import WORKSPACE_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

# 简单的内存会话存储（生产环境应该用数据库）
sessions = {}


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def chat():
    """处理聊天消息"""
    data = request.json
    session_id = data.get('session_id', 'default')
    message = data.get('message', '')
    
    if not message:
        return jsonify({'error': 'Empty message'}), 400
    
    logger.info(f"Session {session_id}: {message}")
    
    # 异步运行 agent
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # 这里需要传入 bot 对象，但我们没有 Telegram bot
    # 创建一个 mock bot
    class MockBot:
        async def send_message(self, chat_id, text):
            logger.info(f"Mock send to {chat_id}: {text}")
            return True
    
    try:
        # 获取会话历史（没有则为空列表）
        history = sessions.get(session_id, [])
        
        response, updated_messages = loop.run_until_complete(
            run_agent(message, MockBot(), session_id, str(WORKSPACE_DIR), messages=history)
        )
        
        # 更新会话历史
        sessions[session_id] = updated_messages
        
        return jsonify({
            'response': response,
            'session_id': session_id
        })
    except Exception as e:
        logger.exception("Agent error")
        return jsonify({'error': str(e)}), 500
    finally:
        loop.close()


@app.route('/api/clear', methods=['POST'])
def clear():
    """清除会话"""
    data = request.json
    session_id = data.get('session_id', 'default')
    
    # 清除会话状态
    if session_id in sessions:
        del sessions[session_id]
    
    return jsonify({'status': 'cleared'})


if __name__ == '__main__':
    print("""
╔════════════════════════════════════════════════════════════╗
║   XinyiClaw Web - AI Assistant with MiniMax API          ║
║   http://localhost:5000                                 ║
╚════════════════════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=5000, debug=True)
