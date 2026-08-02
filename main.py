# --- START OF FILE main.py ---
import os
import sys

# 导入具体的步骤模块
import step0_clean
import step1_skeleton
import step2_expressions
import step3_bind_vrm
import step4_eye_bake  # 引入我们刚刚重新设计的干净清洗和不透明度映射脚本
import step5_new_texture_nodes  # 引入我们刚刚重新设计的干净清洗和不透明度映射脚本


def run(texture_dir, jp_model_name, en_model_name):
    print("\n=== [开始执行模块化处理：规整骨骼、表情并清洗材质不透明度] ===")
    try:
        # 1. 顶点法线清理与平滑着色
        step0_clean.run()

        # 2. 骨骼规范化与 Humanoid 骨骼映射
        step1_skeleton.run(jp_model_name, en_model_name)

        # 3. 规范化形态键（Blendshapes）命名
        step2_expressions.run()

        # 4. 绑定 VRM 表情并执行冗余形态键瘦身
        step3_bind_vrm.run()

        # 5. 材质安全清洗与标准主贴图映射
        # 此步骤强制将大面积皮肤、衣服、头发设为 OPAQUE（不透明），睫毛眉毛设为 CLIP（裁剪）
        # 从底层文件结构上，彻底杜绝 Web 端加载后全身穿透、透明的致命 Bug
        step4_eye_bake.run(texture_dir)

        step5_new_texture_nodes.run(texture_dir)

        print("\n=== [处理完成！] ===")
        print("现在可以安全导出为标准 GLTF 或 VRM。")
        print("导出的模型在 WebGL (Three.js 等) 中将拥有 100% 正确的不透明度深度渲染。")

    except Exception as e:
        print(f"\n❌ 运行中出现错误: {e}")
        import traceback

        traceback.print_exc()
