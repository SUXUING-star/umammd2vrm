import math
import re
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

NON_SPRING_LIMB_KEYWORDS = (
    "hips",
    "spine",
    "chest",
    "upperchest",
    "neck",
    "head",
    "pelvis",
    "root",
    "全ての親",
    "全ての亲",
    "センター",
    "腰",
    "下半身",
    "上半身",
    "首",
    "頭",
    "头",
    "目",
    "指",
    "腕",
    "ひじ",
    "手首",
    "shoulder",
    "arm",
    "hand",
    "足",
    "ひざ",
    "足首",
    "つま先",
    "leg",
    "foot",
    "toe",
    "ankle",
    "shoe",
    "boot",
    "heel",
    "sock",
    "stocking",
    "knee",
    "thigh",
    "calf",
    "靴",
    "鞋",
    "袜",
)

BUST_KEYWORDS = (
    "bust",
    "boob",
    "oppai",
    "breast",
    "mune",
    "乳",
    "おっぱい",
)

_BUST_DECOR_EXCLUSIONS = (
    "饰",
    "飾",
    "花",
    "带",
    "帯",
    "链",
    "鎖",
    "铃",
    "鈴",
    "扣",
    "纽",
    "紐",
    "甲",
    "铠",
    "鎧",
    "衣",
    "服",
    "襟",
    "领",
    "領",
    "结",
    "結",
    "リボン",
    "フリル",
    "ribbon",
    "brooch",
    "pin",
    "bow",
    "tie",
    "charm",
    "bell",
    "lace",
    "frill",
    "collar",
    "armor",
    "cloth",
    "gem",
    "skirt",
    "sleeve",
)


def is_ancestor(bone, maybe_ancestor):
    cur = bone.parent
    while cur:
        if cur == maybe_ancestor:
            return True
        cur = cur.parent
    return False


def is_bust_bone_name(bone_name: str) -> bool:
    low = bone_name.lower()
    if any(ex in low for ex in _BUST_DECOR_EXCLUSIONS):
        return False
    if any(k in low for k in BUST_KEYWORDS):
        return True
    if "胸" in low:
        if low in ("胸", "胸部", "上半身", "上半身2", "上半身3"):
            return False
        return True
    if re.search(r"(^|[_\.\-\s])chest[_\.\-\s]*(l|r|left|right)($|[_\.\-\s\d])", low):
        return True
    if re.search(r"(^|[_\.\-\s])(left|right|l|r)[_\.\-\s]+chest($|[_\.\-\s\d])", low):
        return True
    return False


def is_excluded_from_spring(bone_name: str) -> bool:
    low = bone_name.lower()
    if is_bust_bone_name(bone_name):
        return False
    if any(
        sk in low
        for sk in (
            "skirt",
            "スカート",
            "裙",
            "cape",
            "マント",
            "ribbon",
            "リボン",
            "frill",
            "フリル",
            "sleeve",
            "袖",
            "earring",
            "headband",
            "armlet",
            "hair",
            "髪",
            "发",
        )
    ):
        return False
    if re.search(
        r"(?:^|[_\.\-\s])(thumb|index|middle|ring|little)(?:finger|[_\.\-\s\d]|$)", low
    ):
        return True
    if re.search(r"(?:^|[_\.\-\s])eye(?:[_\.\-\s\d]|$)", low):
        return True
    return any(kw in low for kw in NON_SPRING_LIMB_KEYWORDS)


def classify_spring_part(name: str) -> str:
    if is_bust_bone_name(name):
        return "bust"
    low = name.lower()
    if any(k in low for k in ("袖", "sleeve", "sode", "cuff")):
        return "sleeve"
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
            "coat",
            "apron",
            "エプロン",
            "frill",
            "フリル",
            "披风",
        )
    ):
        return "skirt"
    return "other"


def detect_model_forward_axis(bones):
    """通过眼睛/脚尖相对头部/脚踝的 3D 向量自动判定角色真实正前方（默认 -Y）。"""
    head = next((bones[c] for c in ("Head", "頭", "头") if c in bones), None)
    eyes = [
        bones[c]
        for c in ("LeftEye", "RightEye", "Eye_L", "Eye_R", "左目", "右目")
        if c in bones
    ]
    if head and eyes:
        avg_eye = sum((e.head_local for e in eyes), Vector((0.0, 0.0, 0.0))) / len(eyes)
        v = Vector((avg_eye.x - head.head_local.x, avg_eye.y - head.head_local.y, 0.0))
        if v.length > 0.005:
            return v.normalized()

    foot = next((bones[c] for c in ("FootL", "左足首D", "左足首") if c in bones), None)
    toe = next(
        (bones[c] for c in ("ToesL", "左つま先", "左足先", "左つま先D") if c in bones),
        None,
    )
    if foot and toe:
        v = Vector(
            (
                toe.head_local.x - foot.head_local.x,
                toe.head_local.y - foot.head_local.y,
                0.0,
            )
        )
        if v.length > 0.005:
            return v.normalized()

    return Vector((0.0, -1.0, 0.0))


def classify_chain_part_spatial(chain_bones, bones, fwd_dir):
    """结合骨骼名与 3D 前/侧/后空间位置区分前发、前裙摆、侧裙摆、后裙摆、袖子。"""
    base = classify_spring_part(chain_bones[0].name)
    if base in ("bust", "sleeve"):
        return base

    names_low = " ".join(b.name.lower() for b in chain_bones)
    p_mid = sum((b.head_local for b in chain_bones), Vector((0.0, 0.0, 0.0))) / len(
        chain_bones
    )

    head_b = next(
        (bones[c] for c in ("Head", "頭", "头", "Neck", "首") if c in bones), None
    )
    hips_b = next(
        (bones[c] for c in ("Hips", "下半身", "腰", "Pelvis") if c in bones), None
    )

    if base in ("hair", "bangs"):
        if base == "bangs" or any(
            k in names_low
            for k in (
                "front",
                "mae",
                "前_",
                "_前",
                "前髪",
                "髪_前",
                "刘海",
                "liuhai",
                "bang",
            )
        ):
            return "bangs"
        if any(k in names_low for k in ("back", "ushiro", "後", "后")):
            return "hair"
        if head_b:
            fwd_off = (p_mid.x - head_b.head_local.x) * fwd_dir.x + (
                p_mid.y - head_b.head_local.y
            ) * fwd_dir.y
            if fwd_off > 0.015:
                return "bangs"
        return "hair"

    if base == "skirt":
        if any(k in names_low for k in ("front", "mae", "前_", "_前", "前裙", "前垂")):
            return "front_skirt"
        if any(
            k in names_low
            for k in ("back", "ushiro", "後", "后", "后裙", "披风", "cape", "マント")
        ):
            return "skirt"
        if hips_b:
            fwd_off = (p_mid.x - hips_b.head_local.x) * fwd_dir.x + (
                p_mid.y - hips_b.head_local.y
            ) * fwd_dir.y
            if fwd_off > 0.025:
                return "front_skirt"
            if fwd_off >= -0.025:
                return "side_skirt"
        return "skirt"

    return base


def call_vrm_op(op_name, **kwargs):
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


def get_sb1(armature_obj):
    return armature_obj.data.vrm_addon_extension.spring_bone1


def set_enum_ci(prop_owner, prop_name, target):
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


def ensure_uuid(item):
    if hasattr(item, "uuid"):
        cur = getattr(item, "uuid", "")
        if not cur:
            item.uuid = uuid.uuid4().hex
        return item.uuid
    return ""


def is_valid_body_collider_bone(bone_name):
    if is_bust_bone_name(bone_name):
        return False
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


def classify_collider_region(bone_name: str) -> str:
    low = bone_name.lower()
    if any(
        k in low
        for k in (
            "hips",
            "pelvis",
            "upperleg",
            "lowerleg",
            "foot",
            "下半身",
            "腰",
            "足",
            "ひざ",
            "足首",
        )
    ):
        return "lower_body"
    if any(k in low for k in ("head", "頭", "头")):
        return "head"
    if any(
        k in low
        for k in (
            "shoulder",
            "upperarm",
            "lowerarm",
            "hand",
            "肩",
            "腕",
            "ひじ",
            "手首",
        )
    ):
        return "arms"
    if any(
        k in low for k in ("spine", "chest", "upperchest", "neck", "上半身", "胸", "首")
    ):
        return "torso"
    return "other"


def collect_weighted_bones(armature_obj):
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


def remap_mmd_collider_bone(bone_name, bones, weighted_bones):
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


def get_mmd_rigid_dimensions(rb_obj):
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


def compute_collider_armature_spec(armature_obj, target_bone_name, rb_obj):
    """记录碰撞体在 Armature 空间下相对于 bone.head_local 的偏移，完全脱离 bone.matrix_local 旋转。"""
    bone = armature_obj.data.bones.get(target_bone_name)
    if not bone:
        return None

    shape, dims, (sx, sy, sz) = get_mmd_rigid_dimensions(rb_obj)
    arm_inv = armature_obj.matrix_world.inverted()
    arm_scale = armature_obj.matrix_world.to_scale()
    avg_arm_scale = max(
        1e-5, (abs(arm_scale.x) + abs(arm_scale.y) + abs(arm_scale.z)) / 3.0
    )
    head_arm = bone.head_local

    if shape == "SPHERE":
        radius = dims[0] / avg_arm_scale
        if radius <= 0.004 or radius > 0.32:
            return None
        radius = min(radius, 0.22)
        d = (arm_inv @ rb_obj.matrix_world.translation) - head_arm
        return {
            "bone": target_bone_name,
            "shape": "Sphere",
            "delta_arm": [float(d.x), float(d.y), float(d.z)],
            "radius": float(radius),
        }

    if shape == "CAPSULE":
        radius = dims[0] / avg_arm_scale
        if radius <= 0.004 or radius > 0.32:
            return None
        radius = min(radius, 0.22)
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
    if radius <= 0.005 or radius > 0.30:
        return None
    radius = min(radius, 0.20)

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


def extract_mmd_joint_hints(rb_obj, joint_obj, part="other"):
    # 增大布料/前发防穿模缓冲半径，避免 8mm 细球在腿手快速运动时被瞬间穿过
    if part in ("front_skirt", "side_skirt", "skirt"):
        hit_radius = 0.025
    elif part == "sleeve":
        hit_radius = 0.020
    elif part in ("bangs", "hair"):
        hit_radius = 0.016
    elif part == "bust":
        hit_radius = 0.010
    else:
        hit_radius = 0.015

    if rb_obj is not None:
        shape, dims, _ = get_mmd_rigid_dimensions(rb_obj)
        raw_r = (
            dims[0]
            if shape in ("SPHERE", "CAPSULE")
            else min(dims[0], dims[1], dims[2])
        )
        if part in ("front_skirt", "side_skirt", "skirt"):
            hit_radius = max(0.022, min(0.032, float(raw_r) * 0.65))
        elif part == "sleeve":
            hit_radius = max(0.018, min(0.028, float(raw_r) * 0.55))
        elif part in ("bangs", "hair"):
            hit_radius = max(0.014, min(0.024, float(raw_r) * 0.45))
        elif part == "bust":
            hit_radius = max(0.008, min(0.016, float(raw_r) * 0.35))
        else:
            hit_radius = max(0.012, min(0.024, float(raw_r) * 0.48))

    mmd_sp = 0.0
    if joint_obj is not None:
        mmd_j = getattr(joint_obj, "mmd_joint", None)
        if mmd_j and hasattr(mmd_j, "spring_angular"):
            mmd_sp = sum(abs(float(x)) for x in mmd_j.spring_angular) / 3.0

    sp_norm = min(1.0, math.log10(1.0 + mmd_sp) / 2.5) if mmd_sp > 0.0 else 0.35
    return float(hit_radius), float(sp_norm)


def collect_linear_chains(roots, physics_bones):
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
            if len(current_chain) >= 2 or (
                len(current_chain) == 1
                and classify_spring_part(current_chain[0].name) == "bust"
            ):
                chains.append(current_chain)

    for r in roots:
        walk(r, [])
    return chains


def collect_extra_weighted_bust_chains(bones, weighted_bones, already_in_chains):
    torso_and_limb_tips = [
        bones[c]
        for c in (
            "Head",
            "Neck",
            "頭",
            "头",
            "首",
            "左腕",
            "右腕",
            "UpperArmL",
            "UpperArmR",
        )
        if c in bones
    ]
    bust_cands = set()
    for b in bones:
        if b.name in already_in_chains:
            continue
        if weighted_bones.get(b.name, 0) <= 0:
            continue
        if not is_bust_bone_name(b.name):
            continue
        if any(is_ancestor(tip, b) or tip == b for tip in torso_and_limb_tips):
            continue
        bust_cands.add(b.name)

    if not bust_cands:
        return []

    roots = [
        bones[bn]
        for bn in bust_cands
        if bones[bn].parent is None or bones[bn].parent.name not in bust_cands
    ]
    return collect_linear_chains(roots, bust_cands)


def point_segment_distance(p, a, b):
    ab = b - a
    len_sq = ab.length_squared
    if len_sq < 1e-10:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / len_sq))
    proj = a + ab * t
    return (p - proj).length


def create_vrm1_collider_entry(armature_obj, bone_name):
    sb1 = get_sb1(armature_obj)
    before_len = len(sb1.colliders)
    ok = call_vrm_op(
        "add_spring_bone1_collider",
        armature_object_name=armature_obj.name,
        armature_name=armature_obj.name,
        bone_name=bone_name,
    )
    sb1 = get_sb1(armature_obj)
    col = (
        sb1.colliders[-1]
        if (ok and len(sb1.colliders) > before_len)
        else sb1.colliders.add()
    )
    ensure_uuid(col)

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


def probe_bone_collider_basis(col, armature_obj, bone_name, is_capsule, cache):
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
        set_enum_ci(col, "shape_type", "Capsule")
        col.shape.capsule.offset = (0.0, 0.0, 0.0)
        col.shape.capsule.tail = (0.0, 0.0, 0.05)
    else:
        set_enum_ci(col, "shape_type", "Sphere")
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
