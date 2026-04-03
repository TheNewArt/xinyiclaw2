# test_fair.py - 公平测试
# 清空状态后只测真正的 LLM 响应时间，不依赖缓存

import asyncio
import httpx
import time


async def send_chat(client, port, message, session_id):
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
            "response": data.get("response", "Error")[:100] if response.status_code == 200 else "Error"
        }
    except Exception as e:
        return {"port": port, "success": False, "latency_ms": 0, "response": str(e)}


async def clear_and_wait(client, port):
    """清空会话并等待"""
    await client.post(f"http://localhost:{port}/api/clear", json={"session_id": "fair_test"}, timeout=10.0)
    await asyncio.sleep(0.5)


async def get_metrics(client, port):
    try:
        r = await client.get(f"http://localhost:{port}/api/status", timeout=10.0)
        if r.status_code == 200:
            return r.json().get("metrics", {})
    except:
        pass
    return {}


async def main():
    print("""
============================================================
        公平测试：清空缓存后对比
============================================================
    """)

    prompts = [
        "用 Python 实现一个二分查找",
        "解释什么是 RESTful API",
        "写一个合并两个有序数组的算法",
        "什么是数据库索引？",
        "用 Python 发送 HTTP 请求的方法",
    ]

    async with httpx.AsyncClient() as client:
        # 清空两个项目的缓存
        print("\n  [准备] 清空两个项目的缓存...")
        await clear_and_wait(client, 5000)
        await clear_and_wait(client, 5002)
        print("  完成\n")

        # ========== 测试旧版 (5000) ==========
        print("=" * 60)
        print("  测试旧版 (5000) - 5个不同 prompt")
        print("=" * 60)

        old_latencies = []
        await clear_and_wait(client, 5000)  # 确保清空

        for i, p in enumerate(prompts, 1):
            result = await send_chat(client, 5000, p, "fair_test_old")
            old_latencies.append(result["latency_ms"])
            status = "OK" if result["success"] else "FAIL"
            print(f"  [{i}/5] {result['latency_ms']:.0f}ms - {status}")

        old_avg = sum(old_latencies) / len(old_latencies)
        print(f"\n  旧版平均延迟: {old_avg:.0f}ms")

        # 等待一下
        await asyncio.sleep(2)

        # ========== 测试新版 (5002) ==========
        print("\n" + "=" * 60)
        print("  测试新版 (5002) - 5个不同 prompt (同样清空缓存)")
        print("=" * 60)

        new_latencies = []
        await clear_and_wait(client, 5002)  # 确保清空

        for i, p in enumerate(prompts, 1):
            result = await send_chat(client, 5002, p, "fair_test_new")
            new_latencies.append(result["latency_ms"])
            status = "OK" if result["success"] else "FAIL"
            print(f"  [{i}/5] {result['latency_ms']:.0f}ms - {status}")

        new_avg = sum(new_latencies) / len(new_latencies)
        print(f"\n  新版平均延迟: {new_avg:.0f}ms")

        # 打印对比
        print("\n" + "=" * 60)
        print("  公平对比结果")
        print("=" * 60)

        improvement = ((old_avg - new_avg) / old_avg) * 100 if old_avg > 0 else 0

        print(f"\n  旧版 (5000) 平均: {old_avg:.0f}ms")
        print(f"  新版 (5002) 平均: {new_avg:.0f}ms")
        if improvement > 0:
            print(f"  新版快: {improvement:.1f}%")
        else:
            print(f"  旧版快: {-improvement:.1f}%")

        # 打印详细对比
        print("\n  详细对比:")
        print(f"  {'Prompt':<30} {'旧版':>10} {'新版':>10} {'胜者':>10}")
        print(f"  {'-'*62}")
        for i, p in enumerate(prompts):
            old_l = old_latencies[i]
            new_l = new_latencies[i]
            winner = "新版" if new_l < old_l else "旧版"
            print(f"  {p[:28]:<30} {old_l:>8.0f}ms {new_l:>8.0f}ms {winner:>10}")


if __name__ == "__main__":
    print("确保两个服务都在运行:")
    print("  - 旧版: python -m src.web_app (端口 5000)")
    print("  - 新版: python -m src.web_app (端口 5002)")
    print()
    asyncio.run(main())
