import math
from collections import defaultdict

import bmesh
import bpy
from mathutils import Vector, kdtree

from step0_mat_map import classify_surface_for_normals, extract_material_base_image
from step0_springbone import snapshot_mmd_physics_to_armature


def snapshot_custom_normals(mesh):
    if hasattr(mesh, "corner_normals"):
        loop_normals = [Vector(cn.vector) for cn in mesh.corner_normals]
    else:
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


def get_head_bone_local_z(obj):
    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if not armature:
        return None
    for bone in armature.data.bones:
        b_low = bone.name.lower()
        if "head" in b_low or "頭" in bone.name or "头" in bone.name:
            world_pos = armature.matrix_world @ bone.head_local
            local_pos = obj.matrix_world.inverted() @ world_pos
            return local_pos.z
    return None


def compute_proxy_smooth_normals(orig_obj, poly_indices, iterations):
    orig_mesh = orig_obj.data
    poly_set = set(poly_indices)

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
        if len(edge.link_faces) == 1 or len(in_group_faces) < len(edge.link_faces):
            pinned_verts.add(edge.verts[0].index)
            pinned_verts.add(edge.verts[1].index)
    bm.free()

    proxy_mesh = orig_mesh.copy()
    proxy_obj = bpy.data.objects.new("__tmp_norm_proxy__", proxy_mesh)
    bpy.context.scene.collection.objects.link(proxy_obj)

    try:
        if proxy_obj.data.shape_keys:
            for kb in list(proxy_obj.data.shape_keys.key_blocks)[::-1]:
                proxy_obj.shape_key_remove(kb)

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

        vg = proxy_obj.vertex_groups.new(name="__smooth_mask__")
        interior_verts = [v for v in group_verts if v not in pinned_verts]
        if interior_verts:
            vg.add(interior_verts, 1.0, "REPLACE")
        if pinned_verts:
            vg.add(list(pinned_verts), 0.0, "REPLACE")

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
                p_no = poly.normal
                if (
                    not all(math.isfinite(x) for x in p_no)
                    or p_no.length_squared < 1e-12
                ):
                    continue
                area_n = p_no * max(poly.area, 1e-8)
                for v_idx in poly.vertices:
                    vert_acc[v_idx] += area_n

            co_groups = defaultdict(list)
            for v_idx in group_verts:
                co = orig_mesh.vertices[v_idx].co
                co_groups[(round(co.x, 5), round(co.y, 5), round(co.z, 5))].append(
                    v_idx
                )

            for v_list in co_groups.values():
                if len(v_list) > 1:
                    orig_norms = {v: vert_acc[v].copy() for v in v_list}
                    for v in v_list:
                        base_n = orig_norms[v]
                        if base_n.length_squared <= 1e-12:
                            continue
                        merged = base_n.copy()
                        for other_v in v_list:
                            if other_v == v:
                                continue
                            on = orig_norms[other_v]
                            if (
                                on.length_squared > 1e-12
                                and base_n.normalized().dot(on.normalized()) > 0.2
                            ):
                                merged += on
                        vert_acc[v] = merged

            result = {}
            for v_idx in group_verts:
                n = vert_acc[v_idx]
                if all(math.isfinite(x) for x in n) and n.length_squared > 1e-12:
                    result[v_idx] = n.normalized()
                else:
                    orig_n = Vector(orig_mesh.vertices[v_idx].normal)
                    result[v_idx] = (
                        orig_n.normalized()
                        if orig_n.length_squared > 1e-12
                        else Vector((0.0, 0.0, 1.0))
                    )
            return result
        finally:
            bpy.data.meshes.remove(eval_mesh)
    finally:
        bpy.data.objects.remove(proxy_obj, do_unlink=True)
        bpy.data.meshes.remove(proxy_mesh)


def apply_face_ellipsoid_blend(orig_obj, face_vert_normals, blend=0.65):
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
    rz = max(half.z * 1.25, 1e-4)

    out = dict(face_vert_normals)
    for v_idx in target_verts:
        d = mesh.vertices[v_idx].co - center
        ellip = Vector((d.x / rx, d.y / ry, d.z / rz))
        if ellip.length_squared <= 1e-12:
            continue
        n_sphere = ellip.normalized()
        n_proxy = face_vert_normals[v_idx]

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

    slot_kinds = []
    for mat in mesh.materials:
        if not mat:
            slot_kinds.append("other")
            continue
        b_img = extract_material_base_image(mat)
        slot_kinds.append(
            classify_surface_for_normals(
                obj.name, mat.name, b_img.name if b_img else ""
            )
        )

    groups = {"face_skin": [], "body_skin": [], "body_mixed": []}
    for p_idx, poly in enumerate(mesh.polygons):
        kind = (
            slot_kinds[poly.material_index]
            if 0 <= poly.material_index < len(slot_kinds)
            else "other"
        )
        if kind in groups:
            groups[kind].append(p_idx)

    if not any(groups.values()):
        return

    loops = mesh.loops
    cos_flip_guard = math.cos(math.radians(80.0))

    def _safe_write_group(poly_list, vn_map, min_dot):
        skipped_flip = 0
        for p_idx in poly_list:
            poly = mesh.polygons[p_idx]
            p_no = poly.normal
            if p_no.length_squared < 1e-12:
                continue
            cand = []
            valid = True
            for l_idx in poly.loop_indices:
                vn = vn_map.get(loops[l_idx].vertex_index)
                if (
                    vn is None
                    or not all(math.isfinite(x) for x in vn)
                    or vn.length_squared < 1e-12
                    or p_no.dot(vn) < min_dot
                ):
                    valid = False
                    break
                cand.append((l_idx, tuple(vn.normalized())))
            if valid:
                poly.use_smooth = True
                for l_idx, n_tup in cand:
                    loop_normals[l_idx] = n_tup
            else:
                skipped_flip += 1
        return skipped_flip

    if groups["face_skin"]:
        face_vn = compute_proxy_smooth_normals(obj, groups["face_skin"], iterations=16)
        face_vn = apply_face_ellipsoid_blend(obj, face_vn, blend=0.65)
        _safe_write_group(groups["face_skin"], face_vn, cos_flip_guard)

    if groups["body_skin"]:
        skin_vn = compute_proxy_smooth_normals(obj, groups["body_skin"], iterations=8)
        _safe_write_group(groups["body_skin"], skin_vn, cos_flip_guard)

    if groups["body_mixed"]:
        mixed_vn = compute_proxy_smooth_normals(obj, groups["body_mixed"], iterations=5)
        cos_crease = math.cos(math.radians(55.0))
        _safe_write_group(groups["body_mixed"], mixed_vn, cos_crease)

    if hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True
    mesh.normals_split_custom_set(loop_normals)
    mesh.update()
    print(
        f"   ✨ [{obj.name}] 法线重构完成: "
        f"脸部={len(groups['face_skin'])}面, 纯皮肤={len(groups['body_skin'])}面, 身体混合={len(groups['body_mixed'])}面"
    )


def separate_coplanar_material_overlays(obj, offset=0.00025):
    """检测同一网格上完全重合的材质面，按叠加层数递增微推(+0.25mm, +0.5mm...)彻底消除 Z-fighting 与 EEVEE 光追自阴影变黑"""
    mesh = obj.data
    if not mesh.polygons or len(mesh.materials) < 2:
        return

    if hasattr(mesh, "corner_normals"):
        exact_normals = [tuple(cn.vector) for cn in mesh.corner_normals]
    else:
        mesh.calc_normals_split()
        exact_normals = [tuple(l.normal) for l in mesh.loops]

    slot_centers = defaultdict(set)
    slot_verts = defaultdict(set)
    slot_vert_dirs = defaultdict(lambda: defaultdict(Vector))

    for poly in mesh.polygons:
        s_idx = poly.material_index
        c = poly.center
        slot_centers[s_idx].add((round(c.x, 4), round(c.y, 4), round(c.z, 4)))
        p_no = poly.normal
        valid_no = all(math.isfinite(x) for x in p_no) and p_no.length_squared > 1e-12
        for v_idx in poly.vertices:
            slot_verts[s_idx].add(v_idx)
            if valid_no:
                slot_vert_dirs[s_idx][v_idx] += p_no

    slots = sorted(slot_centers.keys())
    pushed_slots = {}
    layer_count = defaultdict(int)
    for b_pos, s_b in enumerate(slots):
        c_b = slot_centers[s_b]
        if len(c_b) < 20:
            continue
        for s_a in slots[:b_pos]:
            c_a = slot_centers[s_a]
            if len(c_a) < 20:
                continue
            overlap = len(c_a & c_b)
            if overlap >= 20 and overlap >= 0.5 * min(len(c_a), len(c_b)):
                root_s = pushed_slots[s_a][0] if s_a in pushed_slots else s_a
                layer_count[root_s] += 1
                pushed_slots[s_b] = (root_s, layer_count[root_s])
                break

    if not pushed_slots:
        return

    vert_deltas = {}
    separated_names = []
    for s_b, (s_root, layer_idx) in pushed_slots.items():
        exclusive_verts = set(slot_verts[s_b]) - set(slot_verts[s_root])
        for other_b, (other_root, other_layer) in pushed_slots.items():
            if other_root == s_root and other_layer < layer_idx:
                exclusive_verts -= slot_verts[other_b]
        if not exclusive_verts:
            continue
        dirs_b = slot_vert_dirs[s_b]
        step_offset = offset * layer_idx
        cnt = 0
        for v_idx in exclusive_verts:
            if v_idx in vert_deltas:
                continue
            d = dirs_b.get(v_idx, Vector((0.0, 0.0, 0.0)))
            if d.length_squared > 1e-12:
                vert_deltas[v_idx] = d.normalized() * step_offset
                cnt += 1
        if cnt:
            mat_a = (
                mesh.materials[s_root].name if mesh.materials[s_root] else str(s_root)
            )
            mat_b = mesh.materials[s_b].name if mesh.materials[s_b] else str(s_b)
            separated_names.append(f"{mat_b}(覆盖{mat_a} L{layer_idx}, {cnt}点)")

    if not vert_deltas:
        return

    for v_idx, delta in vert_deltas.items():
        mesh.vertices[v_idx].co += delta

    if mesh.shape_keys and len(mesh.shape_keys.key_blocks) > 0:
        for kb in mesh.shape_keys.key_blocks:
            for v_idx, delta in vert_deltas.items():
                kb.data[v_idx].co += delta

    mesh.update()
    if hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True
    mesh.normals_split_custom_set(exact_normals)
    mesh.update()
    print(f"   🛡️ [{obj.name}] 已按层级分离重合材质层: {', '.join(separated_names)}")


def push_vertices_along_normals(obj, strength=0.0004):
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
        for kb in mesh.shape_keys.key_blocks:
            for i, kb_vert in enumerate(kb.data):
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


def is_mmd_physics_or_garbage(obj):
    if getattr(obj, "mmd_type", "NONE") in ("RIGID_BODY", "JOINT"):
        return True
    if obj.type == "EMPTY" and obj.name.lower() in ("joints", "rigidbodies"):
        return True
    if obj.parent and obj.parent.name.lower() in ("joints", "rigidbodies"):
        return True
    for col in obj.users_collection:
        if col.name.lower() in ("rigidbodies", "joints"):
            return True
    if obj.type == "MESH":
        name_low = obj.name.lower()
        if any(
            kw in name_low
            for kw in (
                "shadow",
                "dummy",
                "mmd_shadow",
                "mmd_dummy",
                "rigidbody",
                "mmd_rigid",
                "mmd_joint",
                "cs_rigid",
            )
        ):
            return True
    return False


def clear_mmd_armature_constraints():
    """解除 mmd_tools 生成的 _dummy_/_shadow_ 骨骼约束，防止步骤 0 依赖图刷新时刷屏循环依赖警告"""
    cleared = 0
    for arm in bpy.data.objects:
        if arm.type != "ARMATURE" or not arm.pose:
            continue
        for pb in arm.pose.bones:
            for c in list(pb.constraints):
                pb.constraints.remove(c)
                cleared += 1
            pb.location = (0.0, 0.0, 0.0)
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pb.rotation_euler = (0.0, 0.0, 0.0)
            pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
            pb.scale = (1.0, 1.0, 1.0)
    if cleared:
        print(f"   🔓 已解除 {cleared} 条 MMD 骨骼循环约束")


def run():
    print(">>> [步骤 0] 无损法线保护 + 皮肤代理法线重构 + 清理 mmd_tools 刚体/关节...")

    snapshot_mmd_physics_to_armature()
    clear_mmd_armature_constraints()

    removed_cnt = 0
    for obj in list(bpy.data.objects):
        if is_mmd_physics_or_garbage(obj):
            bpy.data.objects.remove(obj, do_unlink=True)
            removed_cnt += 1
    if removed_cnt:
        print(f"   🧹 已清理 {removed_cnt} 个冗余刚体/关节/Dummy对象")

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

        has_shape_keys = bool(
            obj.data.shape_keys and len(obj.data.shape_keys.key_blocks) > 1
        )

        if not has_shape_keys:
            kd, orig_loop_normals = None, None
            try:
                kd, orig_loop_normals = snapshot_custom_normals(obj.data)
            except Exception:
                pass
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
                except Exception:
                    pass

        try:
            bpy.context.view_layer.objects.active = obj
            repair_skin_normals(obj)
        except Exception as e:
            print(f"   ⚠️ 网格 [{obj.name}] 皮肤法线重构跳过: {e}")

        try:
            separate_coplanar_material_overlays(obj, offset=0.00025)
        except Exception as e:
            print(f"   ⚠️ 网格 [{obj.name}] 重合材质分离跳过: {e}")

        obj_name_lower = obj.name.lower()
        is_clothing = any(
            kw in obj_name_lower
            for kw in ["cloth", "wear", "dress", "costume", "jacket", "skirt"]
        )
        is_inner_skin = any(
            kw in obj_name_lower for kw in ["skin", "inner", "naked", "kao", "face"]
        )

        if is_clothing and not is_inner_skin:
            try:
                push_vertices_along_normals(obj, strength=0.0004)
            except Exception as e:
                print(f"   ⚠️ 衣服网格 [{obj.name}] 微推失败: {e}")

    print("✅ [步骤 0] 皮肤法线重构与清理完成！")
