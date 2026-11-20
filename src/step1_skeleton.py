import math
import re
import time

import bpy
import numpy as np
from mathutils import Vector

from step0_springbone import (
    apply_mmd_spring_snapshot_to_vrm,
    get_snapshot_spring_bone_names,
    snapshot_mmd_physics_to_armature,
)
from step1_bone_map import (
    BASE_BONE_RENAME_MAP,
    FLATTEN_CONTROL_BONES,
    GARBAGE_BONE_KEYWORDS,
    build_vrm_humanoid_mappings,
    is_physics_or_spring_bone,
    translate_non_ascii_bone_name,
)


def to_snake_case(name: str) -> str:
    return re.sub(r"([A-Z])", r"_\1", name).lower()


def is_ancestor(bone, maybe_ancestor):
    cur = bone.parent
    while cur:
        if cur == maybe_ancestor:
            return True
        cur = cur.parent
    return False


def get_bound_meshes(armature_obj):
    return [
        o
        for o in bpy.data.objects
        if o.type == "MESH"
        and o.data
        and (
            o.parent == armature_obj
            or any(
                m.type == "ARMATURE" and m.object == armature_obj for m in o.modifiers
            )
        )
    ]


def iter_spring_bone_refs(ext):
    """遍历 VRM 1.0 (spring_bone1) 与 VRM 0.x (secondary_animation) 中所有骨骼引用对象"""
    if not ext:
        return
    if hasattr(ext, "spring_bone1"):
        sb1 = ext.spring_bone1
        for sp in getattr(sb1, "springs", []):
            if hasattr(sp, "center") and hasattr(sp.center, "bone_name"):
                yield sp.center
            for j in getattr(sp, "joints", []):
                if hasattr(j, "node") and hasattr(j.node, "bone_name"):
                    yield j.node
        for col in getattr(sb1, "colliders", []):
            if hasattr(col, "node") and hasattr(col.node, "bone_name"):
                yield col.node
    if hasattr(ext, "vrm0") and hasattr(ext.vrm0, "secondary_animation"):
        sa = ext.vrm0.secondary_animation
        for bg in getattr(sa, "bone_groups", []):
            if hasattr(bg, "center") and hasattr(bg.center, "bone_name"):
                yield bg.center
            for b in getattr(bg, "bones", []):
                if hasattr(b, "bone_name"):
                    yield b
        for cg in getattr(sa, "collider_groups", []):
            if hasattr(cg, "node") and hasattr(cg.node, "bone_name"):
                yield cg.node


def collect_existing_spring_bone_names(armature_obj):
    ext = getattr(armature_obj.data, "vrm_addon_extension", None)
    names = {
        ref.bone_name
        for ref in iter_spring_bone_refs(ext)
        if getattr(ref, "bone_name", "")
    }
    names.update(get_snapshot_spring_bone_names(armature_obj))
    return names


def sync_spring_bone_rename(armature_obj, old_name, new_name):
    ext = getattr(armature_obj.data, "vrm_addon_extension", None)
    for ref in iter_spring_bone_refs(ext):
        if ref.bone_name == old_name:
            ref.bone_name = new_name


def collect_weighted_bone_names(armature_obj, bound_meshes=None):
    weighted = {}
    if bound_meshes is None:
        bound_meshes = get_bound_meshes(armature_obj)
    for obj in bound_meshes:
        if not obj.vertex_groups:
            continue
        idx_to_name = {vg.index: vg.name for vg in obj.vertex_groups}
        for v in obj.data.vertices:
            for g in v.groups:
                if g.weight > 0.0001 and g.group in idx_to_name:
                    bname = idx_to_name[g.group]
                    weighted[bname] = weighted.get(bname, 0) + 1
    return weighted


def find_first_bone(bones_dict, candidates):
    for c in candidates:
        if c in bones_dict:
            return bones_dict[c]
    return None


def resolve_torso_chain(edit_bones, hips_b, neck_or_head_b, arm_l_b, arm_r_b):
    if not hips_b or not neck_or_head_b:
        return {}

    chain = []
    cur = neck_or_head_b.parent
    while cur and cur != hips_b:
        chain.append(cur)
        cur = cur.parent
    if cur != hips_b:
        return {}
    chain.reverse()

    valid_torso = [
        b
        for b in chain
        if (not arm_l_b or b == arm_l_b or is_ancestor(arm_l_b, b))
        and (not arm_r_b or b == arm_r_b or is_ancestor(arm_r_b, b))
    ]
    if not valid_torso:
        valid_torso = chain

    res = {}
    if len(valid_torso) >= 1:
        res[valid_torso[0].name] = "Spine"
    if len(valid_torso) >= 2:
        res[valid_torso[1].name] = "Chest"
    if len(valid_torso) >= 3:
        res[valid_torso[-1].name] = "UpperChest"
    return res


def safe_rename_bone(
    armature_obj, bone, new_name, existing_names, bound_meshes=None, has_vrm_refs=True
):
    old_name = bone.name
    if old_name == new_name or new_name in existing_names:
        return None
    bone.name = new_name
    final_name = bone.name
    existing_names.discard(old_name)
    existing_names.add(final_name)
    if bound_meshes is None:
        bound_meshes = get_bound_meshes(armature_obj)
    for obj in bound_meshes:
        if not obj.vertex_groups:
            continue
        if old_name in obj.vertex_groups and final_name not in obj.vertex_groups:
            obj.vertex_groups[old_name].name = final_name
    if has_vrm_refs:
        sync_spring_bone_rename(armature_obj, old_name, final_name)
    return final_name


def validate_and_assign_vrm_humanoid(armature_obj, skip_toes=False):
    ext = getattr(armature_obj.data, "vrm_addon_extension", None)
    if not ext:
        return {}

    bones = armature_obj.data.bones
    map_vrm0, map_vrm1 = build_vrm_humanoid_mappings()

    resolved = {}
    for key, cands in map_vrm1.items():
        if skip_toes and key in ("leftToes", "rightToes"):
            continue
        for c in cands:
            if c in bones:
                resolved[key] = c
                break

    hips = bones.get(resolved.get("hips", ""))
    spine = bones.get(resolved.get("spine", ""))
    chest = bones.get(resolved.get("chest", ""))
    upper_chest = bones.get(resolved.get("upperChest", ""))
    neck = bones.get(resolved.get("neck", ""))
    head = bones.get(resolved.get("head", ""))
    arm_l = bones.get(resolved.get("leftUpperArm", ""))
    arm_r = bones.get(resolved.get("rightUpperArm", ""))

    if upper_chest:
        ok = (
            chest is not None
            and is_ancestor(upper_chest, chest)
            and (neck is None or is_ancestor(neck, upper_chest))
            and (head is None or is_ancestor(head, upper_chest))
            and (arm_l is None or is_ancestor(arm_l, upper_chest))
            and (arm_r is None or is_ancestor(arm_r, upper_chest))
        )
        if not ok:
            resolved.pop("upperChest", None)
            upper_chest = None

    top_torso = upper_chest or chest or spine or hips
    for side, uarm in (("left", arm_l), ("right", arm_r)):
        sh = bones.get(resolved.get(f"{side}Shoulder", ""))
        if sh and (
            not top_torso
            or not is_ancestor(sh, top_torso)
            or not uarm
            or not is_ancestor(uarm, sh)
        ):
            resolved.pop(f"{side}Shoulder", None)
        foot = bones.get(resolved.get(f"{side}Foot", ""))
        toes = bones.get(resolved.get(f"{side}Toes", ""))
        if toes and (not foot or not is_ancestor(toes, foot)):
            resolved.pop(f"{side}Toes", None)

    for eye_key in ("leftEye", "rightEye"):
        eye = bones.get(resolved.get(eye_key, ""))
        if eye and (not head or not is_ancestor(eye, head)):
            resolved.pop(eye_key, None)

    if hasattr(ext, "vrm0") and hasattr(ext.vrm0, "humanoid"):
        for hb in ext.vrm0.humanoid.human_bones:
            hb.node.bone_name = ""
            if hb.bone in resolved:
                hb.node.bone_name = resolved[hb.bone]
            elif hb.bone == "leftThumbProximal" and "leftThumbMetacarpal" in resolved:
                hb.node.bone_name = resolved["leftThumbMetacarpal"]
            elif hb.bone == "leftThumbIntermediate" and "leftThumbProximal" in resolved:
                hb.node.bone_name = resolved["leftThumbProximal"]
            elif hb.bone == "rightThumbProximal" and "rightThumbMetacarpal" in resolved:
                hb.node.bone_name = resolved["rightThumbMetacarpal"]
            elif (
                hb.bone == "rightThumbIntermediate" and "rightThumbProximal" in resolved
            ):
                hb.node.bone_name = resolved["rightThumbProximal"]

    if hasattr(ext, "vrm1") and hasattr(ext.vrm1, "humanoid"):
        h_bones = ext.vrm1.humanoid.human_bones
        for attr_name in map_vrm1:
            snake_attr = to_snake_case(attr_name)
            target_attr = (
                attr_name
                if hasattr(h_bones, attr_name)
                else (snake_attr if hasattr(h_bones, snake_attr) else None)
            )
            if not target_attr:
                continue
            hb_item = getattr(h_bones, target_attr)
            if hasattr(hb_item, "node"):
                hb_item.node.bone_name = resolved.get(attr_name, "")

    return resolved


def bone_depth(b):
    d = 0
    cur = b.parent
    while cur:
        d += 1
        cur = cur.parent
    return d


def merge_bone_pairs_to_parent(armature_obj, child_to_parent, bound_meshes=None):
    if not child_to_parent:
        return 0
    if bound_meshes is None:
        bound_meshes = get_bound_meshes(armature_obj)
    for mesh_obj in bound_meshes:
        vgs = mesh_obj.vertex_groups
        if not vgs:
            continue
        src_idx_to_dst = {}
        for src_name, dst_name in child_to_parent.items():
            if src_name in vgs:
                dst_vg = vgs.get(dst_name) or vgs.new(name=dst_name)
                src_idx_to_dst[vgs[src_name].index] = dst_vg
        if not src_idx_to_dst:
            continue
        for v in mesh_obj.data.vertices:
            for g in v.groups:
                dst_vg = src_idx_to_dst.get(g.group)
                if dst_vg is not None and g.weight > 0.0:
                    dst_vg.add([v.index], g.weight, "ADD")
        for src_name in child_to_parent:
            if src_name in vgs:
                vgs.remove(vgs[src_name])

    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode="EDIT")
    eb = armature_obj.data.edit_bones
    removed = 0
    for bname, dst_name in child_to_parent.items():
        if bname in eb:
            target_parent = eb.get(dst_name) or eb[bname].parent
            for ch in list(eb[bname].children):
                ch.parent = target_parent
            eb.remove(eb[bname])
            removed += 1
    bpy.ops.object.mode_set(mode="OBJECT")
    return removed


def merge_excess_bones_to_limit(
    armature_obj, protected_names, max_bones=240, bound_meshes=None
):
    if max_bones <= 0 or len(armature_obj.data.bones) <= max_bones:
        return 0, {}

    # 在内存中一次性推演全部可合并链条，最后只切换 1 次 Edit 模式和扫描 1 次顶点
    parent_of = {
        b.name: (b.parent.name if b.parent else None) for b in armature_obj.data.bones
    }
    child_cnt = {b.name: len(b.children) for b in armature_obj.data.bones}
    depth_of = {b.name: bone_depth(b) for b in armature_obj.data.bones}

    total_count = len(parent_of)
    direct_merge = {}

    while total_count > max_bones:
        excess = total_count - max_bones
        leaves = [
            bname
            for bname, cnt in child_cnt.items()
            if cnt == 0
            and parent_of.get(bname) is not None
            and bname not in protected_names
        ]
        if not leaves:
            break

        def leaf_priority(bname):
            low = bname.lower()
            if any(k in low for k in ("twist", "bip001_", "aux", "cancel", "prop")):
                tier = 0
            elif is_physics_or_spring_bone(bname):
                tier = 2
            else:
                tier = 1
            return (tier, -depth_of[bname])

        leaves.sort(key=leaf_priority)
        batch = leaves[:excess]
        for bname in batch:
            p = parent_of[bname]
            direct_merge[bname] = p
            child_cnt.pop(bname, None)
            if p in child_cnt:
                child_cnt[p] = max(0, child_cnt[p] - 1)
            total_count -= 1

    if not direct_merge:
        return 0, {}

    child_to_surviving = {}
    for bname in direct_merge:
        cur = direct_merge[bname]
        while cur in direct_merge:
            cur = direct_merge[cur]
        child_to_surviving[bname] = cur

    merged_total = merge_bone_pairs_to_parent(
        armature_obj, child_to_surviving, bound_meshes=bound_meshes
    )
    return merged_total, child_to_surviving


def ground_model_to_z0(armature_obj, bound_meshes=None):
    if bound_meshes is None:
        bound_meshes = get_bound_meshes(armature_obj)
    if not bound_meshes:
        return 0.0

    min_z = float("inf")
    for o in bound_meshes:
        n = len(o.data.vertices)
        if n == 0:
            continue
        co = np.empty(n * 3, dtype=np.float32)
        o.data.vertices.foreach_get("co", co)
        pts = co.reshape(-1, 3)
        mat = np.array(o.matrix_world, dtype=np.float32)
        z_vals = pts @ mat[2, :3] + mat[2, 3]
        m = float(np.min(z_vals))
        if m < min_z:
            min_z = m

    if min_z == float("inf"):
        return 0.0
    dz = -min_z
    if abs(dz) < 0.001:
        return 0.0

    world_shift = Vector((0.0, 0.0, dz))
    for o in bound_meshes:
        n = len(o.data.vertices)
        if n == 0:
            continue
        local_shift = o.matrix_world.inverted().to_3x3() @ world_shift
        shift_arr = np.array(
            [local_shift.x, local_shift.y, local_shift.z], dtype=np.float32
        )

        co = np.empty(n * 3, dtype=np.float32)
        o.data.vertices.foreach_get("co", co)
        co.reshape(-1, 3)[:] += shift_arr
        o.data.vertices.foreach_set("co", co)

        if o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks:
                k_co = np.empty(n * 3, dtype=np.float32)
                kb.data.foreach_get("co", k_co)
                k_co.reshape(-1, 3)[:] += shift_arr
                kb.data.foreach_set("co", k_co)
        o.data.update()

    arm_shift = armature_obj.matrix_world.inverted().to_3x3() @ world_shift
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode="EDIT")
    for eb in armature_obj.data.edit_bones:
        eb.head += arm_shift
        eb.tail += arm_shift
    bpy.ops.object.mode_set(mode="OBJECT")
    return dz


def apply_high_heel_retarget_fix(armature_obj, bound_meshes=None):
    """基于真实脚踝网格截面与骨骼几何动态计算高跟/小腿倾角校准，无硬编码比例。"""
    if bound_meshes is None:
        bound_meshes = [o for o in get_bound_meshes(armature_obj) if o.vertex_groups]
    else:
        bound_meshes = [o for o in bound_meshes if o.vertex_groups]
    arm_inv = armature_obj.matrix_world.inverted()

    ankle_y_bounds = {}
    for side in ("L", "R"):
        foot_b = armature_obj.data.bones.get(f"Foot{side}")
        if not foot_b:
            continue
        fz = foot_b.head_local.z
        ys = []
        target_names = {f"Foot{side}", f"LowerLeg{side}"}
        for o in bound_meshes:
            vg_indices = {
                o.vertex_groups[n].index for n in target_names if n in o.vertex_groups
            }
            if not vg_indices:
                continue
            to_arm = arm_inv @ o.matrix_world
            for v in o.data.vertices:
                if not any(g.group in vg_indices and g.weight > 0.1 for g in v.groups):
                    continue
                co_arm = to_arm @ v.co
                if abs(co_arm.z - fz) <= 0.025:
                    ys.append(co_arm.y)
        if ys:
            y_min, y_max = min(ys), max(ys)
            margin = (y_max - y_min) * 0.20
            ankle_y_bounds[side] = (y_min + margin, y_max - margin)

    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode="EDIT")
    eb = armature_obj.data.edit_bones
    for side in ("L", "R"):
        knee = eb.get(f"LowerLeg{side}")
        foot = eb.get(f"Foot{side}")
        if not knee or not foot or side not in ankle_y_bounds:
            continue
        dz = max(1e-4, knee.head.z - foot.head.z)
        shin_tilt_deg = math.degrees(math.atan2(abs(knee.head.y - foot.head.y), dz))
        if shin_tilt_deg <= 4.0:
            continue
        safe_min_y, safe_max_y = ankle_y_bounds[side]
        new_y = max(safe_min_y, min(safe_max_y, knee.head.y))
        delta_y = new_y - foot.head.y
        if abs(delta_y) > 1e-4:
            foot.head.y += delta_y
            foot.tail.y += delta_y
            print(
                f"   📐 [脚踝动态校准 {side}] 小腿倾角={shin_tilt_deg:.1f}°, "
                f"截面安全范围=[{safe_min_y:.3f}, {safe_max_y:.3f}], delta_y={delta_y:+.4f}m"
            )
    bpy.ops.object.mode_set(mode="OBJECT")

    to_merge = {}
    for side in ("L", "R"):
        toe_b = armature_obj.data.bones.get(f"Toes{side}")
        foot_b = armature_obj.data.bones.get(f"Foot{side}")
        if not toe_b or not foot_b or not toe_b.parent:
            continue
        dz = foot_b.head_local.z - toe_b.head_local.z
        horiz = math.hypot(
            toe_b.head_local.x - foot_b.head_local.x,
            toe_b.head_local.y - foot_b.head_local.y,
        )
        slope_deg = math.degrees(math.atan2(dz, max(1e-4, horiz)))
        if slope_deg > 30.0:
            to_merge[toe_b.name] = foot_b.name
            print(
                f"   👠 [高跟坡度检测 {side}] Foot->Toes 俯角={slope_deg:.1f}° (>30°)，自动合并 {toe_b.name}->{foot_b.name}"
            )

    merge_bone_pairs_to_parent(armature_obj, to_merge, bound_meshes=bound_meshes)
    return len(to_merge) > 0, to_merge


def run(
    jp_model_name,
    en_model_name,
    max_bones=240,
    ground_to_zero=True,
    fix_high_heel_rig=True,
):
    t0 = time.perf_counter()
    print(">>> [步骤 1] 规整 MMD 骨骼命名、保护弹簧骨与校验躯干/脚踝链路...")
    armature_obj = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if armature_obj:
        # 若跳过了步骤 0 直接调用步骤 1，先拍取 MMD 物理快照
        snapshot_mmd_physics_to_armature(armature_obj, overwrite=False)

        bound_meshes = get_bound_meshes(armature_obj)
        weighted_bones = collect_weighted_bone_names(
            armature_obj, bound_meshes=bound_meshes
        )
        existing_spring_bones = collect_existing_spring_bone_names(armature_obj)

        ext = getattr(armature_obj.data, "vrm_addon_extension", None)
        has_vrm_refs = bool(
            ext
            and (
                (
                    hasattr(ext, "spring_bone1")
                    and len(getattr(ext.spring_bone1, "springs", [])) > 0
                )
                or (
                    hasattr(ext, "vrm0")
                    and len(getattr(ext.vrm0.secondary_animation, "bone_groups", []))
                    > 0
                )
            )
        )

        mmd_name_e_map = {}
        for pb in armature_obj.pose.bones:
            mmd_b = getattr(pb, "mmd_bone", None)
            if mmd_b and getattr(mmd_b, "name_e", ""):
                mmd_name_e_map[pb.name] = mmd_b.name_e
            for c in list(pb.constraints):
                pb.constraints.remove(c)
            pb.location = (0.0, 0.0, 0.0)
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pb.rotation_euler = (0.0, 0.0, 0.0)
            pb.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
            pb.scale = (1.0, 1.0, 1.0)

        bpy.context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="EDIT")
        eb = armature_obj.data.edit_bones

        use_leg_l_d = "左足D" in eb and weighted_bones.get(
            "左足D", 0
        ) >= weighted_bones.get("左足", 0)
        use_leg_r_d = "右足D" in eb and weighted_bones.get(
            "右足D", 0
        ) >= weighted_bones.get("右足", 0)
        use_arm_l_d = "左腕D" in eb and weighted_bones.get(
            "左腕D", 0
        ) >= weighted_bones.get("左腕", 0)
        use_arm_r_d = "右腕D" in eb and weighted_bones.get(
            "右腕D", 0
        ) >= weighted_bones.get("右腕", 0)

        to_remove = {
            b.name
            for b in eb
            if (
                any(kw in b.name for kw in GARBAGE_BONE_KEYWORDS)
                or b.name.endswith("IK")
            )
            and b.name not in weighted_bones
            and b.name not in existing_spring_bones
        }
        if use_leg_l_d:
            to_remove.update(
                d
                for d in ("左足", "左ひざ", "左足首")
                if d in eb
                and d not in weighted_bones
                and d not in existing_spring_bones
            )
        if use_leg_r_d:
            to_remove.update(
                d
                for d in ("右足", "右ひざ", "右足首")
                if d in eb
                and d not in weighted_bones
                and d not in existing_spring_bones
            )
        to_remove.update(
            c
            for c in FLATTEN_CONTROL_BONES
            if c in eb and c not in weighted_bones and c not in existing_spring_bones
        )

        for bn in list(to_remove):
            if bn in eb:
                p = eb[bn].parent
                for ch in list(eb[bn].children):
                    ch.parent = p
                eb.remove(eb[bn])

        root_b = find_first_bone(
            eb, ("Root", "全ての親", "全ての亲", "Position", "ParentNode")
        )
        hips_b = find_first_bone(
            eb, ("Hips", "Hip", "pelvis", "Bip001 Pelvis", "腰", "下半身", "LowerBody")
        )
        spine_b = find_first_bone(
            eb, ("Spine", "上半身", "UpperBody", "spine_01", "Bip001 Spine")
        )
        neck_b = find_first_bone(eb, ("Neck", "首", "脖子", "neck_01", "Bip001 Neck"))
        head_b = find_first_bone(eb, ("Head", "頭", "头", "head", "Bip001 Head"))
        arm_l_b = find_first_bone(
            eb,
            ("左腕D",)
            if use_arm_l_d
            else ("UpperArmL", "Arm_L", "左腕", "upperarm_l", "Bip001 L UpperArm"),
        )
        arm_r_b = find_first_bone(
            eb,
            ("右腕D",)
            if use_arm_r_d
            else ("UpperArmR", "Arm_R", "右腕", "upperarm_r", "Bip001 R UpperArm"),
        )

        if hips_b and root_b and hips_b != root_b:
            hips_b.parent = root_b
        if hips_b and spine_b and not is_ancestor(spine_b, hips_b):
            spine_b.parent = hips_b

        rename_map = dict(BASE_BONE_RENAME_MAP)
        if hips_b:
            rename_map[hips_b.name] = "Hips"
        rename_map.update(
            resolve_torso_chain(eb, hips_b, neck_b or head_b, arm_l_b, arm_r_b)
        )
        rename_map.update(
            {"左腕D": "UpperArmL", "左ひじD": "LowerArmL", "左手首D": "HandL"}
            if use_arm_l_d
            else {"左腕": "UpperArmL", "左ひじ": "LowerArmL", "左手首": "HandL"}
        )
        rename_map.update(
            {"右腕D": "UpperArmR", "右ひじD": "LowerArmR", "右手首D": "HandR"}
            if use_arm_r_d
            else {"右腕": "UpperArmR", "右ひじ": "LowerArmR", "右手首": "HandR"}
        )
        rename_map.update(
            {"左足D": "UpperLegL", "左ひざD": "LowerLegL", "左足首D": "FootL"}
            if use_leg_l_d
            else {"左足": "UpperLegL", "左ひざ": "LowerLegL", "左足首": "FootL"}
        )
        rename_map.update(
            {"右足D": "UpperLegR", "右ひざD": "LowerLegR", "右足首D": "FootR"}
            if use_leg_r_d
            else {"右足": "UpperLegR", "右ひざ": "LowerLegR", "右足首": "FootR"}
        )

        foot_l_b = find_first_bone(
            eb, ("FootL", "左足首D" if use_leg_l_d else "左足首")
        )
        foot_r_b = find_first_bone(
            eb, ("FootR", "右足首D" if use_leg_r_d else "右足首")
        )
        for cand in ("左足先EX", "左つま先D", "左足先D", "左つま先", "左足先"):
            if cand in eb and (not foot_l_b or is_ancestor(eb[cand], foot_l_b)):
                rename_map[cand] = "ToesL"
                break
        for cand in ("右足先EX", "右つま先D", "右足先D", "右つま先", "右足先"):
            if cand in eb and (not foot_r_b or is_ancestor(eb[cand], foot_r_b)):
                rename_map[cand] = "ToesR"
                break

        protected = (
            set(rename_map.keys()) | set(rename_map.values()) | existing_spring_bones
        )
        pruned_cnt = 0
        while True:
            leaves = [
                b.name
                for b in eb
                if len(b.children) == 0
                and b.name not in weighted_bones
                and b.name not in protected
                and not is_physics_or_spring_bone(b.name)
                and not (b.parent and is_physics_or_spring_bone(b.parent.name))
                and not any(
                    k in b.name
                    for k in (
                        "指",
                        "Thumb",
                        "Index",
                        "Middle",
                        "Ring",
                        "Little",
                        "Finger",
                        "目",
                        "Eye",
                        "足",
                        "Toe",
                        "Foot",
                    )
                )
            ]
            if not leaves:
                break
            for bn in leaves:
                eb.remove(eb[bn])
                pruned_cnt += 1

        bpy.ops.object.mode_set(mode="OBJECT")

        # 追踪所有骨骼改名链（old -> final）以便最后一次性映射到 SpringBone 快照
        final_rename_map = {}
        reverse_rename_map = {}

        def record_rename(old_n, new_n):
            origs = reverse_rename_map.pop(old_n, [old_n])
            for o in origs:
                final_rename_map[o] = new_n
            reverse_rename_map.setdefault(new_n, []).extend(origs)

        existing = {b.name for b in armature_obj.data.bones}
        renamed = 0
        for bone in list(armature_obj.data.bones):
            tgt = rename_map.get(bone.name)
            if not tgt or tgt == bone.name:
                continue
            if tgt in existing:
                occ = armature_obj.data.bones.get(tgt)
                if occ and occ.name not in rename_map:
                    tmp = f"Aux_{tgt}_old"
                    while tmp in existing:
                        tmp += "_"
                    occ_old = occ.name
                    res_n = safe_rename_bone(
                        armature_obj,
                        occ,
                        tmp,
                        existing,
                        bound_meshes=bound_meshes,
                        has_vrm_refs=has_vrm_refs,
                    )
                    if res_n:
                        record_rename(occ_old, res_n)
                        renamed += 1
            b_old = bone.name
            res_n = safe_rename_bone(
                armature_obj,
                bone,
                tgt,
                existing,
                bound_meshes=bound_meshes,
                has_vrm_refs=has_vrm_refs,
            )
            if res_n:
                record_rename(b_old, res_n)
                renamed += 1

        for bone in list(armature_obj.data.bones):
            if bone.name.isascii():
                continue
            old = bone.name
            base_en = translate_non_ascii_bone_name(old, mmd_name_e_map.get(old, ""))
            cand, idx = base_en, 1
            while cand in existing and cand != old:
                cand = f"{base_en}_{idx}"
                idx += 1
            res_n = safe_rename_bone(
                armature_obj,
                bone,
                cand,
                existing,
                bound_meshes=bound_meshes,
                has_vrm_refs=has_vrm_refs,
            )
            if res_n:
                record_rename(old, res_n)
                renamed += 1

        if ground_to_zero:
            dz = ground_model_to_z0(armature_obj, bound_meshes=bound_meshes)
            if abs(dz) >= 0.001:
                print(
                    f"   👟 [自动接地] 已将鞋底最低点整体抬升 {dz:+.4f}m 对齐地面 Z=0.0"
                )

        skip_toes = False
        if fix_high_heel_rig:
            skip_toes, toe_merges = apply_high_heel_retarget_fix(
                armature_obj, bound_meshes=bound_meshes
            )
            for src_b, dst_b in toe_merges.items():
                record_rename(src_b, dst_b)

        assigned = validate_and_assign_vrm_humanoid(armature_obj, skip_toes=skip_toes)
        protected_spring = {
            final_rename_map.get(n, n)
            for n in collect_existing_spring_bone_names(armature_obj)
        }
        protected_human = set(assigned.values()) | {"Root", "Pelvis"} | protected_spring
        merged_cnt, merged_map = merge_excess_bones_to_limit(
            armature_obj,
            protected_human,
            max_bones=max_bones,
            bound_meshes=bound_meshes,
        )
        for src_b, dst_b in merged_map.items():
            record_rename(src_b, dst_b)

        if merged_cnt > 0:
            assigned = validate_and_assign_vrm_humanoid(
                armature_obj, skip_toes=skip_toes
            )

        # 所有改名、接地与合并完成后，一次性把物理快照写入 VRM spring_bone1
        apply_mmd_spring_snapshot_to_vrm(armature_obj, rename_map=final_rename_map)

        protected_spring_final = collect_existing_spring_bone_names(armature_obj)
        spring_cand_cnt = sum(
            1 for b in armature_obj.data.bones if is_physics_or_spring_bone(b.name)
        )
        final_w = collect_weighted_bone_names(armature_obj, bound_meshes=bound_meshes)
        core_check = {
            k: f"{assigned.get(k)}({final_w.get(assigned.get(k), 0)}v)"
            for k in (
                "hips",
                "spine",
                "chest",
                "upperChest",
                "head",
                "leftUpperArm",
                "rightUpperArm",
                "leftUpperLeg",
                "rightUpperLeg",
                "leftLowerLeg",
                "rightLowerLeg",
                "leftFoot",
                "rightFoot",
                "leftToes",
                "rightToes",
            )
            if k in assigned
        }
        print(
            f"   🦴 骨骼处理完成：保留 {len(armature_obj.data.bones)} 根（上限={max_bones or '不限'}），"
            f"清理 {len(to_remove)}+{pruned_cnt} 根废骨，合并 {merged_cnt} 根，重命名 {renamed} 根。"
        )
        print(
            f"   🌸 [弹簧骨保护] 已有SpringBone骨骼={len(protected_spring_final)}根 | 保留物理摇晃候选骨={spring_cand_cnt}根"
        )
        print(f"   ⚖️ [核心骨骼链路与权重] {core_check}")

    for coll_data in (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.armatures,
        bpy.data.collections,
    ):
        for item in coll_data:
            if jp_model_name in item.name and not (
                coll_data is bpy.data.objects and re.search(r"\.\d+$", item.name)
            ):
                item.name = item.name.replace(jp_model_name, en_model_name)
    print(f"✅ [步骤 1] 骨骼与命名处理完成！耗时 {time.perf_counter() - t0:.2f}s")
