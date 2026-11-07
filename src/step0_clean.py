import bpy


def run():
    print(">>> [步骤 0] 法线保护、重叠面清理与抗卡模 (Anti-Z-Fighting) 处理...")

    # 🌟 1. 清理冗余阴影/Dummy网格 (防止物理重叠闪烁)
    GARBAGE_MESH_KEYWORDS = ["shadow", "dummy", "mmd_shadow", "mmd_dummy"]
    for obj in list(bpy.data.objects):
        if obj.type == "MESH":
            obj_name_lower = obj.name.lower()
            if any(kw in obj_name_lower for kw in GARBAGE_MESH_KEYWORDS):
                print(f"   🧹 清理冗余阴影/Dummy网格: [{obj.name}]")
                bpy.data.objects.remove(obj, do_unlink=True)

    # 🌟 2. 网格几何清理、法线重置与衣服微米级外扩
    for obj in list(bpy.data.objects):
        if obj.type != "MESH" or not obj.data:
            continue

        # 强制开启平滑着色
        try:
            for poly in obj.data.polygons:
                poly.use_smooth = True
        except Exception:
            pass

        # 清理可能导致嘴角/面部黑斑的顶点色
        if obj.data.color_attributes:
            try:
                while obj.data.color_attributes:
                    obj.data.color_attributes.remove(obj.data.color_attributes[0])
                print(f"   🧹 已清理网格 [{obj.name}] 的残存顶点色遮罩。")
            except Exception:
                pass

        # 进入编辑模式进行几何去重与统一法线
        try:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")

            # A. 消除重叠顶点 (Threshold: 0.00005m)
            bpy.ops.mesh.remove_doubles(threshold=0.00005)

            # B. 清理退化面
            bpy.ops.mesh.dissolve_degenerate(threshold=0.0001)

            # C. 统一法线向外 (防止法线反转导致的双面闪烁)
            bpy.ops.mesh.normals_make_consistent(inside=False)

            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception as e:
            print(f"   ⚠️ 网格 [{obj.name}] 几何清理跳过: {e}")
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        # 🌟 3. 抗卡模核心：对外套/衣服网格应用微米级法线外扩 (Displace Offset)
        # 解决赛马娘模型中身体皮肤 mesh 与衣服 mesh 0距离重叠导致的 Z-Fighting 穿模闪烁
        obj_name_lower = obj.name.lower()
        is_clothing = any(
            kw in obj_name_lower
            for kw in [
                "bdy",
                "body",
                "cloth",
                "wear",
                "dress",
                "costume",
                "jacket",
                "skirt",
                "top",
                "bottom",
            ]
        )
        is_inner_skin = any(
            kw in obj_name_lower for kw in ["skin", "inner", "naked", "kao", "face"]
        )

        if is_clothing and not is_inner_skin:
            try:
                # 添加微小法线膨胀，将衣服微推 0.0004 米 (0.4 毫米)
                disp_mod = obj.modifiers.new(
                    name="Anti_ZFighting_Push", type="DISPLACE"
                )
                disp_mod.mid_level = 0.0
                disp_mod.strength = (
                    0.0004  # 0.4mm 微推，肉眼不可见，彻底消除 Depth-Fighting
                )

                # 立即应用修改器，烘焙入顶点坐标
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.modifier_apply(modifier=disp_mod.name)
                print(
                    f"   ✨ 已对衣服网格 [{obj.name}] 应用 0.4mm 微米级法线外扩，彻底消除闪烁卡模！"
                )
            except Exception as e:
                print(f"   ⚠️ 衣服网格 [{obj.name}] 微推失败: {e}")

    print("✅ [步骤 0] 法线保护、重叠面清理与抗卡模处理完成！")
