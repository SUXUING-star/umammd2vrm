# --- START OF FILE step0_clean.py ---
import bpy


def run():
    print(">>> [步骤 0] 无损法线清理与脸部法线保护...")

    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data:
            continue

        obj_name_lower = obj.name.lower()
        # 🎯 判断是否为脸部/头部网格
        is_face = any(
            kw in obj_name_lower for kw in ["face", "kao", "head", "mayu", "eye"]
        )

        # 1. 🌟 如果是身体/衣服，清除自定义法线重新平滑；如果是脸部，千万不能清除！
        if not is_face:
            try:
                obj.data.clear_custom_normals()
            except Exception:
                pass
            try:
                bpy.context.view_layer.objects.active = obj
                bpy.ops.mesh.customdata_custom_splitnormals_clear()
            except Exception:
                pass
        else:
            print(
                f"   🛡️ [法线保护] 检测到脸部/头部网格 [{obj.name}]，保留原厂球体平滑法线！"
            )

        # 2. 🌟 强制全网格平滑着色
        try:
            for poly in obj.data.polygons:
                poly.use_smooth = True
        except Exception:
            pass

        # 3. 🌟 清理可能导致嘴角变黑的顶点色 (Vertex Colors)
        if obj.data.color_attributes:
            try:
                # 移除烘焙了暗部 AO 的顶点色图层，防止 WebGL 渲染时嘴角乘法变黑
                while obj.data.color_attributes:
                    obj.data.color_attributes.remove(obj.data.color_attributes[0])
                print(f"   🧹 已清理网格 [{obj.name}] 的残存顶点色暗部遮罩。")
            except Exception:
                pass

    print("✅ [步骤 0] 法线保护与顶点色清理完成！")
