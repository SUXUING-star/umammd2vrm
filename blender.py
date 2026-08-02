import os
import sys

import bpy

ENGLISH_MODEL_NAME = "Mejiro Bright"
JP_NAME = "メジロブライト"
# 1. 贴图存放的绝对路径（在此处集中修改）
TEXTURE_DIR = r"E:\3dmodels\mejiro bright mizugi\Texture2D"

if not bpy.data.is_saved:
    raise Exception("❌ 请先保存当前的 Blender 工程，以便脚本确定相对路径！")

blend_dir = bpy.path.abspath("//")
scripts_dir = os.path.normpath(os.path.join(blend_dir, "vrm_scripts"))

# 将外部脚本目录加入系统路径
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

# 强力清理 Blender 中的旧模块缓存，确保外部代码修改后能实时生效
for m in list(sys.modules.keys()):
    if m == "main" or m.startswith("step") or m == "utils":
        del sys.modules[m]

# 2. 一键导入并运行
try:
    import main

    main.run(TEXTURE_DIR, ENGLISH_MODEL_NAME, JP_NAME)
except Exception as e:
    print(f"❌ 启动失败: {e}")
