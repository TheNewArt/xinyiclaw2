# demo_realtime.py - 实时对比演示
# 同时向两个项目发送相同请求，对比响应和延迟

import asyncio
import httpx
import time


async def send_chat(client: httpx.AsyncClient, port: int, message: str, session_id: str = "demo") -> dict:
    start = time.perf_counter()
    try:
        response = await client.post(
            f"http://localhost:{port}/api/chat",
            json={"message": message, "session_id": session_id},
            timeout=120.0
        )
        latency_ms = (time.perf_counter() - start) * 1000
        data = response.json()
        return {
            "port": port,
            "success": response.status_code == 200,
            "latency_ms": latency_ms,
            "response": data.get("response", "Error")[:150] if response.status_code == 200 else "Error",
            "error": data.get("error") if response.status_code != 200 else None
        }
    except Exception as e:
        return {
            "port": port,
            "success": False,
            "latency_ms": (time.perf_counter() - start) * 1000,
            "response": None,
            "error": str(e)
        }


async def get_status(client: httpx.AsyncClient, port: int) -> dict:
    try:
        response = await client.get(f"http://localhost:{port}/api/status", timeout=10.0)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return {}


async def run_demo(prompts: list):
    async with httpx.AsyncClient() as client:
        print("\n  [初始状态]")
        status_new = await get_status(client, 5002)
        if "metrics" in status_new:
            m = status_new["metrics"]
            print(f"    新版请求数: {m.get('total_requests', 0)}")

        print("\n" + "=" * 60)
        print("  开始实时对比测试")
        print("=" * 60)

        for i, prompt in enumerate(prompts, 1):
            print(f"\n  [Prompt {i}/{len(prompts)}]")
            print(f"  User: {prompt[:50]}{'...' if len(prompt) > 50 else ''}")

            start = time.perf_counter()
            result_old, result_new = await asyncio.gather(
                send_chat(client, 5000, prompt),
                send_chat(client, 5002, prompt)
            )
            total_time = (time.perf_counter() - start) * 1000

            print(f"\n  >> 旧版 (5000): {result_old['latency_ms']:.0f}ms")
            if result_old["success"]:
                print(f"     {result_old['response'][:80]}...")
            else:
                print(f"     Error: {result_old['error']}")

            print(f"\n  >> 新版 (5002): {result_new['latency_ms']:.0f}ms")
            if result_new["success"]:
                print(f"     {result_new['response'][:80]}...")
            else:
                print(f"     Error: {result_new['error']}")

            diff = abs(result_old["latency_ms"] - result_new["latency_ms"])
            faster = "旧版" if result_old["latency_ms"] < result_new["latency_ms"] else "新版"
            winner = "*" if result_old["latency_ms"] < result_new["latency_ms"] else ""
            print(f"\n  => {faster}快 {diff:.0f}ms | 总耗时: {total_time:.0f}ms {winner}")

            await asyncio.sleep(0.5)

        print("\n" + "=" * 60)
        print("  最终状态对比")
        print("=" * 60)

        status_new = await get_status(client, 5002)
        if "metrics" in status_new:
            m = status_new["metrics"]
            print(f"\n  新版 (5002) Metrics:")
            print(f"    总请求: {m.get('total_requests', 0)}")
            print(f"    平均延迟: {m.get('avg_latency_ms', 0):.1f}ms")
            print(f"    缓存命中率: {m.get('cache_hit_rate_%', 0):.1f}%")
            print(f"    预测准确率: {m.get('prediction_accuracy_%', 0):.1f}%")
            print(f"    预取命中率: {m.get('prefetch_hit_rate_%', 0):.1f}%")
            print(f"    峰值并发: {m.get('peak_in_flight', 0)}")


async def main():
    print("""
============================================================
        XinyiClaw 实时对比演示
============================================================
    """)
    print("  使用默认 prompts 进行测试...\n")

    default_prompts = [
        "你好，你是什么模型？",
        "解释一下什么是 CPU 的分支预测",
        "写一个快速排序的 Python 实现",
        "什么是 LRU 缓存？",
        "用 Python 写一个简单的 HTTP 服务器",
    ]

    await run_demo(default_prompts)
    print("\n  演示完成!\n")


if __name__ == "__main__":
    print("""
    使用说明:
    1. 确保两个项目都在运行:
       - 旧版: python -m src.web_app  (端口 5000)
       - 新版: python -m src.web_app  (端口 5002)
    
    2. 运行演示:
       python demo_realtime.py
    """)
    asyncio.run(main())
