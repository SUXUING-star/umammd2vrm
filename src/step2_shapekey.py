import re

import bpy


def get_armature_and_shape_meshes():
    armature_obj = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if not armature_obj:
        return None, []

    mesh_objs = []
    seen = set()

    for child in armature_obj.children:
        if child.type == "MESH" and child.data and child.data.shape_keys:
            if len(child.data.shape_keys.key_blocks) > 1:
                mesh_objs.append(child)
                seen.add(child.name)

    for obj in bpy.data.objects:
        if (
            obj.name in seen
            or obj.type != "MESH"
            or not obj.data
            or not obj.data.shape_keys
        ):
            continue
        if len(obj.data.shape_keys.key_blocks) <= 1:
            continue
        for mod in obj.modifiers:
            if mod.type == "ARMATURE" and mod.object == armature_obj:
                mesh_objs.append(obj)
                seen.add(obj.name)
                break

    return armature_obj, mesh_objs


def run():
    print(">>> [步骤 2/4] 开始规范全部 MMD 网格的表情形态键命名...")

    armature_obj, mesh_objs = get_armature_and_shape_meshes()
    if not armature_obj or not mesh_objs:
        print("⚠️ 未找到包含形态键的目标网格，跳过表情规范化。")
        return

    total_renamed = 0
    for mesh_obj in mesh_objs:
        key_blocks = mesh_obj.data.shape_keys.key_blocks
        existing_names = {k.name for k in key_blocks}

        for key in key_blocks:
            if key.name.lower() in ["basis", "base", "基础", "ベース"]:
                continue

            # 剥离如 "001." / "01_" / 前后空格
            clean_name = re.sub(r"^\d+[\._\-\s]+", "", key.name).strip()
            if clean_name and clean_name != key.name:
                if clean_name not in existing_names:
                    existing_names.discard(key.name)
                    key.name = clean_name
                    existing_names.add(clean_name)
                    total_renamed += 1

    print(
        f"✅ [步骤 2/4] 已扫描 {len(mesh_objs)} 个含形态键网格，完成 {total_renamed} 个形态键前缀清洗！"
    )
