import re

import bpy


def run():
    print(">>> [步骤 2/4] 开始规范表情命名，剥离形态键前缀...")

    armature_obj = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    mesh_obj = None
    if armature_obj:
        for child in armature_obj.children:
            if child.type == "MESH" and child.data.shape_keys:
                if len(child.data.shape_keys.key_blocks) > 50:
                    mesh_obj = child
                    break

    if not mesh_obj:
        print("⚠️ 未找到目标网格，跳过表情规范化。")
        return

    key_blocks = mesh_obj.data.shape_keys.key_blocks

    count = 0
    for key in key_blocks:
        if key.name.lower() in ["basis", "base", "基础"]:
            continue
        clean_name = re.sub(r"^\d+\.", "", key.name)
        if clean_name != key.name:
            key.name = clean_name
            count += 1

    print(f"✅ [步骤 2/4] 形态键前缀清洗完成！")
