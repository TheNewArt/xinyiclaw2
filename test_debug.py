# test_debug.py - 调试测试，看看实际返回了什么
import asyncio
import httpx


async def main():
    async with httpx.AsyncClient() as client:
        # 清空
        await client.post("http://localhost:5002/api/clear", json={"session_id": "debug"}, timeout=10.0)
        await asyncio.sleep(0.5)

        prompt = "用 Python 实现一个二分查找"
        print(f"Prompt: {prompt}\n")

        # 发一次请求
        r = await client.post(
            "http://localhost:5002/api/chat",
            json={"message": prompt, "session_id": "debug"},
            timeout=120.0
        )
        print(f"Status: {r.status_code}")
        print(f"Response: {r.text[:500]}")
        
        # 看 metrics
        m = await client.get("http://localhost:5002/api/status", timeout=10.0)
        metrics = m.json().get("metrics", {})
        print(f"\nMetrics:")
        print(f"  cache_hits: {metrics.get('cache_hits', 0)}")
        print(f"  cache_misses: {metrics.get('cache_misses', 0)}")
        print(f"  avg_latency: {metrics.get('avg_latency_ms', 0)}")


if __name__ == "__main__":
    asyncio.run(main())
