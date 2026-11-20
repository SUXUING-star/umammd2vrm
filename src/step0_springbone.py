import json
import math
import uuid

import bpy
from mathutils import Matrix, Vector

from step1_bone_map import is_physics_or_spring_bone

SNAPSHOT_PROP = "ww_mmd_spring_snapshot"

BODY_COLLIDER_KEYWORDS = (
    "head",
    "neck",
    "chest",
    "upperchest",
    "spine",
    "hips",
    "pelvis",
    "shoulder",
    "upperarm",
    "lowerarm",
    "hand",
    "upperleg",
    "lowerleg",
    "foot",
    "頭",
    "头",
    "首",
    "上半身",
    "下半身",
    "腰",
    "胸",
    "肩",
    "腕",
    "ひじ",
    "手首",
    "足",
    "ひざ",
    "足首",
)


def _call_vrm_op(op_name, **kwargs):
    op_ns = getattr(bpy.ops, "vrm", None)
    op = getattr(op_ns, op_name, None) if op_ns else None
    if op is None:
        return False
    try:
        valid_props = {p.identifier for p in op.get_rna_type().properties}
        filtered = {k: v for k, v in kwargs.items() if k in valid_props}
        return op("EXEC_DEFAULT", False, **filtered) == {"FINISHED"}
    except Exception:
        return False


def _get_sb1(armature_obj):
    return armature_obj.data.vrm_addon_extension.spring_bone1


def _set_enum_ci(prop_owner, prop_name, target):
    if not prop_owner or not hasattr(prop_owner, prop_name):
        return
    try:
        prop = prop_owner.bl_rna.properties.get(prop_name)
        if prop and prop.type == "ENUM":
            t_low = target.lower()
            for item in prop.enum_items:
                if item.identifier.lower() == t_low:
                    setattr(prop_owner, prop_name, item.identifier)
                    return
    except Exception:
        pass
    try:
        setattr(prop_owner, prop_name, target)
    except Exception:
        pass


def _ensure_uuid(item):
    if hasattr(item, "uuid"):
        cur = getattr(item, "uuid", "")
        if not cur:
            item.uuid = uuid.uuid4().hex
        return item.uuid
    return ""


def _is_valid_body_collider_bone(bone_name):
    low = bone_name.lower()
    if any(
        bad in low
        for bad in (
            "裙",
            "スカート",
            "skirt",
            "dummy",
            "全ての親",
            "センター",
            "center",
            "groove",
        )
    ):
        return False
    return any(kw in low for kw in BODY_COLLIDER_KEYWORDS)


def _collect_weighted_bones(armature_obj):
    weighted = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data or not obj.vertex_groups:
            continue
        bound = obj.parent == armature_obj or any(
            m.type == "ARMATURE" and m.object == armature_obj for m in obj.modifiers
        )
        if not bound:
            continue
        idx_to_name = {vg.index: vg.name for vg in obj.vertex_groups}
        for v in obj.data.vertices:
            for g in v.groups:
                if g.weight > 0.0001 and g.group in idx_to_name:
                    bname = idx_to_name[g.group]
                    weighted[bname] = weighted.get(bname, 0) + 1
    return weighted


def _remap_mmd_collider_bone(bone_name, bones, weighted_bones):
    d_pairs = {
        "左足": "左足D",
        "左ひざ": "左ひざD",
        "左足首": "左足首D",
        "右足": "右足D",
        "右ひざ": "右ひざD",
        "右足首": "右足首D",
        "左腕": "左腕D",
        "左ひじ": "左ひじD",
        "左手首": "左手首D",
        "右腕": "右腕D",
        "右ひじ": "右ひじD",
        "右手首": "右手首D",
    }
    d_name = d_pairs.get(bone_name)
    if d_name and d_name in bones:
        if weighted_bones.get(d_name, 0) >= weighted_bones.get(bone_name, 0):
            return d_name
    return bone_name


def _get_mmd_rigid_dimensions(rb_obj):
    rb = getattr(rb_obj, "mmd_rigid", None)
    shape = str(getattr(rb, "shape", "SPHERE")).upper()
    rb_scale = rb_obj.matrix_world.to_scale()
    sx, sy, sz = abs(rb_scale.x), abs(rb_scale.y), abs(rb_scale.z)
    avg_scale = max(1e-5, (sx + sy + sz) / 3.0)

    if rb_obj.type == "MESH" and rb_obj.data and len(rb_obj.data.vertices) > 0:
        max_x = max(abs(v.co.x) for v in rb_obj.data.vertices) * sx
        max_y = max(abs(v.co.y) for v in rb_obj.data.vertices) * sy
        max_z = max(abs(v.co.z) for v in rb_obj.data.vertices) * sz
        if shape == "SPHERE":
            return "SPHERE", (max(max_x, max_y, max_z), 0.0, 0.0), (sx, sy, sz)
        if shape == "CAPSULE":
            r = max(max_x, max_y)
            half_h = max(0.0, max_z - r)
            return "CAPSULE", (r, half_h * 2.0, 0.0), (sx, sy, sz)
        return "BOX", (max_x, max_y, max_z), (sx, sy, sz)

    size = tuple(getattr(rb, "size", (0.05, 0.05, 0.05)))
    if shape == "SPHERE":
        return "SPHERE", (abs(size[0]) * avg_scale, 0.0, 0.0), (sx, sy, sz)
    if shape == "CAPSULE":
        return (
            "CAPSULE",
            (abs(size[0]) * max(sx, sy), abs(size[1]) * sz, 0.0),
            (sx, sy, sz),
        )
    return (
        "BOX",
        (abs(size[0]) * sx, abs(size[1]) * sy, abs(size[2]) * sz),
        (sx, sy, sz),
    )


def _compute_collider_armature_spec(armature_obj, target_bone_name, rb_obj):
    """记录碰撞体在 Armature 空间下相对于 bone.head_local 的偏移，完全脱离 bone.matrix_local 旋转。"""
    bone = armature_obj.data.bones.get(target_bone_name)
    if not bone:
        return None

    shape, dims, (sx, sy, sz) = _get_mmd_rigid_dimensions(rb_obj)
    arm_inv = armature_obj.matrix_world.inverted()
    arm_scale = armature_obj.matrix_world.to_scale()
    avg_arm_scale = max(
        1e-5, (abs(arm_scale.x) + abs(arm_scale.y) + abs(arm_scale.z)) / 3.0
    )
    head_arm = bone.head_local

    if shape == "SPHERE":
        radius = dims[0] / avg_arm_scale
        if radius <= 0.004 or radius > 0.22:
            return None
        d = (arm_inv @ rb_obj.matrix_world.translation) - head_arm
        return {
            "bone": target_bone_name,
            "shape": "Sphere",
            "delta_arm": [float(d.x), float(d.y), float(d.z)],
            "radius": float(radius),
        }

    if shape == "CAPSULE":
        radius = dims[0] / avg_arm_scale
        if radius <= 0.004 or radius > 0.22:
            return None
        half_h_world = dims[1] * 0.5
        if half_h_world < 0.003:
            d = (arm_inv @ rb_obj.matrix_world.translation) - head_arm
            return {
                "bone": target_bone_name,
                "shape": "Sphere",
                "delta_arm": [float(d.x), float(d.y), float(d.z)],
                "radius": float(radius),
            }
        local_z = half_h_world / max(1e-5, sz)
        d_a = (
            arm_inv @ (rb_obj.matrix_world @ Vector((0.0, 0.0, -local_z)))
        ) - head_arm
        d_b = (arm_inv @ (rb_obj.matrix_world @ Vector((0.0, 0.0, local_z)))) - head_arm
        return {
            "bone": target_bone_name,
            "shape": "Capsule",
            "delta_arm": [float(d_a.x), float(d_a.y), float(d_a.z)],
            "tail_delta_arm": [float(d_b.x), float(d_b.y), float(d_b.z)],
            "radius": float(radius),
        }

    hx, hy, hz = dims
    axes = [(hx, 0, sx), (hy, 1, sy), (hz, 2, sz)]
    axes.sort(key=lambda x: x[0], reverse=True)
    longest, idx_max, s_max = axes[0]
    mid, smallest = axes[1][0], axes[2][0]

    r_world = min(mid, smallest) if longest > mid * 1.4 else (hx + hy + hz) / 3.0
    radius = r_world / avg_arm_scale
    if radius <= 0.005 or radius > 0.18:
        return None

    if longest > mid * 1.4 and longest > 0.015:
        half_len_world = max(0.0, longest - r_world)
        local_vec = [0.0, 0.0, 0.0]
        local_vec[idx_max] = half_len_world / max(1e-5, s_max)
        v_pos = Vector(local_vec)
        d_a = (arm_inv @ (rb_obj.matrix_world @ (-v_pos))) - head_arm
        d_b = (arm_inv @ (rb_obj.matrix_world @ v_pos)) - head_arm
        return {
            "bone": target_bone_name,
            "shape": "Capsule",
            "delta_arm": [float(d_a.x), float(d_a.y), float(d_a.z)],
            "tail_delta_arm": [float(d_b.x), float(d_b.y), float(d_b.z)],
            "radius": float(radius),
        }

    d = (arm_inv @ rb_obj.matrix_world.translation) - head_arm
    return {
        "bone": target_bone_name,
        "shape": "Sphere",
        "delta_arm": [float(d.x), float(d.y), float(d.z)],
        "radius": float(radius),
    }


def _classify_spring_part(name: str) -> str:
    low = name.lower()
    if any(k in low for k in ("胸", "bust", "boob", "oppai")):
        return "bust"
    if any(
        k in low
        for k in (
            "前髪",
            "刘海",
            "liuhai",
            "bangs",
            "ahoge",
            "アホ毛",
            "sideburn",
            "もみあげ",
        )
    ):
        return "bangs"
    if any(
        k in low
        for k in (
            "髪",
            "发",
            "hair",
            "twin",
            "pony",
            "braid",
            "ツイン",
            "ポニ",
            "辮",
            "辫",
        )
    ):
        return "hair"
    if any(
        k in low
        for k in (
            "スカート",
            "skirt",
            "マント",
            "cape",
            "裾",
            "裙",
            "cloth",
            "dress",
            "袖",
            "sleeve",
        )
    ):
        return "skirt"
    return "other"


def _extract_mmd_joint_hints(rb_obj, joint_obj):
    hit_radius = 0.010
    if rb_obj is not None:
        shape, dims, _ = _get_mmd_rigid_dimensions(rb_obj)
        raw_r = (
            dims[0]
            if shape in ("SPHERE", "CAPSULE")
            else min(dims[0], dims[1], dims[2])
        )
        hit_radius = max(0.005, min(0.016, float(raw_r) * 0.35))

    mmd_sp = 0.0
    if joint_obj is not None:
        mmd_j = getattr(joint_obj, "mmd_joint", None)
        if mmd_j and hasattr(mmd_j, "spring_angular"):
            mmd_sp = sum(abs(float(x)) for x in mmd_j.spring_angular) / 3.0

    sp_norm = min(1.0, math.log10(1.0 + mmd_sp) / 2.5) if mmd_sp > 0.0 else 0.35
    return float(hit_radius), float(sp_norm)


def _compute_damped_joint_params(
    bone_name, hit_radius, sp_norm, t_chain=0.5, seg_len=0.05
):
    """按临界/微过阻尼公式解算参数，保证 20~60fps 启动与静息态无过冲震荡。"""
    part = _classify_spring_part(bone_name)
    true_len = max(0.005, float(seg_len))
    len_scale = max(0.05, min(1.0, true_len / 0.10))
    t = max(0.0, min(1.0, float(t_chain)))

    if part == "bust":
        alpha_target = 0.21 + 0.03 * sp_norm
        drag_force = 0.86
        gravity_power = 0.0
    elif part == "bangs":
        alpha_target = (0.21 - 0.06 * t) + 0.03 * sp_norm
        drag_force = 0.82 + 0.04 * t
        gravity_power = 0.0
    elif part == "hair":
        alpha_target = (0.19 - 0.05 * t) + 0.03 * sp_norm
        drag_force = 0.78 + 0.06 * t
        gravity_power = 0.008 * len_scale
    elif part == "skirt":
        alpha_target = (0.21 - 0.06 * t) + 0.03 * sp_norm
        drag_force = 0.80 + 0.05 * t
        gravity_power = 0.010 * len_scale
    else:
        alpha_target = (0.19 - 0.05 * t) + 0.03 * sp_norm
        drag_force = 0.80 + 0.05 * t
        gravity_power = 0.008 * len_scale

    # 严格随真实骨长线性缩放，不再设置 0.12 下限以免短骨 alpha60 爆表
    stiffness = max(0.01, min(2.00, true_len * alpha_target * 60.0))
    return float(hit_radius), float(stiffness), float(drag_force), float(gravity_power)


def _compute_joint_params(bone_name, rb_obj, joint_obj, t_chain=0.5, seg_len=0.05):
    hit_radius, sp_norm = _extract_mmd_joint_hints(rb_obj, joint_obj)
    return _compute_damped_joint_params(
        bone_name, hit_radius, sp_norm, t_chain, seg_len
    )


def _collect_linear_chains(roots, physics_bones):
    chains = []

    def walk(b, current_chain):
        current_chain.append(b)
        phys_children = [ch for ch in b.children if ch.name in physics_bones]
        if len(phys_children) == 1:
            walk(phys_children[0], current_chain)
        elif len(phys_children) > 1:
            walk(phys_children[0], current_chain)
            for extra_ch in phys_children[1:]:
                walk(extra_ch, [])
        else:
            tip_children = [
                ch
                for ch in b.children
                if ch.name not in physics_bones and not ch.children
            ]
            if len(tip_children) == 1:
                current_chain.append(tip_children[0])
            elif len(b.children) == 1 and b.children[0].name not in physics_bones:
                current_chain.append(b.children[0])
            if len(current_chain) >= 2:
                chains.append(current_chain)

    for r in roots:
        walk(r, [])
    return chains


def snapshot_mmd_physics_to_armature(armature_obj=None, overwrite=False):
    armature_obj = armature_obj or next(
        (o for o in bpy.data.objects if o.type == "ARMATURE"), None
    )
    if not armature_obj:
        return False
    if not overwrite and SNAPSHOT_PROP in armature_obj:
        return True

    bones = armature_obj.data.bones
    center_bone = next(
        (
            bones[c]
            for c in ("Root", "全ての親", "全ての亲", "Position", "ParentNode")
            if c in bones
        ),
        None,
    )
    center_bone_name = center_bone.name if center_bone else ""

    rigid_bodies = [
        o for o in bpy.data.objects if getattr(o, "mmd_type", "NONE") == "RIGID_BODY"
    ]
    joints = [o for o in bpy.data.objects if getattr(o, "mmd_type", "NONE") == "JOINT"]

    if not rigid_bodies:
        core_exclude = (
            "hips",
            "spine",
            "chest",
            "upperchest",
            "neck",
            "head",
            "pelvis",
            "root",
            "全ての親",
            "センター",
            "腰",
            "下半身",
            "上半身",
            "首",
            "頭",
            "头",
            "目",
            "eye",
            "指",
            "thumb",
            "index",
            "middle",
            "ring",
            "little",
            "腕",
            "ひじ",
            "手首",
            "足",
            "ひざ",
            "足首",
            "shoulder",
            "arm",
            "hand",
            "leg",
            "foot",
            "toe",
        )
        physics_bones = {
            b.name
            for b in bones
            if is_physics_or_spring_bone(b.name)
            and not any(ex in b.name.lower() for ex in core_exclude)
        }
        if not physics_bones:
            return False

        cols_by_group = {"0": []}
        for cands, rad, off in (
            (("Head", "頭", "头"), 0.085, [0.0, 0.0, 0.08]),
            (("UpperChest", "Chest", "上半身2", "上半身"), 0.095, [0.0, 0.0, 0.05]),
            (("Hips", "下半身", "腰", "Pelvis"), 0.09, [0.0, 0.0, 0.0]),
        ):
            b = next((bones[c] for c in cands if c in bones), None)
            if b:
                cols_by_group["0"].append(
                    {"bone": b.name, "shape": "Sphere", "delta_arm": off, "radius": rad}
                )

        roots = [
            b
            for b in bones
            if b.name in physics_bones
            and (b.parent is None or b.parent.name not in physics_bones)
        ]
        chains = _collect_linear_chains(roots, physics_bones)
        springs = []
        for idx, ch in enumerate(chains):
            chain_len = max(1, len(ch) - 1)
            j_list = []
            for j_idx, b in enumerate(ch):
                seg_len = (
                    (ch[j_idx + 1].head_local - b.head_local).length
                    if j_idx + 1 < len(ch)
                    else (b.tail_local - b.head_local).length
                )
                hit_r, sp_norm = _extract_mmd_joint_hints(None, None)
                j_list.append(
                    {
                        "bone": b.name,
                        "hit_radius": hit_r,
                        "sp_norm": sp_norm,
                        "params": list(
                            _compute_damped_joint_params(
                                b.name, hit_r, sp_norm, j_idx / chain_len, seg_len
                            )
                        ),
                    }
                )
            springs.append(
                {
                    "name": f"Spring_{ch[0].name}_{idx}",
                    "groups": ["0"] if cols_by_group["0"] else [],
                    "joints": j_list,
                }
            )
        snap = {
            "mode": "heuristic",
            "center_bone": center_bone_name,
            "collider_groups": cols_by_group,
            "springs": springs,
        }
        armature_obj[SNAPSHOT_PROP] = json.dumps(snap, ensure_ascii=False)
        return True

    weighted_bones = _collect_weighted_bones(armature_obj)
    joint_by_rigid = {}
    for j_obj in joints:
        rbc = getattr(j_obj, "rigid_body_constraint", None)
        if rbc and rbc.object2:
            joint_by_rigid[rbc.object2] = j_obj

    cols_by_group = {}
    bone_to_rigid = {}
    col_count = 0
    skipped_non_body = 0

    for rb_obj in rigid_bodies:
        mmd_rb = getattr(rb_obj, "mmd_rigid", None)
        if not mmd_rb:
            continue
        raw_bone_name = getattr(mmd_rb, "bone", "")
        if not raw_bone_name or raw_bone_name not in bones:
            continue
        rb_type = str(getattr(mmd_rb, "type", "0"))
        if rb_type == "0":
            target_bone = _remap_mmd_collider_bone(raw_bone_name, bones, weighted_bones)
            if not _is_valid_body_collider_bone(target_bone):
                skipped_non_body += 1
                continue
            spec = _compute_collider_armature_spec(armature_obj, target_bone, rb_obj)
            if spec is not None:
                grp_key = str(int(getattr(mmd_rb, "collision_group_number", 0)))
                cols_by_group.setdefault(grp_key, []).append(spec)
                col_count += 1
        else:
            prev = bone_to_rigid.get(raw_bone_name)
            if prev is None or (
                str(getattr(prev.mmd_rigid, "type", "1")) == "1" and rb_type == "2"
            ):
                bone_to_rigid[raw_bone_name] = rb_obj

    humanoid_core = {
        "Hips",
        "Spine",
        "Chest",
        "UpperChest",
        "Neck",
        "Head",
        "全ての親",
        "全ての亲",
        "センター",
        "下半身",
        "上半身",
        "上半身2",
        "首",
        "頭",
        "头",
    }
    physics_bones = {b for b in bone_to_rigid if b not in humanoid_core}
    roots = [
        b
        for b in bones
        if b.name in physics_bones
        and (b.parent is None or b.parent.name not in physics_bones)
    ]
    chains = _collect_linear_chains(roots, physics_bones)

    springs = []
    total_joints = 0
    for idx, ch in enumerate(chains):
        active_grps = set()
        joint_specs = []
        chain_len = max(1, len(ch) - 1)
        for j_idx, b in enumerate(ch):
            rb_obj = bone_to_rigid.get(b.name)
            j_obj = joint_by_rigid.get(rb_obj) if rb_obj else None
            seg_len = (
                (ch[j_idx + 1].head_local - b.head_local).length
                if j_idx + 1 < len(ch)
                else (b.tail_local - b.head_local).length
            )
            hit_r, sp_norm = _extract_mmd_joint_hints(rb_obj, j_obj)
            joint_specs.append(
                {
                    "bone": b.name,
                    "hit_radius": hit_r,
                    "sp_norm": sp_norm,
                    "params": list(
                        _compute_damped_joint_params(
                            b.name, hit_r, sp_norm, j_idx / chain_len, seg_len
                        )
                    ),
                }
            )
            if rb_obj:
                mask = getattr(rb_obj.mmd_rigid, "collision_group_mask", None)
                if mask is None:
                    active_grps.update(cols_by_group.keys())
                else:
                    for g_key in cols_by_group:
                        g_num = int(g_key)
                        if g_num < len(mask) and not mask[g_num]:
                            active_grps.add(g_key)
        total_joints += len(joint_specs)
        springs.append(
            {
                "name": f"Spring_{ch[0].name}_{idx}",
                "groups": sorted(active_grps, key=lambda x: int(x)),
                "joints": joint_specs,
            }
        )

    snap = {
        "mode": "mmd",
        "center_bone": center_bone_name,
        "collider_groups": cols_by_group,
        "springs": springs,
    }
    armature_obj[SNAPSHOT_PROP] = json.dumps(snap, ensure_ascii=False)
    print(
        f"   🌸 [SpringBone 快照] 缓存 {len(springs)} 条弹簧链（{total_joints} 个关节），"
        f"{col_count} 个身体碰撞体（过滤 {skipped_non_body} 个非人体刚体）。"
    )
    return True


def get_snapshot_spring_bone_names(armature_obj):
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


def _point_segment_distance(p, a, b):
    ab = b - a
    len_sq = ab.length_squared
    if len_sq < 1e-10:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / len_sq))
    proj = a + ab * t
    return (p - proj).length


def _create_vrm1_collider_entry(armature_obj, bone_name):
    before_len = len(_get_sb1(armature_obj).colliders)
    ok = _call_vrm_op(
        "add_spring_bone1_collider",
        armature_object_name=armature_obj.name,
        armature_name=armature_obj.name,
        bone_name=bone_name,
    )
    sb1 = _get_sb1(armature_obj)
    col = (
        sb1.colliders[-1]
        if (ok and len(sb1.colliders) > before_len)
        else sb1.colliders.add()
    )
    _ensure_uuid(col)

    if hasattr(col, "bpy_object") and col.bpy_object is None:
        empty = bpy.data.objects.new(f"VRM_Collider_{bone_name}", None)
        empty.empty_display_type = "SPHERE"
        empty.hide_render = True
        bpy.context.scene.collection.objects.link(empty)
        empty.parent = armature_obj
        empty.parent_type = "BONE"
        empty.parent_bone = bone_name
        col.bpy_object = empty

    if hasattr(col, "node") and hasattr(col.node, "bone_name"):
        col.node.bone_name = bone_name
    return col


def _probe_bone_collider_basis(col, armature_obj, bone_name, is_capsule, cache):
    """实测该骨骼下 col.shape.*.offset 到 Blender 世界坐标的基矩阵，保证 0 位置偏差。"""
    key = (bone_name, "Capsule" if is_capsule else "Sphere")
    if key in cache:
        return cache[key]

    if not hasattr(col, "bpy_object") or col.bpy_object is None:
        bone = armature_obj.data.bones.get(bone_name)
        bw = armature_obj.matrix_world @ bone.matrix_local
        res = (bw.translation.copy(), bw.to_3x3().inverted())
        cache[key] = res
        return res

    vl = bpy.context.view_layer
    if is_capsule:
        _set_enum_ci(col, "shape_type", "Capsule")
        col.shape.capsule.offset = (0.0, 0.0, 0.0)
        col.shape.capsule.tail = (0.0, 0.0, 0.05)
    else:
        _set_enum_ci(col, "shape_type", "Sphere")
        col.shape.sphere.offset = (0.0, 0.0, 0.0)
    vl.update()
    o0 = col.bpy_object.matrix_world.translation.copy()

    cols_mat = []
    for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        if is_capsule:
            col.shape.capsule.offset = axis
        else:
            col.shape.sphere.offset = axis
        vl.update()
        cols_mat.append(col.bpy_object.matrix_world.translation - o0)

    basis = Matrix((cols_mat[0], cols_mat[1], cols_mat[2])).transposed()
    if abs(basis.determinant()) < 1e-8:
        bone = armature_obj.data.bones.get(bone_name)
        basis_inv = (armature_obj.matrix_world @ bone.matrix_local).to_3x3().inverted()
    else:
        basis_inv = basis.inverted()

    cache[key] = (o0, basis_inv)
    return o0, basis_inv


def apply_mmd_spring_snapshot_to_vrm(armature_obj, rename_map=None, overwrite=True):
    """按最终骨骼名重映射，剔除零长度退化关节，按临界阻尼重算参数并屏蔽静息穿插碰撞。"""
    if not armature_obj or SNAPSHOT_PROP not in armature_obj:
        return 0, 0
    ext = getattr(armature_obj.data, "vrm_addon_extension", None)
    if not ext or not hasattr(ext, "spring_bone1"):
        return 0, 0

    try:
        snap = json.loads(armature_obj[SNAPSHOT_PROP])
    except Exception:
        return 0, 0

    rename_map = rename_map or {}
    bones = armature_obj.data.bones
    ext.spec_version = "1.0"
    sb1 = _get_sb1(armature_obj)
    if overwrite:
        sb1.springs.clear()
        sb1.collider_groups.clear()
        sb1.colliders.clear()

    try:
        bpy.context.view_layer.objects.active = armature_obj
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    def resolve_bone(bname):
        return rename_map.get(bname, bname)

    def is_bone_ancestor(bone, maybe_anc):
        cur = bone.parent
        while cur:
            if cur == maybe_anc:
                return True
            cur = cur.parent
        return False

    all_spring_bones = {
        resolve_bone(j_spec["bone"])
        for sp_spec in snap.get("springs", [])
        for j_spec in sp_spec.get("joints", [])
    }

    def pick_local_center(part_name, root_bone_name):
        root_b = bones.get(root_bone_name)
        if not root_b:
            return center_bone
        if part_name in ("hair", "bangs"):
            cands = (
                "UpperChest",
                "Chest",
                "Spine",
                "Hips",
                center_bone or "Root",
                "Root",
            )
        else:
            cands = ("Hips", center_bone or "Root", "Root")
        for c in cands:
            cb = bones.get(c)
            if cb and c not in all_spring_bones and is_bone_ancestor(root_b, cb):
                return c
        return ""

    arm_mat = armature_obj.matrix_world
    arm_scale = arm_mat.to_scale()
    avg_arm_scale = max(
        1e-5, (abs(arm_scale.x) + abs(arm_scale.y) + abs(arm_scale.z)) / 3.0
    )

    # 1. 创建碰撞体并按 (grp_key, bone_name) 细粒度保存世界坐标几何信息
    basis_cache = {}
    col_records_by_subkey = {}
    grp_to_subkeys = {}
    col_count = 0

    for grp_key, col_specs in sorted(
        snap.get("collider_groups", {}).items(), key=lambda x: int(x[0])
    ):
        for spec in col_specs:
            bname = resolve_bone(spec["bone"])
            if bname not in bones:
                continue
            b_obj = bones[bname]
            p_a_world = arm_mat @ (b_obj.head_local + Vector(spec["delta_arm"]))
            is_cap = spec["shape"] == "Capsule"
            p_b_world = (
                arm_mat @ (b_obj.head_local + Vector(spec["tail_delta_arm"]))
                if is_cap
                else p_a_world
            )
            final_r = max(0.008, float(spec["radius"]))
            col_r_world = final_r * avg_arm_scale

            col = _create_vrm1_collider_entry(armature_obj, bname)
            o0, basis_inv = _probe_bone_collider_basis(
                col, armature_obj, bname, is_cap, basis_cache
            )
            off_a = basis_inv @ (p_a_world - o0)

            if is_cap:
                off_b = basis_inv @ (p_b_world - o0)
                _set_enum_ci(col, "shape_type", "Capsule")
                col.shape.capsule.offset = (
                    float(off_a.x),
                    float(off_a.y),
                    float(off_a.z),
                )
                col.shape.capsule.tail = (
                    float(off_b.x),
                    float(off_b.y),
                    float(off_b.z),
                )
                col.shape.capsule.radius = final_r
            else:
                _set_enum_ci(col, "shape_type", "Sphere")
                col.shape.sphere.offset = (
                    float(off_a.x),
                    float(off_a.y),
                    float(off_a.z),
                )
                col.shape.sphere.radius = final_r

            subkey = (grp_key, bname)
            col_records_by_subkey.setdefault(subkey, []).append(
                {
                    "uuid": _ensure_uuid(col),
                    "name": getattr(col, "name", ""),
                    "is_cap": is_cap,
                    "p_a": p_a_world,
                    "p_b": p_b_world,
                    "r_world": col_r_world,
                }
            )
            grp_to_subkeys.setdefault(grp_key, set()).add(subkey)
            col_count += 1

    # 2. 按 (grp_key, bone_name) 建立细粒度 ColliderGroup
    sb1 = _get_sb1(armature_obj)
    subkey_to_cg_ref = {}
    for subkey, recs in sorted(
        col_records_by_subkey.items(), key=lambda x: (int(x[0][0]), x[0][1])
    ):
        cg = sb1.collider_groups.add()
        cg_uuid = _ensure_uuid(cg)
        cg_name = f"MMD_G{subkey[0]}_{subkey[1]}"
        if hasattr(cg, "vrm_name"):
            cg.vrm_name = cg_name
        elif hasattr(cg, "name"):
            cg.name = cg_name
        for rec in recs:
            ref = cg.colliders.add()
            if hasattr(ref, "collider_uuid"):
                ref.collider_uuid = rec["uuid"]
            elif hasattr(ref, "collider_name"):
                ref.collider_name = rec["name"]
        subkey_to_cg_ref[subkey] = (
            cg_uuid,
            getattr(cg, "vrm_name", getattr(cg, "name", cg_name)),
        )

    # 3. 建立 Springs，过滤零长度退化关节并按真实 seg_len 重算阻尼参数
    raw_center = snap.get("center_bone", "")
    center_bone = resolve_bone(raw_center) if raw_center else ""
    if center_bone not in bones:
        center_bone = "Root" if "Root" in bones else ""

    cat_counts = {"hair": 0, "bangs": 0, "skirt": 0, "bust": 0, "other": 0}
    created_springs = 0
    total_joints = 0
    masked_overlap_links = 0
    dropped_zero_joints = 0

    for idx, sp_spec in enumerate(snap.get("springs", [])):
        valid_joints = []
        seen_b = set()
        for j_spec in sp_spec.get("joints", []):
            bname = resolve_bone(j_spec["bone"])
            if bname not in bones or bname in seen_b:
                continue
            if valid_joints:
                prev_b = bones[valid_joints[-1]["bone"]]
                curr_b = bones[bname]
                if (curr_b.head_local - prev_b.head_local).length < 0.005:
                    dropped_zero_joints += 1
                    continue
            seen_b.add(bname)
            valid_joints.append(
                {
                    "bone": bname,
                    "hit_radius": j_spec.get("hit_radius", j_spec["params"][0]),
                    "sp_norm": j_spec.get("sp_norm", 0.35),
                }
            )
        if len(valid_joints) < 2:
            continue

        # 根据最终过滤后的真实链长与 seg_len 重算临界阻尼参数
        chain_len = max(1, len(valid_joints) - 1)
        resolved_joints = []
        for idx_j, j_info in enumerate(valid_joints):
            bname = j_info["bone"]
            b = bones[bname]
            if idx_j + 1 < len(valid_joints):
                nb = bones[valid_joints[idx_j + 1]["bone"]]
                seg_len = (nb.head_local - b.head_local).length
            else:
                prev_b = bones[valid_joints[idx_j - 1]["bone"]]
                seg_len = (b.head_local - prev_b.head_local).length
            params = _compute_damped_joint_params(
                bname,
                j_info["hit_radius"],
                j_info["sp_norm"],
                idx_j / chain_len,
                seg_len,
            )
            resolved_joints.append((bname, params))

        # 仅检测在 VRM 1.0 中实际受碰撞推挤的尾节点（j1..jn）
        moving_pts = []
        for idx_j in range(1, len(resolved_joints)):
            jb = bones[resolved_joints[idx_j][0]]
            j_hit_r = resolved_joints[idx_j - 1][1][0] * avg_arm_scale
            moving_pts.append((arm_mat @ jb.head_local, j_hit_r))

        sp = sb1.springs.add()
        sp_name = f"Spring_{resolved_joints[0][0]}_{idx}"
        if hasattr(sp, "vrm_name"):
            sp.vrm_name = sp_name
        elif hasattr(sp, "name"):
            sp.name = sp_name

        cat = _classify_spring_part(resolved_joints[0][0])
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

        local_center = pick_local_center(cat, resolved_joints[0][0])
        if local_center and local_center not in seen_b:
            if hasattr(sp, "center") and hasattr(sp.center, "bone_name"):
                sp.center.bone_name = local_center

        sp.joints.clear()
        for bname, params in resolved_joints:
            j = sp.joints.add()
            if hasattr(j, "node") and hasattr(j.node, "bone_name"):
                j.node.bone_name = bname
            hit_radius, stiffness, drag_force, gravity_power = params
            if hasattr(j, "hit_radius"):
                j.hit_radius = hit_radius
            if hasattr(j, "stiffness"):
                j.stiffness = stiffness
            if hasattr(j, "drag_force"):
                j.drag_force = drag_force
            if hasattr(j, "gravity_power"):
                j.gravity_power = gravity_power
            if hasattr(j, "gravity_dir"):
                j.gravity_dir = (0.0, 0.0, -1.0)
            total_joints += 1

        sp.collider_groups.clear()
        for grp_key in sp_spec.get("groups", []):
            for subkey in sorted(grp_to_subkeys.get(grp_key, set())):
                recs = col_records_by_subkey.get(subkey, [])
                overlaps = False
                for rec in recs:
                    for pt_w, j_hit_r in moving_pts:
                        d_w = (
                            _point_segment_distance(pt_w, rec["p_a"], rec["p_b"])
                            if rec["is_cap"]
                            else (pt_w - rec["p_a"]).length
                        )
                        if d_w < rec["r_world"] + j_hit_r + 0.015:
                            overlaps = True
                            break
                    if overlaps:
                        break
                if overlaps:
                    masked_overlap_links += 1
                    continue

                cg_ref = subkey_to_cg_ref.get(subkey)
                if cg_ref:
                    ref = sp.collider_groups.add()
                    if hasattr(ref, "collider_group_uuid"):
                        ref.collider_group_uuid = cg_ref[0]
                    elif hasattr(ref, "collider_group_name"):
                        ref.collider_group_name = cg_ref[1]
        created_springs += 1

    try:
        del armature_obj[SNAPSHOT_PROP]
    except Exception:
        pass

    seg_lens = []
    alphas = []
    centers_stat = {}
    for sp in sb1.springs:
        c_name = getattr(getattr(sp, "center", None), "bone_name", "") or "None"
        centers_stat[c_name] = centers_stat.get(c_name, 0) + 1
        j_list = list(sp.joints)
        for i_j in range(len(j_list) - 1):
            b = bones.get(j_list[i_j].node.bone_name)
            nb = bones.get(j_list[i_j + 1].node.bone_name)
            if not b or not nb:
                continue
            sl = (nb.head_local - b.head_local).length
            seg_lens.append(sl)
            if sl > 1e-4:
                alphas.append(j_list[i_j].stiffness / (60.0 * sl))

    sl_str = f"[{min(seg_lens):.3f}, {max(seg_lens):.3f}]" if seg_lens else "[]"
    al_str = f"[{min(alphas):.2f}, {max(alphas):.2f}]" if alphas else "[]"
    print(
        f"   🌸 [SpringBone 写入] springs={created_springs} 条（joints={total_joints} 个, 过滤零长={dropped_zero_joints} 个, 分布={cat_counts}, "
        f"seg_len={sl_str}, alpha60={al_str}, center={centers_stat}），"
        f"colliders={col_count} 个，colliderGroups={len(subkey_to_cg_ref)} 组，静息穿插免碰屏蔽={masked_overlap_links} 对。"
    )
    return created_springs, col_count


def extract_mmd_spring_bones_to_vrm(armature_obj=None, overwrite=False):
    armature_obj = armature_obj or next(
        (o for o in bpy.data.objects if o.type == "ARMATURE"), None
    )
    if not armature_obj:
        return 0, 0
    ext = getattr(armature_obj.data, "vrm_addon_extension", None)
    if not ext or not hasattr(ext, "spring_bone1"):
        return 0, 0
    if not overwrite and len(getattr(ext.spring_bone1, "springs", [])) > 0:
        return len(ext.spring_bone1.springs), len(
            getattr(ext.spring_bone1, "colliders", [])
        )

    if snapshot_mmd_physics_to_armature(armature_obj, overwrite=overwrite):
        return apply_mmd_spring_snapshot_to_vrm(armature_obj, overwrite=overwrite)
    return 0, 0
