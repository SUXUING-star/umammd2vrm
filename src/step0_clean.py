import math
from collections import defaultdict

import bmesh
import bpy
from mathutils import Vector, kdtree


def snapshot_custom_normals(mesh):
    """备份每个 Loop 的原始法线，用于保护非皮肤/硬边区域"""
    if hasattr(mesh, "corner_normals"):  # Blender 4.1+
        loop_normals = [Vector(cn.vector) for cn in mesh.corner_normals]
    else:  # Blender 3.x ~ 4.0
        mesh.calc_normals_split()
        loop_normals = [Vector(l.normal) for l in mesh.loops]

    verts = mesh.vertices
    loops = mesh.loops
    kd = kdtree.KDTree(len(loops))

    for poly in mesh.polygons:
        p_no = poly.normal
        for l_idx in poly.loop_indices:
            v_co = verts[loops[l_idx].vertex_index].co
            kd.insert(v_co + p_no * 0.001, l_idx)

    kd.balance()
    return kd, loop_normals


def restore_custom_normals(mesh, kd, orig_loop_normals):
    """还原非皮肤区域的原始自定义法线"""
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


def classify_poly_surface(obj_name_low, mat_name_low):
    """按材质名（兜底对象名）区分需要法线重构的区域"""
    target = mat_name_low or obj_name_low

    EXCLUDE_KW = (
        "eye",
        "lash",
        "mayu",
        "brow",
        "eyeline",
        "tooth",
        "teeth",
        "tongue",
        "mouth_in",
        "hair",
        "kami",
        "ribbon",
        "metal",
        "button",
        "shoe",
        "boot",
        "cloth",
        "wear",
        "dress",
        "skirt",
        "jacket",
        "瞳",
        "目",
        "睫",
        "眉",
        "歯",
        "舌",
        "髪",
        "靴",
        "服",
    )
    if any(kw in target for kw in EXCLUDE_KW):
        return "other"

    if any(kw in target for kw in ("face", "kao", "cheek", "顔")):
        return "face_skin"

    if any(kw in target for kw in ("skin", "hada", "naked", "肌", "素体")):
        return "body_skin"

    if any(kw in target for kw in ("bdy", "body", "karada", "体")):
        return "body_mixed"

    return "other"


def get_head_bone_local_z(obj):
    """查找头部骨骼在当前网格局部空间中的 Z 高度，用于区分脸部和脖子"""
    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if not armature:
        return None
    for bone in armature.data.bones:
        b_low = bone.name.lower()
        if "head" in b_low or "頭" in bone.name:
            world_pos = armature.matrix_world @ bone.head_local
            local_pos = obj.matrix_world.inverted() @ world_pos
            return local_pos.z
    return None


def compute_proxy_smooth_normals(orig_obj, poly_indices, iterations):
    """
    复制无 Shape Keys 的代理网格，锁死开口/材质边界顶点，
    通过位置平滑修改器抹平低模三角面凹凸后，返回 1-to-1 对应顶点的平滑法线。
    """
    orig_mesh = orig_obj.data
    poly_set = set(poly_indices)

    # 统计目标组顶点以及组外/开口边界顶点（边界顶点锁死位置不参与平滑收缩）
    bm = bmesh.new()
    bm.from_mesh(orig_mesh)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    group_verts = set()
    pinned_verts = set()
    for f_idx in poly_indices:
        for v in bm.faces[f_idx].verts:
            group_verts.add(v.index)

    for edge in bm.edges:
        in_group_faces = [f for f in edge.link_faces if f.index in poly_set]
        if not in_group_faces:
            continue
        # 开口边界（如眼眶、嘴唇、颈口）或与非目标面交界：锁死
        if len(edge.link_faces) == 1 or len(in_group_faces) < len(edge.link_faces):
            pinned_verts.add(edge.verts[0].index)
            pinned_verts.add(edge.verts[1].index)
    bm.free()

    # 创建临时代理对象（保留严格 1-to-1 顶点索引）
    proxy_mesh = orig_mesh.copy()
    proxy_obj = bpy.data.objects.new("__tmp_norm_proxy__", proxy_mesh)
    bpy.context.scene.collection.objects.link(proxy_obj)

    try:
        # 1. 清除代理上的 Shape Keys（保留 Basis 形状）
        if proxy_obj.data.shape_keys:
            for kb in list(proxy_obj.data.shape_keys.key_blocks)[::-1]:
                proxy_obj.shape_key_remove(kb)

        # 2. 清除旧自定义法线与锐边标记，强制全平滑
        bpy.context.view_layer.objects.active = proxy_obj
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        try:
            bpy.ops.mesh.customdata_custom_splitnormals_clear()
        except Exception:
            pass

        for p in proxy_mesh.polygons:
            p.use_smooth = True
        for e in proxy_mesh.edges:
            if hasattr(e, "use_edge_sharp"):
                e.use_edge_sharp = False

        # 3. 写入光滑权重组（内部顶点=1.0，边界顶点=0.0）
        vg = proxy_obj.vertex_groups.new(name="__smooth_mask__")
        interior_verts = [v for v in group_verts if v not in pinned_verts]
        if interior_verts:
            vg.add(interior_verts, 1.0, "REPLACE")
        if pinned_verts:
            vg.add(list(pinned_verts), 0.0, "REPLACE")

        # 4. 对代理网格做几何位置松弛
        mod = proxy_obj.modifiers.new(name="SmoothProxy", type="SMOOTH")
        mod.factor = 0.5
        mod.iterations = iterations
        mod.vertex_group = vg.name

        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = proxy_obj.evaluated_get(depsgraph)
        eval_mesh = bpy.data.meshes.new_from_object(eval_obj)

        try:
            eval_mesh.update()
            vert_acc = defaultdict(Vector)
            for p_idx in poly_indices:
                poly = eval_mesh.polygons[p_idx]
                area_n = poly.normal * max(poly.area, 1e-8)
                for v_idx in poly.vertices:
                    vert_acc[v_idx] += area_n

            # 按原网格空间坐标合并未焊接的 UV 缝法线
            co_groups = defaultdict(list)
            for v_idx in group_verts:
                co = orig_mesh.vertices[v_idx].co
                co_groups[(round(co.x, 5), round(co.y, 5), round(co.z, 5))].append(
                    v_idx
                )

            for v_list in co_groups.values():
                if len(v_list) > 1:
                    merged = sum((vert_acc[v] for v in v_list), Vector((0.0, 0.0, 0.0)))
                    for v in v_list:
                        vert_acc[v] = merged.copy()

            result = {}
            for v_idx in group_verts:
                n = vert_acc[v_idx]
                if n.length_squared > 1e-12:
                    result[v_idx] = n.normalized()
                else:
                    result[v_idx] = Vector(eval_mesh.vertices[v_idx].normal)
            return result
        finally:
            bpy.data.meshes.remove(eval_mesh)
    finally:
        bpy.data.objects.remove(proxy_obj, do_unlink=True)
        bpy.data.meshes.remove(proxy_mesh)


def apply_face_ellipsoid_blend(orig_obj, face_vert_normals, blend=0.65):
    """对头部/脸部顶点叠加坡度平滑的椭球法线（脖子保持平滑圆柱法线）"""
    if not face_vert_normals:
        return face_vert_normals

    mesh = orig_obj.data
    head_z = get_head_bone_local_z(orig_obj)

    target_verts = [
        v_idx
        for v_idx in face_vert_normals
        if head_z is None or mesh.vertices[v_idx].co.z >= head_z - 0.02
    ]
    if not target_verts:
        return face_vert_normals

    coords = [mesh.vertices[v].co for v in target_verts]
    min_co = Vector(
        (min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords))
    )
    max_co = Vector(
        (max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords))
    )
    center = (min_co + max_co) * 0.5
    half = (max_co - min_co) * 0.5

    rx = max(half.x, 1e-4)
    ry = max(half.y, 1e-4)
    rz = max(half.z * 1.25, 1e-4)  # 垂直略拉长，额头与脸颊过渡更平顺

    out = dict(face_vert_normals)
    for v_idx in target_verts:
        d = mesh.vertices[v_idx].co - center
        ellip = Vector((d.x / rx, d.y / ry, d.z / rz))
        if ellip.length_squared <= 1e-12:
            continue
        n_sphere = ellip.normalized()
        n_proxy = face_vert_normals[v_idx]

        # 软过渡权重：靠近颈部边界渐弱 + 防止口腔/鼻孔内壁法线翻转
        height_fade = 1.0
        if head_z is not None:
            height_fade = max(
                0.0, min(1.0, (mesh.vertices[v_idx].co.z - (head_z - 0.02)) / 0.05)
            )
        local_w = blend * height_fade * max(0.0, n_proxy.dot(n_sphere))

        n_final = n_proxy.lerp(n_sphere, local_w)
        if n_final.length_squared > 1e-12:
            out[v_idx] = n_final.normalized()

    return out


def repair_skin_normals(obj):
    mesh = obj.data
    mesh.update()
    if not mesh.polygons:
        return

    if hasattr(mesh, "corner_normals"):
        loop_normals = [tuple(cn.vector) for cn in mesh.corner_normals]
    else:
        mesh.calc_normals_split()
        loop_normals = [tuple(l.normal) for l in mesh.loops]

    obj_name_low = obj.name.lower()
    groups = {"face_skin": [], "body_skin": [], "body_mixed": []}

    for p_idx, poly in enumerate(mesh.polygons):
        mat_name_low = ""
        if (
            0 <= poly.material_index < len(mesh.materials)
            and mesh.materials[poly.material_index]
        ):
            mat_name_low = mesh.materials[poly.material_index].name.lower()
        kind = classify_poly_surface(obj_name_low, mat_name_low)
        if kind in groups:
            groups[kind].append(p_idx)

    if not any(groups.values()):
        return

    loops = mesh.loops

    # 1. 脸部皮肤：强代理平滑 + 头部椭球法线混合
    if groups["face_skin"]:
        face_vn = compute_proxy_smooth_normals(obj, groups["face_skin"], iterations=16)
        face_vn = apply_face_ellipsoid_blend(obj, face_vn, blend=0.65)
        for p_idx in groups["face_skin"]:
            poly = mesh.polygons[p_idx]
            poly.use_smooth = True
            for l_idx in poly.loop_indices:
                loop_normals[l_idx] = tuple(face_vn[loops[l_idx].vertex_index])

    # 2. 纯身体皮肤：中度代理平滑
    if groups["body_skin"]:
        skin_vn = compute_proxy_smooth_normals(obj, groups["body_skin"], iterations=12)
        for p_idx in groups["body_skin"]:
            poly = mesh.polygons[p_idx]
            poly.use_smooth = True
            for l_idx in poly.loop_indices:
                loop_normals[l_idx] = tuple(skin_vn[loops[l_idx].vertex_index])

    # 3. 身体+衣服混合网格（bdy）：仅平滑 <45° 曲面，保留衣领/饰品硬折痕
    if groups["body_mixed"]:
        mixed_vn = compute_proxy_smooth_normals(obj, groups["body_mixed"], iterations=5)
        cos_crease = math.cos(math.radians(55.0))
        for p_idx in groups["body_mixed"]:
            poly = mesh.polygons[p_idx]
            p_no = poly.normal
            for l_idx in poly.loop_indices:
                vn = mixed_vn[loops[l_idx].vertex_index]
                if p_no.dot(vn) >= cos_crease:
                    poly.use_smooth = True
                    loop_normals[l_idx] = tuple(vn)

    if hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True
    mesh.normals_split_custom_set(loop_normals)
    mesh.update()
    print(
        f"   ✨ [{obj.name}] 法线重构完成: "
        f"脸部={len(groups['face_skin'])}面, 纯皮肤={len(groups['body_skin'])}面, 身体混合={len(groups['body_mixed'])}面"
    )


def push_vertices_along_normals(obj, strength=0.0004):
    """安全外扩顶点消除跨网格 Z-Fighting（兼容 Shape Keys，且保留修复后的法线）"""
    mesh = obj.data
    if hasattr(mesh, "corner_normals"):
        exact_normals = [tuple(cn.vector) for cn in mesh.corner_normals]
    else:
        mesh.calc_normals_split()
        exact_normals = [tuple(l.normal) for l in mesh.loops]

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
        basis = mesh.shape_keys.key_blocks[0]
        for i, kb_vert in enumerate(basis.data):
            kb_vert.co += vert_dirs[i] * strength
        mesh.update()
    else:
        for i, vert in enumerate(mesh.vertices):
            vert.co += vert_dirs[i] * strength
        mesh.update()

    if hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True
    mesh.normals_split_custom_set(exact_normals)
    mesh.update()


def run():
    print(">>> [步骤 0] 无损法线保护 + 皮肤代理法线重构 + 抗卡模处理...")

    GARBAGE_MESH_KEYWORDS = ["shadow", "dummy", "mmd_shadow", "mmd_dummy"]
    for obj in list(bpy.data.objects):
        if obj.type == "MESH":
            if any(kw in obj.name.lower() for kw in GARBAGE_MESH_KEYWORDS):
                print(f"   🧹 清理冗余阴影/Dummy网格: [{obj.name}]")
                bpy.data.objects.remove(obj, do_unlink=True)

    for obj in list(bpy.data.objects):
        if obj.type != "MESH" or not obj.data:
            continue

        try:
            if not obj.data.has_custom_normals:
                for poly in obj.data.polygons:
                    poly.use_smooth = True
        except Exception:
            pass

        if obj.data.color_attributes:
            try:
                while obj.data.color_attributes:
                    obj.data.color_attributes.remove(obj.data.color_attributes[0])
            except Exception:
                pass

        kd, orig_loop_normals = None, None
        try:
            kd, orig_loop_normals = snapshot_custom_normals(obj.data)
        except Exception as e:
            print(f"   ⚠️ 网格 [{obj.name}] 法线备份跳过: {e}")

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

        if kd is not None and orig_loop_normals:
            try:
                restore_custom_normals(obj.data, kd, orig_loop_normals)
            except Exception as e:
                print(f"   ⚠️ 网格 [{obj.name}] 法线还原跳过: {e}")

        # 重构皮肤与脸部平滑法线
        try:
            bpy.context.view_layer.objects.active = obj
            repair_skin_normals(obj)
        except Exception as e:
            print(f"   ⚠️ 网格 [{obj.name}] 皮肤法线重构跳过: {e}")

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
            except Exception as e:
                print(f"   ⚠️ 衣服网格 [{obj.name}] 微推失败: {e}")

    print("✅ [步骤 0] 皮肤法线重构与抗卡模处理完成！")
