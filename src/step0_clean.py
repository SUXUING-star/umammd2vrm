import bpy


def run():
    print(">>> [步骤 0] 法线保护与顶点色暗部清理...")

    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data:
            continue

        # 🌟 1. 全网格保留原厂自定义法线（不再清除衣服/身体法线，保留布料转折细节）
        # 强制开启平滑着色
        try:
            for poly in obj.data.polygons:
                poly.use_smooth = True
        except Exception:
            pass

        # 🌟 2. 清理可能导致嘴角变黑的顶点色 (Vertex Colors)
        if obj.data.color_attributes:
            try:
                while obj.data.color_attributes:
                    obj.data.color_attributes.remove(obj.data.color_attributes[0])
                print(f"   🧹 已清理网格 [{obj.name}] 的残存顶点色遮罩。")
            except Exception:
                pass

    print("✅ [步骤 0] 法线保护与顶点色清理完成！")
