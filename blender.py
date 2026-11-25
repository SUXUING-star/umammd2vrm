import json
import os
import sys

import bpy

# 1. 获取当前 .blend 所在目录
blend_dir = bpy.path.abspath("//")

# 2. 读取同级 config.json
config_path = os.path.join(blend_dir, "config.json")
if not os.path.exists(config_path):
    raise FileNotFoundError(f"❌ 目录下未找到 config.json: {config_path}")

with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

# 3. 直接指定 src 绝对路径
scripts_dir = r"E:\3dmodels\blenders\umammd2vrm\src"
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

# 4. 清理模块缓存
for m in list(sys.modules.keys()):
    if m == "main" or m.startswith("step"):
        del sys.modules[m]

# 5. 运行主程序
import main

main.run(config)
