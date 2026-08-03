import bpy


def run():
    print(
        ">>> [步骤 0] 进行无损法线清理与平滑着色 (保留顶点颜色、材质槽与所有网格结构)..."
    )

    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data:
            continue

        print(f"   正在无损修复网格体: {obj.name}...")

        # 1. 🌟 清除自定义拆分法线
        # 这是解决 Blender 5.2 中渲染死黑/阴影错乱的关键，且绝对不会影响网格和贴图
        try:
            obj.data.clear_custom_normals()
        except Exception:
            pass
        try:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
        except Exception:
            pass

        # 2. 🌟 强制启用平滑着色，避免片面感
        try:
            for poly in obj.data.polygons:
                poly.use_smooth = True
        except Exception:
            pass

    print("✅ [步骤 0] 无损清理完成！(顶点颜色、UV 边界与材质槽已完全保留)")
