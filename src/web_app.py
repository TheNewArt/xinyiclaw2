# web_app.py - Web 前端入口 (简化版)
# 支持会话管理、追踪面板

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

from xinyiclaw.agent_core import Agent, AgentState, ToolRegistry
from xinyiclaw.config import WORKSPACE_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

# 简单的内存会话存储
sessions = {}

# 线程池
_executor = ThreadPoolExecutor(max_workers=4)


def create_agent():
    """创建简单的 Agent"""
    async def llm_call(prompt):
        from xinyiclaw.agent import chat_minimax
        result = await chat_minimax([{"role": "user", "content": prompt}])
        return result

    agent = Agent(llm_func=llm_call)
    return agent


async def run_simple(message, session_id):
    """简化版 agent 运行 - 直接 LLM 调用"""
    from xinyiclaw.agent import chat_minimax

    trace = []
    trace.append({"type": "start", "content": "开始处理"})

    # 直接调用 LLM
    trace.append({"type": "thinking", "content": "思考中..."})
    response = await chat_minimax([{"role": "user", "content": message}])
    trace.append({"type": "response", "content": response})

    trace.append({"type": "done", "content": "完成"})
    return trace, response


def _run_sync(message, session_id):
    """在线程中运行异步代码"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(run_simple(message, session_id))
    finally:
        loop.close()


@app.route('/')
def index():
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

    # 在线程池中运行
    future = _executor.submit(_run_sync, message, session_id)
    try:
        trace, response = future.result(timeout=60)
        return jsonify({
            'trace': trace,
            'response': response,
            'session_id': session_id
        })
    except FuturesTimeoutError:
        return jsonify({'error': '请求超时，请重试'}), 504
    except Exception as e:
        logger.exception("Agent error")
        return jsonify({'error': str(e)}), 500


@app.route('/api/cancel/<session_id>', methods=['POST'])
def cancel(session_id):
    """取消会话"""
    if session_id in sessions:
        sessions[session_id]["cancelled"] = True
        return jsonify({'status': 'cancelled'})
    return jsonify({'error': 'Session not found'}), 404


@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """获取会话列表"""
    return jsonify({'sessions': list(sessions.keys())})


@app.route('/api/sessions', methods=['POST'])
def create_session():
    """创建新会话"""
    import uuid
    session_id = str(uuid.uuid4())[:8]
    sessions[session_id] = {"agent": None, "cancelled": False}
    return jsonify({'session_id': session_id})


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    """删除会话"""
    if session_id in sessions:
        del sessions[session_id]
        return jsonify({'status': 'deleted'})
    return jsonify({'error': 'Session not found'}), 404


@app.route('/api/clear', methods=['POST'])
def clear():
    """清除会话"""
    data = request.json
    session_id = data.get('session_id', 'default')
    if session_id in sessions:
        del sessions[session_id]
    return jsonify({'status': 'cleared'})


@app.route('/api/status', methods=['GET'])
def status():
    """获取状态"""
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    print("""
╔════════════════════════════════════════════════════════════╗
║   XinyiClaw 2 - 简化版 Agent                     ║
║   http://localhost:5002                              ║
╚════════════════════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=5002, debug=False, threaded=True)
