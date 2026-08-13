"""外脑伙伴 —— v2 演示脚本

运行：python3 demo.py
演示内容（覆盖规格 2.2-5.4）：
1. 画像初始化（5 问）
2. 任务 1：澄清 → 规格确认 → 框架预览 → 内容填充 → 成品交付（含评分反馈）
3. 任务 2：主动暂停 → 记录放弃点
4. 任务 3：断点续传询问 + 高相似任务复用（跳过提问）+ 完成
5. 命令：调整画像（规格 5.3）
"""

from __future__ import annotations

import shutil
from collections import deque
from pathlib import Path

from waibao.agent import PersonalExplorerAgent
from waibao.interaction import ConsoleInterface


def main() -> None:
    demo_dir = Path(__file__).parent / "demo_data"
    if demo_dir.exists():
        shutil.rmtree(demo_dir)

    script = deque([
        # --- 画像初始化（5 问，规格 2.2）---
        "直接给框架",   # 宏观优先
        "制作",         # 音乐领域角色
        "中性",         # 语气
        "继续修改",     # 高 abandon 风险
        "不需要",       # 举例偏好低
        # --- 任务 1：生成型（澄清 2 问）---
        "独立音乐人",
        "完整文案",
        "确认",         # 规格确认
        "继续",         # 框架草案 → 内容填充
        "4分，多给点细节",  # 内容填充后：评分 + 显式信号
        "5分",          # 成品交付后评分
        # --- 任务 2：整理型（只问 1 个缺口，然后暂停）---
        "独立音乐人",
        "确认",
        "先这样",       # 框架草案后暂停（规格 4.4 放弃点）
        # --- 任务 3：新任务 → 断点续传询问 → 高相似复用 ---
        "新任务",       # 对“上次任务要继续吗”的回答
        "确认",
        "继续",
        "4分",
        "5分",
        # --- 命令演示：调整画像（规格 5.3）---
        "expression.output_tone",
        "casual",
    ])

    interface = ConsoleInterface(input_fn=lambda prompt: script.popleft())
    agent = PersonalExplorerAgent(storage_dir=demo_dir, interface=interface)

    print("=" * 64)
    print("步骤 1/6：画像初始化")
    print("=" * 64)
    agent.ensure_profile_initialized()

    print("\n" + "=" * 64)
    print("步骤 2/6：任务 1 —— 澄清 → 规格确认 → 四阶段交付 → 评分反馈")
    print("=" * 64)
    agent.start_new_task("我想做一个关于音乐行业的播客栏目，帮我出个方案")

    print("\n" + "=" * 64)
    print("步骤 3/6：任务 2 —— 用户主动暂停，记录放弃点")
    print("=" * 64)
    agent.start_new_task("帮我整理一份播客选题清单")

    print("\n" + "=" * 64)
    print("步骤 4/6：任务 3 —— 断点续传询问 + 高相似任务复用（跳过提问）")
    print("=" * 64)
    agent.start_new_task("帮我策划一期关于现场演出市场的播客节目")

    print("\n" + "=" * 64)
    print("步骤 5/6：命令 —— 调整画像（规格 5.3）")
    print("=" * 64)
    agent.handle("调整画像")

    print("\n" + "=" * 64)
    print("步骤 6/6：画像进化结果")
    print("=" * 64)
    for rec in agent.profile.update_log[-10:]:
        print(f"  · {rec['reason']}：{rec['field']} {rec['before']} → {rec['after']}")
    print("\n" + agent.profile.summary())

    print("\n✅ 演示完成。生成的记忆文件：")
    for f in sorted(demo_dir.iterdir()):
        print("  ", f)


if __name__ == "__main__":
    main()

