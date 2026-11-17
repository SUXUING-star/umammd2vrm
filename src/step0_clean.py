import bpy
from mathutils import Vector, kdtree


def snapshot_custom_normals(mesh):
    """在修改任何几何体之前，按 (顶点坐标 + 微小面法线偏置) 备份每个 Loop 的原始法线"""
    if hasattr(mesh, "corner_normals"):  # Blender 4.1+
        loop_normals = [Vector(cn.vector) for cn in mesh.corner_normals]
    else:  # Blender 3.x ~ 4.0
        mesh.calc_normals_split()
        loop_normals = [Vector(l.normal) for l in mesh.loops]

    verts = mesh.vertices
    loops = mesh.loops
    n_loops = len(loops)
    kd = kdtree.KDTree(n_loops)

    for poly in mesh.polygons:
        p_no = poly.normal
        for l_idx in poly.loop_indices:
            v_co = verts[loops[l_idx].vertex_index].co
            # 加入 0.001 * 面法线偏置，区分硬边/UV接缝处同坐标不同朝向的拆分法线
            kd.insert(v_co + p_no * 0.001, l_idx)

    kd.balance()
    return kd, loop_normals


def restore_custom_normals(mesh, kd, orig_loop_normals):
    """用 KDTree 把原始法线无损还原到清理后的网格上（支持带形态键的网格）"""
    if hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True

    verts = mesh.vertices
    loops = mesh.loops
    restored = [(0.0, 0.0, 1.0)] * len(loops)

    for poly in mesh.polygons:
        p_no = poly.normal
        for l_idx in poly.loop_indices:
            v_co = verts[loops[l_idx].vertex_index].co
            _, orig_idx, _ = kd.find(v_co + p_no * 0.001)
            restored[l_idx] = tuple(orig_loop_normals[orig_idx])

    mesh.normals_split_custom_set(restored)
    mesh.update()


def push_vertices_along_normals(obj, strength=0.0004):
    """安全外扩顶点消除跨网格 Z-Fighting（兼容带 Shape Keys 的网格，且不破坏法线）"""
    mesh = obj.data

    # 预先记录当前精确法线，防止位置偏移后法线重算
    if hasattr(mesh, "corner_normals"):
        exact_normals = [tuple(cn.vector) for cn in mesh.corner_normals]
    else:
        mesh.calc_normals_split()
        exact_normals = [tuple(l.normal) for l in mesh.loops]

    # 计算每个顶点的平均平滑偏移方向
    v_count = len(mesh.vertices)
    vert_dirs = [Vector((0.0, 0.0, 0.0)) for _ in range(v_count)]
    for l_idx, loop in enumerate(mesh.loops):
        vert_dirs[loop.vertex_index] += Vector(exact_normals[l_idx])

    for i in range(v_count):
        if vert_dirs[i].length_squared > 1e-12:
            vert_dirs[i].normalize()
        else:
            vert_dirs[i] = Vector(mesh.vertices[i].normal)

    if mesh.shape_keys and len(mesh.shape_keys.key_blocks) > 0:
        # 带形态键时直接推进 Basis（相对形态键会自动跟随 Basis 偏移）
        basis = mesh.shape_keys.key_blocks[0]
        for i, kb_vert in enumerate(basis.data):
            kb_vert.co += vert_dirs[i] * strength
        mesh.update()
    else:
        for i, vert in enumerate(mesh.vertices):
            vert.co += vert_dirs[i] * strength
        mesh.update()

    # 锁死回原法线
    if hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True
    mesh.normals_split_custom_set(exact_normals)
    mesh.update()


def run():
    print(">>> [步骤 0] 无损法线保护 + 几何去重与抗卡模 (Anti-Z-Fighting) 处理...")

    # 🌟 1. 清理冗余阴影/Dummy网格 (防止物理重叠闪烁)
    GARBAGE_MESH_KEYWORDS = ["shadow", "dummy", "mmd_shadow", "mmd_dummy"]
    for obj in list(bpy.data.objects):
        if obj.type == "MESH":
            obj_name_lower = obj.name.lower()
            if any(kw in obj_name_lower for kw in GARBAGE_MESH_KEYWORDS):
                print(f"   🧹 清理冗余阴影/Dummy网格: [{obj.name}]")
                bpy.data.objects.remove(obj, do_unlink=True)

    # 🌟 2. 清理顶点色 + 消除重叠面 + 衣服微米级外扩（全程锁死原法线）
    for obj in list(bpy.data.objects):
        if obj.type != "MESH" or not obj.data:
            continue

        # 仅在原本没有自定义法线时才开平滑着色，防止覆盖已有自定义法线
        try:
            if not obj.data.has_custom_normals:
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

        # A. 备份原始法线
        kd = None
        orig_loop_normals = None
        try:
            kd, orig_loop_normals = snapshot_custom_normals(obj.data)
        except Exception as e:
            print(f"   ⚠️ 网格 [{obj.name}] 法线备份跳过: {e}")

        # B. 消除共面重叠顶点与退化面（不调用 normals_make_consistent，避免单面衣服法线被翻错）
        try:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.remove_doubles(threshold=0.00005)
            bpy.ops.mesh.dissolve_degenerate(threshold=0.0001)
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception as e:
            print(f"   ⚠️ 网格 [{obj.name}] 几何清理跳过: {e}")
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        # C. 立即把原始法线无损还原回来
        if kd is not None and orig_loop_normals:
            try:
                restore_custom_normals(obj.data, kd, orig_loop_normals)
            except Exception as e:
                print(f"   ⚠️ 网格 [{obj.name}] 法线还原跳过: {e}")

        # D. 对外套/衣服网格应用 0.4mm 微推（兼容带形态键网格，且保持还原后的原法线不变）
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
                push_vertices_along_normals(obj, strength=0.0004)
                print(
                    f"   ✨ 已对衣服网格 [{obj.name}] 应用 0.4mm 无损法线外扩，消除闪烁卡模！"
                )
            except Exception as e:
                print(f"   ⚠️ 衣服网格 [{obj.name}] 微推失败: {e}")

    print("✅ [步骤 0] 无损法线保护与抗卡模处理完成！")
