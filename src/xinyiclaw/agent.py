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


async def chat_minimax(messages: list[dict], system: str = "", max_retries: int = 3) -> str:
    """调用 MiniMax API（带重试机制）"""
    import httpx
    
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
    
    last_error = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    MINIMAX_API_URL,
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                
                # 优先检查是否有有效内容（即使有错误码也可能有内容）
                if data.get("choices") and data["choices"][0].get("message"):
                    return data["choices"][0]["message"]["content"]
                
                if data.get("content"):
                    return data["content"]
                
                # 没有有效内容，检查错误
                base_resp = data.get("base_resp", {})
                status_code = base_resp.get("status_code", 0) if base_resp else 0
                status_msg = base_resp.get("status_msg", "") if base_resp else ""
                
                # 记录异常响应格式
                if not base_resp:
                    logger.warning(f"Unexpected response structure (no base_resp): {str(data)[:300]}")
                elif status_code == 0:
                    logger.warning(f"Status code 0, full response: {str(data)[:300]}")
                
                # status_code 1000 是成功，但 status_msg 可能包含警告
                if status_code == 1000:
                    # 成功但有警告信息，记录一下
                    if status_msg and "error" in status_msg.lower():
                        logger.warning(f"MiniMax API warning: {status_msg}")
                    # 没有内容，返回警告信息
                    return f"API Warning: {status_msg}" if status_msg else "Empty response from API"
                
                # 非 1000 都是错误
                logger.warning(f"MiniMax API error: {status_code} - {status_msg}")
                
                # 520 是服务端临时错误，可以重试
                if status_code == 520 or "520" in str(status_msg):
                    last_error = f"API Error {status_code}: {status_msg}"
                    await asyncio.sleep(1 * (attempt + 1))
                    continue
                
                # 其他错误不重试
                return f"API Error {status_code}: {status_msg}"
                
        except httpx.TimeoutException:
            last_error = f"Request timeout (attempt {attempt + 1}/{max_retries})"
            logger.warning(last_error)
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
                continue
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP error: {e.response.status_code}"
            logger.warning(last_error)
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
                continue
        except Exception as e:
            last_error = f"Unexpected error: {str(e)}"
            logger.exception(last_error)
            break
    
    return f"请求失败: {last_error}"


def parse_tool_call_args(tool_call_str: str) -> tuple[str, dict]:
    """解析工具调用参数字符串
    
    处理格式: ToolName|key1=value1|key2=value2|...
    支持 value 中包含 | 和 = 符号（如 JSON 或多行内容）
    """
    parts = tool_call_str.split('|')
    if not parts:
        return "", {}
    
    tool_name = parts[0].strip()
    arguments = {}
    
    i = 1
    while i < len(parts):
        part = parts[i]
        if '=' not in part:
            i += 1
            continue
        
        key, value = part.split('=', 1)
        key = key.strip()
        value = value.strip()
        
        # 处理多行字符串值（以 """ 开头）
        # 如果 value 以 """ 开头但没有以 """ 结尾，继续合并后续部分
        if value.startswith('"""'):
            # 检查是否在同一 part 内关闭
            if value.count('"""') >= 2:
                # 简单情况: """..."""
                value = value[3:-3]
            else:
                # 跨多个 part，继续合并
                j = i + 1
                while j < len(parts) and value.count('"""') < 2:
                    value += '|' + parts[j]
                    j += 1
                # 去掉前后 """
                if value.startswith('"""') and value.endswith('"""'):
                    value = value[3:-3]
                elif value.startswith('"""'):
                    value = value[3:]
                i = j - 1
        elif value.startswith('"') and value.endswith('"') and value.count('"') == 2:
            # 处理转义引号如 "hello\"world"
            value = value[1:-1]
        
        arguments[key] = value
        i += 1
    
    return tool_name, arguments


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
            
            # 1. 去掉外层 triple-quote 包裹（如果 content 是被 """ 包裹的字符串）
            content = content.strip()
            if content.startswith('"""') and content.endswith('"""') and len(content) > 6:
                content = content[3:-3]
            elif content.startswith('"""'):
                content = content[3:]
            
            # 2. 处理转义字符：\" -> ", \\n -> 真正的换行, \\r -> 真正的回车
            content = content.replace('\\"', '"').replace('\\n', '\n').replace('\\r', '\r')
            
            # 3. 去除 markdown 代码块标记（如果模型把整块 markdown 当内容写进来了）
            if content.strip().startswith('```'):
                lines = content.split('\n')
                if len(lines) >= 2 and lines[0].strip().startswith('```'):
                    content = '\n'.join(lines[1:])
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
            tool_name, arguments = parse_tool_call_args(tool_call_str)
            if not tool_name:
                continue
            
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
