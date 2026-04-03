# test_unique.py - 用完全唯一的 prompt 测试
import asyncio
import httpx
import time
import random
import string


def random_prompt():
    """生成随机 prompt"""
    topics = ["排序算法", "网络编程", "数据结构", "并发处理", "文件操作", "加密解密", "正则表达式", "单元测试"]
    actions = ["实现", "解释", "比较", "优化", "调试", "分析", "设计", "重构"]
    return f"{random.choice(actions)}一下{random.choice(topics)}相关的{random.choice(['概念', '代码', '原理', '最佳实践', '常见问题'])}"


async def main():
    prompts = [random_prompt() for _ in range(5)]
    
    print("随机生成的唯一 prompt:")
    for i, p in enumerate(prompts, 1):
        print(f"  {i}. {p}")
    print()
    
    async with httpx.AsyncClient() as client:
        # 清空
        await client.post("http://localhost:5002/api/clear", json={"session_id": "unique"}, timeout=10.0)
        await asyncio.sleep(0.5)
        
        print("测试新版 (5002) 5个唯一 prompt:")
        for i, p in enumerate(prompts, 1):
            start = time.perf_counter()
            r = await client.post(
                "http://localhost:5002/api/chat",
                json={"message": p, "session_id": f"unique_{i}"},
                timeout=120.0
            )
            elapsed = (time.perf_counter() - start) * 1000
            print(f"  [{i}] {elapsed:.0f}ms - {p[:20]}...")
        
        # 看 metrics
        m = await client.get("http://localhost:5002/api/status", timeout=10.0)
        metrics = m.json().get("metrics", {})
        print(f"\nMetrics:")
        print(f"  cache_hits: {metrics.get('cache_hits', 0)}")
        print(f"  cache_misses: {metrics.get('cache_misses', 0)}")


if __name__ == "__main__":
    asyncio.run(main())
