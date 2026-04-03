# web_app.py - Web 前端入口
# 提供 Web 界面控制 XinyiClaw
# 使用 Flask 提供 HTTP API

import asyncio
import logging
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

from xinyiclaw.engine import AgentEngine
from xinyiclaw.config import WORKSPACE_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

# 初始化 Agent Engine (CPU 架构启发的 Agent 引擎)
agent_engine = AgentEngine(Path(WORKSPACE_DIR))

# 简单的内存会话存储
sessions = {}


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def chat():
    """处理聊天消息 - 使用 AgentEngine"""
    data = request.json
    session_id = data.get('session_id', 'default')
    message = data.get('message', '')
    
    if not message:
        return jsonify({'error': 'Empty message'}), 400
    
    logger.info(f"Session {session_id}: {message}")
    
    # 异步运行 agent engine
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # 使用 AgentEngine 处理对话
        response, updated_messages = loop.run_until_complete(
            agent_engine.chat(message, session_id=session_id)
        )
        
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


@app.route('/api/status', methods=['GET'])
def status():
    """获取引擎状态和性能指标"""
    return jsonify({
        'cache_size': {
            'l1': len(agent_engine.cache.l1),
            'l2': len(agent_engine.cache.l2),
            'l3': len(agent_engine.cache.l3),
            'tlb': len(agent_engine.cache.tlb),
        },
        'in_flight_tasks': agent_engine.scheduler.dual_queue.get_in_flight_count(),
        'tool_patterns_count': len(agent_engine.predictor.tool_patterns),
        'session_count': len(agent_engine._session_histories),
        'metrics': agent_engine.metrics.get_stats(),
    })


if __name__ == '__main__':
    print("""
╔════════════════════════════════════════════════════════════╗
║   XinyiClaw 2 - CPU-Inspired Agent Engine             ║
║   调度与并行 | 预测与预取 | 存储层级                      ║
║   同步与竞争 | 异常与中断 | 批量处理                       ║
║   http://localhost:5002                                 ║
╚════════════════════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=5002, debug=True, use_reloader=False)
