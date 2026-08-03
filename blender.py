import json
import os
import sys

import bpy

# 1. 获取当前 .blend 所在目录 (public/<角色名>/)
blend_dir = bpy.path.abspath("//")

# 2. 读取同级 config.json
config_path = os.path.join(blend_dir, "config.json")
if not os.path.exists(config_path):
    raise FileNotFoundError(f"❌ 目录下未找到 config.json: {config_path}")

with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

# 3. 寻找 src/ 目录并加入 sys.path
scripts_rel = config.get("scripts_dir", "src")
project_root = os.path.abspath(os.path.join(blend_dir, "..", ".."))
scripts_dir = os.path.abspath(os.path.join(project_root, scripts_rel))

# 兜底：若向上两级没找到 src，逐级向上找
if not os.path.exists(scripts_dir):
    curr = blend_dir
    while True:
        candidate = os.path.join(curr, scripts_rel)
        if os.path.exists(candidate):
            scripts_dir = candidate
            break
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent

if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

# 4. 清理模块缓存
for m in list(sys.modules.keys()):
    if m == "main" or m.startswith("step"):
        del sys.modules[m]

# 5. 运行主程序
import main

main.run(config)
