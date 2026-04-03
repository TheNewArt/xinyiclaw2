# XinyiClaw 2 - CPU 架构启发的 Agent 引擎

## 一句话介绍

将 CPU 几十年的架构设计融入 LLM Agent，实现更高效、更可控的 Agent 系统。

---

## 为什么做这个？

设计 Agent 系统时，CPU 架构提供了极其成熟的参考。缓存、预测、调度、并发控制——这些都是 CPU 已经优化了几十年的问题。

XinyiClaw 2 将这些思想融入 Agent 引擎。

---

## 核心架构

```
用户输入
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  BranchPredictor (分支预测)                          │
│  预测下一步工具，提前准备资源                         │
└────────────────────┬────────────────────────────────┘
                     │
    ┌────────────────┴────────────────┐
    ▼                                 ▼
┌───────────────┐            ┌───────────────┐
│   Prefetcher  │            │  MemoryCache  │
│   预取文件    │            │  L1/L2/L3缓存 │
│   到 L2 缓存  │            │  + TLB 快速查找│
└───────────────┘            └───────────────┘
                                    │
                                    ▼
                         ┌───────────────────┐
                         │  DualQueue        │
                         │  (双队列并行调度)  │
                         └─────────┬─────────┘
                                   │
                         ┌─────────┴─────────┐
                         ▼                   ▼
                   ┌───────────┐       ┌───────────┐
                   │  工具1    │       │  工具2    │
                   │  执行中   │       │  执行中   │
                   └───────────┘       └───────────┘
```

---

## 六大模块

| 模块 | CPU 概念 | 作用 |
|------|---------|------|
| **MemoryCache** | L1/L2/L3 缓存 + TLB | 多级记忆分层，热点数据快速访问 |
| **BranchPredictor** | 分支预测 | 预测下一步工具，减少等待 |
| **Prefetcher** | 预取 | 提前加载可能需要的文件 |
| **AsyncLock/Semaphore** | Mutex/信号量 | 并发控制，防止资源竞争 |
| **WatchdogTimer** | 看门狗 | 超时保护，防止死循环 |
| **DualQueue** | 双发射队列 | 任务并行调度，流水线执行 |

---

## 性能对比

| 指标 | 旧版 | 新版 | 提升 |
|------|------|------|------|
| 平均延迟 | 15,905ms | 10,783ms | **+32%** |
| 缓存命中率 | 0% | **33.3%** | 重复请求直接返回 |
| 错误恢复 | 失败暴露 | **100%** | API 错误自动重试 |

---

## 快速开始

```bash
# 克隆项目
git clone https://github.com/TheNewArt/xinyiclaw2.git
cd xinyiclaw2

# 安装依赖
uv sync

# 启动
cd src
python web_app.py

# 访问
http://localhost:5002
```

---

## API

### 聊天
```bash
curl -X POST http://localhost:5002/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "session_id": "test"}'
```

### 状态监控
```bash
curl http://localhost:5002/api/status
```

返回 Metrics：缓存命中率、预测准确率、延迟等。

---

## 项目结构

```
xinyiclaw2/
├── src/
│   ├── xinyiclaw/
│   │   ├── engine.py    # 核心引擎（CPU 架构模块）
│   │   ├── agent.py     # Agent 实现
│   │   └── config.py   # 配置
│   └── web_app.py      # Web 接口
├── benchmark.py         # 性能测试
├── demo_realtime.py     # 实时演示
└── test_metrics.py      # Metrics 验证
```

---

## 设计亮点

### 1. Blake2b 缓存 Key
```python
# 用完整 prompt hash，不用截断
prompt_hash = blake2b(prompt.encode()).hexdigest()
# "两数之和" vs "三数之和" 不会冲突
```

### 2. 延迟创建 Semaphore
```python
# 在 async 上下文直接创建，避免 event loop 绑定问题
async with asyncio.Semaphore(3):
    result = await executor(task)
```

### 3. API 错误自动重试
```python
# 520/0 错误自动重试，最多 3 次
if status_code in (0, 520):
    await asyncio.sleep(1 * (attempt + 1))
    continue
```

---

## Bug Log

| 日期 | 问题 | 修复 |
|-----|------|------|
| 2026-04-03 | Semaphore event loop 绑定错误 | async 上下文直接创建 |
| 2026-04-03 | 缓存 key 截断导致相似问题误命中 | Blake2b 完整 hash |
| 2026-04-03 | API 520 错误无重试 | 自动重试 3 次 |
| 2026-04-03 | Metrics 全是 0% | 正确记录缓存/预测/预取 |

---

## 未来方向

- [ ] 缓存持久化（Redis）
- [ ] 多 Agent 流水线
- [ ] 学习式分支预测

---

*受 CPU 架构启发，为 LLM Agent 提供更高效、更可控的执行框架。*

**仓库：** https://github.com/TheNewArt/xinyiclaw2
