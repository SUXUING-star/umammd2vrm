# --- START OF FILE main.py ---
import os
import sys

# 导入所有具体的步骤模块
import step0_clean
import step1_skeleton
import step2_expressions
import step3_bind_vrm
import step4_toon_calibration
import step5_eye_bake
import step6_texture_nodes


def run(texture_dir):
    print("\n=== [开始执行模块化卡渲处理流程] ===")
    try:
        # 1. 清理与平滑
        step0_clean.run()

        # 2. 骨骼与命名规整
        step1_skeleton.run()

        # 3. 规范化形态键命名
        step2_expressions.run()

        # 4. 绑定 VRM 表情
        step3_bind_vrm.run()

        # 5. MToon 参数调校
        step4_toon_calibration.run()

        # 6. 眼睛贴图烘焙
        step5_eye_bake.run(texture_dir)

        # 7. 重建材质节点与贴图绑定
        step6_texture_nodes.run(texture_dir)

        print("=== [全部处理完成！可以导出 VRM 文件] ===")

    except Exception as e:
        print(f"\n❌ 运行中出现错误: {e}")
        import traceback

        traceback.print_exc()
