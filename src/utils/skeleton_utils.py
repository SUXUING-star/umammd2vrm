import json
import math
import re

import bpy
import numpy as np
from mathutils import Vector

from step1_bone_map import (
    build_vrm_humanoid_mappings,
    is_physics_or_spring_bone,
)
from utils.spring_utils import (
    SNAPSHOT_PROP,
    classify_spring_part,
    is_ancestor,
)


def to_snake_case(name: str) -> str:
    return re.sub(r"([A-Z])", r"_\1", name).lower()


def bone_depth(b):
    d = 0
    cur = b.parent
    while cur:
        d += 1
        cur = cur.parent
    return d


def find_first_bone(bones_dict, candidates):
    for c in candidates:
        if c in bones_dict:
            return bones_dict[c]
    return None


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


def get_snapshot_spring_bone_names_raw(armature_obj):
    if not armature_obj or SNAPSHOT_PROP not in armature_obj:
        return set()
    try:
        snap = json.loads(armature_obj[SNAPSHOT_PROP])
    except Exception:
        return set()

    names = set()
    if snap.get("center_bone"):
        names.add(snap["center_bone"])
    for cols in snap.get("collider_groups", {}).values():
        for c in cols:
            if c.get("bone"):
                names.add(c["bone"])
    for sp in snap.get("springs", []):
        for j in sp.get("joints", []):
            if j.get("bone"):
                names.add(j["bone"])
    return names


def collect_existing_spring_bone_names(armature_obj):
    ext = getattr(armature_obj.data, "vrm_addon_extension", None)
    names = {
        ref.bone_name
        for ref in iter_spring_bone_refs(ext)
        if getattr(ref, "bone_name", "")
    }
    names.update(get_snapshot_spring_bone_names_raw(armature_obj))
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
    _, map_vrm1 = build_vrm_humanoid_mappings()

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


def ensure_object_mode(obj):
    if not obj or obj.mode == "OBJECT":
        return
    prev_active = bpy.context.view_layer.objects.active
    was_hidden = obj.hide_viewport
    if was_hidden:
        obj.hide_viewport = False
    try:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="OBJECT")
    finally:
        if was_hidden:
            obj.hide_viewport = True
        bpy.context.view_layer.objects.active = prev_active


def merge_bone_pairs_to_parent(armature_obj, child_to_parent, bound_meshes=None):
    if not child_to_parent:
        return 0
    if bound_meshes is None:
        bound_meshes = get_bound_meshes(armature_obj)
    for mesh_obj in bound_meshes:
        ensure_object_mode(mesh_obj)  # <--- 新增：确保网格不在编辑模式
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


def ensure_bust_tip_bones(armature_obj, rename_map):
    if not armature_obj or SNAPSHOT_PROP not in armature_obj:
        return 0
    try:
        snap = json.loads(armature_obj[SNAPSHOT_PROP])
    except Exception:
        return 0

    bones = armature_obj.data.bones
    need_tips = []
    for sp_idx, sp_spec in enumerate(snap.get("springs", [])):
        joints = sp_spec.get("joints", [])
        if not joints:
            continue
        resolved = [
            rename_map.get(j["bone"], j["bone"])
            for j in joints
            if rename_map.get(j["bone"], j["bone"]) in bones
        ]
        part = sp_spec.get("part") or (
            classify_spring_part(resolved[0]) if resolved else ""
        )
        if len(resolved) == 1 and part == "bust":
            need_tips.append((sp_idx, resolved[0]))

    if not need_tips:
        return 0

    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode="EDIT")
    eb = armature_obj.data.edit_bones
    added = 0
    for sp_idx, root_name in need_tips:
        root_b = eb.get(root_name)
        if not root_b:
            continue
        if len(root_b.children) > 0:
            ch_name = root_b.children[0].name
            snap["springs"][sp_idx]["joints"].append(
                {"bone": ch_name, "hit_radius": 0.010, "sp_norm": 0.35}
            )
            continue

        tip_name = f"{root_name}_Tip"
        idx = 1
        while tip_name in eb:
            tip_name = f"{root_name}_Tip_{idx}"
            idx += 1

        vec = root_b.tail - root_b.head
        if vec.length >= 0.005:
            dir_v = vec.normalized()
            seg_len = max(0.05, vec.length)
        else:
            dir_v = Vector((0.0, -1.0, 0.0))
            seg_len = 0.05

        tip_b = eb.new(tip_name)
        tip_b.parent = root_b
        tip_b.head = root_b.head + dir_v * seg_len
        tip_b.tail = tip_b.head + dir_v * 0.02
        snap["springs"][sp_idx]["joints"].append(
            {"bone": tip_b.name, "hit_radius": 0.010, "sp_norm": 0.35}
        )
        added += 1

    bpy.ops.object.mode_set(mode="OBJECT")
    armature_obj[SNAPSHOT_PROP] = json.dumps(snap, ensure_ascii=False)
    if added:
        print(f"   💗 [胸部物理补全] 为 {added} 根单骨胸骨自动补出 _Tip 末端节点")
    return added


def merge_excess_bones_to_limit(
    armature_obj, protected_names, max_bones=240, bound_meshes=None
):
    if max_bones <= 0 or len(armature_obj.data.bones) <= max_bones:
        return 0, {}

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


def decimate_spring_chains_budgeted(
    armature_obj,
    protected_human_base,
    max_bones=240,
    bound_meshes=None,
    rename_map=None,
):
    """优先保住前/侧裙摆的 3 节大腿中段碰撞关节及长发分段，裁掉微小饰品子链。"""
    bones = armature_obj.data.bones
    rename_map = rename_map or {}

    snap = {}
    if SNAPSHOT_PROP in armature_obj:
        try:
            snap = json.loads(armature_obj[SNAPSHOT_PROP])
        except Exception:
            snap = {}

    chains_info = []
    all_spring_bones = set()
    prio_table = {
        "bust": 4,
        "bangs": 3,
        "front_skirt": 3,
        "side_skirt": 2,
        "sleeve": 2,
        "hair": 2,
        "skirt": 1,
        "other": 0,
    }

    for sp_spec in snap.get("springs", []):
        ch = []
        seen = set()
        for j in sp_spec.get("joints", []):
            bn = rename_map.get(j["bone"], j["bone"])
            if bn in bones and bn not in seen:
                seen.add(bn)
                ch.append(bn)
        if len(ch) >= 2:
            all_spring_bones.update(ch)
            part = sp_spec.get("part") or classify_spring_part(ch[0])
            span = (bones[ch[-1]].head_local - bones[ch[0]].head_local).length
            # 前/侧裙摆只要 >=0.12m 就保 3 节（确保大腿中段存在碰撞关节！）
            if part in ("front_skirt", "side_skirt", "sleeve"):
                target_len = 4 if span >= 0.40 else (3 if span >= 0.12 else 2)
            else:
                target_len = 4 if span >= 0.40 else (3 if span >= 0.18 else 2)
            chains_info.append(
                {
                    "chain": ch,
                    "part": part,
                    "prio": prio_table.get(part, 0),
                    "span": span,
                    "target_len": target_len,
                }
            )

    if max_bones <= 0 or len(bones) <= max_bones:
        return 0, {}, all_spring_bones

    # 第 1 步：先只合并非弹簧的冗余辅助/末梢骨，不伤害任何弹簧链
    merged_total, child_to_surv = merge_excess_bones_to_limit(
        armature_obj,
        protected_human_base | all_spring_bones,
        max_bones=max_bones,
        bound_meshes=bound_meshes,
    )

    bones = armature_obj.data.bones
    excess = len(bones) - max_bones
    if excess <= 0 or not chains_info:
        surviving = {bn for info in chains_info for bn in info["chain"] if bn in bones}
        return merged_total, child_to_surv, surviving

    orig_parent_of = {b.name: (b.parent.name if b.parent else None) for b in bones}
    head_of = {b.name: b.head_local.copy() for b in bones}
    direct_merge = {}

    def pop_best_interior(target_info):
        ch = target_info["chain"]
        best_i = 1
        best_score = float("inf")
        for i in range(1, len(ch) - 1):
            d_prev = (head_of[ch[i]] - head_of[ch[i - 1]]).length
            d_next = (head_of[ch[i + 1]] - head_of[ch[i]]).length
            if d_prev + d_next < best_score:
                best_score = d_prev + d_next
                best_i = i
        rm_bone = ch[best_i]
        if rm_bone in protected_human_base:
            return False
        direct_merge[rm_bone] = ch[best_i - 1]
        ch.pop(best_i)
        return True

    # 第 2A 步：将所有超长链抽稀到 target_len（保住前裙3节与长发3~4节）
    while excess > 0:
        over_target = [
            info
            for info in chains_info
            if len(info["chain"]) > info["target_len"] and len(info["chain"]) >= 3
        ]
        if not over_target:
            break
        over_target.sort(
            key=lambda info: (
                len(info["chain"]) - info["target_len"],
                -info["prio"],
            ),
            reverse=True,
        )
        if not pop_best_interior(over_target[0]):
            break
        excess -= 1

    # 第 2B 步：若仍超预算，先放弃微小的 other 装饰链 (span < 0.14m)，释放名额保住前裙大腿中段节点
    if excess > 0:
        micro_other = [
            info
            for info in chains_info
            if info["part"] == "other"
            and info["span"] < 0.14
            and len(info["chain"]) >= 2
        ]
        micro_other.sort(key=lambda info: info["span"])
        for info in micro_other:
            if excess <= 0:
                break
            ch = info["chain"]
            if any(bn in protected_human_base for bn in ch):
                continue
            for bn in reversed(ch):
                direct_merge[bn] = orig_parent_of.get(bn)
                excess -= 1
            ch.clear()

    # 第 2C 步：若仍超预算，按优先级从低到高压缩中段（后裙/短发先压，前裙/袖子最后压）
    while excess > 0:
        trimmable = [info for info in chains_info if len(info["chain"]) >= 3]
        if not trimmable:
            break
        trimmable.sort(
            key=lambda info: (info["prio"], info["span"], -len(info["chain"]))
        )
        if not pop_best_interior(trimmable[0]):
            break
        excess -= 1

    # 第 3 步：若仍超限，整条撤除最低优先级链（绝不撤 bust）
    if excess > 0:
        droppable = [
            info
            for info in chains_info
            if len(info["chain"]) >= 2 and info["part"] != "bust"
        ]
        droppable.sort(key=lambda info: (info["prio"], info["span"]))
        for info in droppable:
            if excess <= 0:
                break
            ch = info["chain"]
            if any(bn in protected_human_base for bn in ch):
                continue
            for bn in reversed(ch):
                direct_merge[bn] = orig_parent_of.get(bn)
                excess -= 1
            ch.clear()

    if direct_merge:
        spring_surv = {}
        for bn in direct_merge:
            cur = direct_merge[bn]
            while cur in direct_merge:
                cur = direct_merge[cur]
            if cur is not None:
                spring_surv[bn] = cur
        removed = merge_bone_pairs_to_parent(
            armature_obj, spring_surv, bound_meshes=bound_meshes
        )
        merged_total += removed
        child_to_surv.update(spring_surv)

    bones = armature_obj.data.bones
    surviving = {bn for info in chains_info for bn in info["chain"] if bn in bones}
    return merged_total, child_to_surv, surviving


def decimate_spring_bones_stride(
    armature_obj, spring_names, protected_names, max_bones=240, bound_meshes=None
):
    if max_bones <= 0 or len(armature_obj.data.bones) <= max_bones:
        return 0, {}

    bones = armature_obj.data.bones
    spring_set = set(spring_names)
    roots = [
        b
        for b in bones
        if b.name in spring_set
        and (b.parent is None or b.parent.name not in spring_set)
    ]

    candidates = []

    def walk(b, depth):
        if depth % 2 == 1 and b.name not in protected_names and b.parent:
            candidates.append((depth, b.name, b.parent.name))
        for ch in b.children:
            if ch.name in spring_set:
                walk(ch, depth + 1)

    for r in roots:
        walk(r, 0)

    if not candidates:
        return 0, {}

    excess = len(bones) - max_bones
    candidates.sort(key=lambda x: -x[0])
    stride_merge = {bname: pname for _, bname, pname in candidates[:excess]}

    merged = merge_bone_pairs_to_parent(
        armature_obj, stride_merge, bound_meshes=bound_meshes
    )
    return merged, stride_merge


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
