# agent.py - AI Agent 模块 (MiniMax 版本)
# 使用 MiniMax API，支持工具调用

import asyncio
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from xinyiclaw.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_BASE_URL,
    WORKSPACE_DIR,
)

logger = logging.getLogger(__name__)

# MiniMax API 配置
MINIMAX_API_URL = "https://llm.hytriu.cn/v1/chat/completions"
MINIMAX_MODEL = "MiniMax-M2.1"


async def chat_minimax(messages: list[dict], system: str = "") -> str:
    """调用 MiniMax API"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ANTHROPIC_API_KEY}"
    }
    
    all_messages = []
    if system:
        all_messages.append({"role": "system", "content": system})
    all_messages.extend(messages)
    
    payload = {
        "model": MINIMAX_MODEL,
        "messages": all_messages,
        "temperature": 0.7,
        "max_tokens": 4096
    }
    
    import httpx
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            MINIMAX_API_URL,
            headers=headers,
            json=payload
        )
        response.raise_for_status()
        data = response.json()
        
        if data.get("choices") and data["choices"][0].get("message"):
            return data["choices"][0]["message"]["content"]
        
        if data.get("content"):
            return data["content"]
        
        return str(data)


def execute_tool(tool_name: str, arguments: dict) -> str:
    """执行工具"""
    try:
        if tool_name == "Bash":
            cmd = arguments.get("command", "")
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60,
                cwd=str(WORKSPACE_DIR)
            )
            output = result.stdout if result.stdout else result.stderr
            return output[:5000] if output else "(no output)"
        
        elif tool_name == "Read":
            filepath = Path(arguments.get("path", ""))
            if not filepath.is_absolute():
                filepath = WORKSPACE_DIR / filepath
            content = filepath.read_text(encoding="utf-8")
            return content[:5000] if len(content) > 5000 else content
        
        elif tool_name == "Write":
            filepath = Path(arguments.get("path", ""))
            if not filepath.is_absolute():
                filepath = WORKSPACE_DIR / filepath
            filepath.parent.mkdir(parents=True, exist_ok=True)
            content = arguments.get("content", "")
            # 处理字面化的 \n 和 \r（LLM 输出时会把真正的换行转成 \\n）
            content = content.replace('\\n', '\n').replace('\\r', '\r')
            # 去除 markdown 代码块标记（如果模型把整块 markdown 当内容写进来了）
            content = content.strip()
            if content.startswith('```'):
                # 去掉开头的 ```python 或 ```
                lines = content.split('\n')
                if len(lines) >= 2 and lines[0].strip().startswith('```'):
                    content = '\n'.join(lines[1:])
                # 去掉结尾的 ```
                lines = content.split('\n')
                if lines and lines[-1].strip() == '```':
                    content = '\n'.join(lines[:-1])
                content = content.strip()
            filepath.write_text(content, encoding="utf-8")
            return f"Written to {filepath}"
        
        elif tool_name == "Edit":
            filepath = Path(arguments.get("path", ""))
            if not filepath.is_absolute():
                filepath = WORKSPACE_DIR / filepath
            old_text = arguments.get("old_text", "")
            new_text = arguments.get("new_text", "")
            content = filepath.read_text(encoding="utf-8")
            if old_text not in content:
                return f"Error: old_text not found in file"
            content = content.replace(old_text, new_text)
            filepath.write_text(content, encoding="utf-8")
            return f"Edited {filepath}"
        
        elif tool_name == "Glob":
            import fnmatch
            pattern = arguments.get("pattern", "*")
            matches = []
            for root, dirs, files in os.walk(str(WORKSPACE_DIR)):
                for name in files + dirs:
                    if fnmatch.fnmatch(name, pattern):
                        rel_path = os.path.relpath(os.path.join(root, name), str(WORKSPACE_DIR))
                        matches.append(rel_path)
            return "\n".join(matches[:100]) if matches else "(no matches)"
        
        elif tool_name == "Grep":
            pattern = arguments.get("pattern", "")
            search_path = Path(arguments.get("path", str(WORKSPACE_DIR)))
            if not search_path.is_absolute():
                search_path = WORKSPACE_DIR / search_path
            
            matches = []
            for root, dirs, files in os.walk(str(search_path)):
                for name in files:
                    filepath = Path(root) / name
                    try:
                        content = filepath.read_text(encoding="utf-8", errors='ignore')
                        for i, line in enumerate(content.split('\n'), 1):
                            if pattern.lower() in line.lower():
                                matches.append(f"{filepath}:{i}: {line[:200]}")
                    except:
                        pass
            return "\n".join(matches[:50]) if matches else "(no matches)"
        
        else:
            return f"Unknown tool: {tool_name}"
    
    except Exception as e:
        return f"Error executing {tool_name}: {str(e)}"


async def run_agent(prompt: str, bot: Any, session_id: str, workspace: str, messages: list = None) -> str:
    """运行 Agent（MiniMax 版本）
    
    Args:
        prompt: 当前用户输入
        bot: mock bot 对象
        session_id: 会话 ID
        workspace: 工作区路径
        messages: 对话历史（可选），格式为 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    """
    
    system_prompt = f"""You are a helpful AI assistant with access to tools in the workspace: {WORKSPACE_DIR}

Available tools (MUST be called explicitly):
- Bash(command="ls -la")
- Read(path="filename.txt")
- Write(path="filename.txt", content="text content")
- Edit(path="filename.txt", old_text="old text", new_text="new text")
- Glob(pattern="*.py")
- Grep(pattern="search term", path=".")

IMPORTANT: When you need to use a tool, you MUST output the tool call in this EXACT format:
[TOOL_CALL]ToolName|arg1=value1|arg2=value2[/TOOL_CALL]

For example:
- To list files: [TOOL_CALL]Bash|command=ls[/TOOL_CALL]
- To read a file: [TOOL_CALL]Read|path=hello.txt[/TOOL_CALL]
- To write a file: [TOOL_CALL]Write|path=hello.txt|content=Hello![/TOOL_CALL]

If no tools are needed, just answer the question directly.
"""
    
    # 如果没有传入历史，从当前 prompt 开始
    # 如果传入了历史，在末尾追加当前 prompt
    if messages is None:
        messages = [{"role": "user", "content": prompt}]
    else:
        messages = list(messages)  # 复制一份，避免修改原列表
        messages.append({"role": "user", "content": prompt})
    
    # 对话轮次限制
    max_turns = 5
    for turn in range(max_turns):
        response = await chat_minimax(messages, system_prompt)
        messages.append({"role": "assistant", "content": response})
        
        # 检查是否有工具调用
        tool_pattern = r'\[TOOL_CALL\](.+?)\[/TOOL_CALL\]'
        matches = list(re.finditer(tool_pattern, response, re.DOTALL))
        
        if not matches:
            # 没有工具调用，返回响应
            return response, messages
        
        # 执行工具调用
        tool_results = []
        for match in matches:
            tool_call_str = match.group(1)
            parts = tool_call_str.split('|')
            if not parts:
                continue
            
            tool_name = parts[0].strip()
            arguments = {}
            
            for part in parts[1:]:
                if '=' in part:
                    key, value = part.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    arguments[key] = value
            
            # 执行工具
            result = execute_tool(tool_name, arguments)
            tool_results.append(f"[{tool_name}]\n{result}")
        
        # 将工具结果添加为用户消息
        tool_feedback = "\n\n".join(tool_results)
        messages.append({
            "role": "user", 
            "content": f"Tool results:\n{tool_feedback}\n\nContinue with the task if needed."
        })
    
    # 达到最大轮次，返回最后响应和完整消息历史
    return messages[-1]["content"] if messages else "No response.", messages


def clear_session_id() -> None:
    """清除会话 ID（无操作）"""
    pass
