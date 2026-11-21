import json
import math
import time

import bpy
from mathutils import Vector

from step1_bone_map import is_physics_or_spring_bone
from utils.spring_solver import solve_chain_spring_params
from utils.spring_utils import (
    BODY_COLLIDER_KEYWORDS,
    NON_SPRING_LIMB_KEYWORDS,
    SNAPSHOT_PROP,
    classify_chain_part_spatial,
    classify_collider_region,
    classify_spring_part,
    collect_extra_weighted_bust_chains,
    collect_linear_chains,
    collect_weighted_bones,
    compute_collider_armature_spec,
    create_vrm1_collider_entry,
    detect_model_forward_axis,
    ensure_uuid,
    extract_mmd_joint_hints,
    get_sb1,
    is_bust_bone_name,
    is_excluded_from_spring,
    is_valid_body_collider_bone,
    point_segment_distance,
    probe_bone_collider_basis,
    remap_mmd_collider_bone,
    set_enum_ci,
)

_classify_spring_part = classify_spring_part


def snapshot_mmd_physics_to_armature(armature_obj=None, overwrite=False):
    armature_obj = armature_obj or next(
        (o for o in bpy.data.objects if o.type == "ARMATURE"), None
    )
    if not armature_obj:
        return False
    if not overwrite and SNAPSHOT_PROP in armature_obj:
        return True

    bones = armature_obj.data.bones
    fwd_dir = detect_model_forward_axis(bones)
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
        physics_bones = {
            b.name
            for b in bones
            if (is_physics_or_spring_bone(b.name) or is_bust_bone_name(b.name))
            and not is_excluded_from_spring(b.name)
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
        chains = collect_linear_chains(roots, physics_bones)
        springs = []
        for idx, ch in enumerate(chains):
            part = classify_chain_part_spatial(ch, bones, fwd_dir)
            j_list = []
            for b in ch:
                hit_r, sp_norm = extract_mmd_joint_hints(None, None, part=part)
                j_list.append({"bone": b.name, "hit_radius": hit_r, "sp_norm": sp_norm})
            springs.append(
                {
                    "name": f"Spring_{ch[0].name}_{idx}",
                    "part": part,
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

    weighted_bones = collect_weighted_bones(armature_obj)
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
            target_bone = remap_mmd_collider_bone(raw_bone_name, bones, weighted_bones)
            if not is_valid_body_collider_bone(target_bone):
                skipped_non_body += 1
                continue
            spec = compute_collider_armature_spec(armature_obj, target_bone, rb_obj)
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

    physics_bones = {b for b in bone_to_rigid if not is_excluded_from_spring(b)}
    roots = [
        b
        for b in bones
        if b.name in physics_bones
        and (b.parent is None or b.parent.name not in physics_bones)
    ]
    chains = collect_linear_chains(roots, physics_bones)

    already_in_chains = {b.name for ch in chains for b in ch}
    extra_bust_chains = collect_extra_weighted_bust_chains(
        bones, weighted_bones, already_in_chains
    )
    chains.extend(extra_bust_chains)

    springs = []
    total_joints = 0
    cat_counts = {}
    for idx, ch in enumerate(chains):
        active_grps = set()
        joint_specs = []
        part = classify_chain_part_spatial(ch, bones, fwd_dir)
        cat_counts[part] = cat_counts.get(part, 0) + 1
        for b in ch:
            rb_obj = bone_to_rigid.get(b.name)
            j_obj = joint_by_rigid.get(rb_obj) if rb_obj else None
            hit_r, sp_norm = extract_mmd_joint_hints(rb_obj, j_obj, part=part)
            joint_specs.append(
                {"bone": b.name, "hit_radius": hit_r, "sp_norm": sp_norm}
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
                "part": part,
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
        f"   🌸 [SpringBone 快照] 缓存 {len(springs)} 条弹簧链（{total_joints} 个关节, 空间分布={cat_counts}, 补全胸链={len(extra_bust_chains)}），"
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


def get_snapshot_spring_roots_and_colliders(armature_obj):
    if not armature_obj or SNAPSHOT_PROP not in armature_obj:
        return set()
    try:
        snap = json.loads(armature_obj[SNAPSHOT_PROP])
    except Exception:
        return set()

    names = set()
    for cols in snap.get("collider_groups", {}).values():
        for c in cols:
            if c.get("bone"):
                names.add(c["bone"])
    for sp in snap.get("springs", []):
        joints = sp.get("joints", [])
        if joints and joints[0].get("bone"):
            names.add(joints[0]["bone"])
    return names


def apply_mmd_spring_snapshot_to_vrm(armature_obj, rename_map=None, overwrite=True):
    """按最终骨骼名重映射，补全缺失四肢胶囊碰撞，通过 Verlet 运动解算器收敛各向物理参数。"""
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
    sb1 = get_sb1(armature_obj)
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

    arm_mat = armature_obj.matrix_world
    arm_scale = arm_mat.to_scale()
    avg_arm_scale = max(
        1e-5, (abs(arm_scale.x) + abs(arm_scale.y) + abs(arm_scale.z)) / 3.0
    )

    basis_cache = {}

    def build_collider_entry(bname, is_cap, p_a_world, p_b_world, radius_arm):
        col = create_vrm1_collider_entry(armature_obj, bname)
        o0, basis_inv = probe_bone_collider_basis(
            col, armature_obj, bname, is_cap, basis_cache
        )
        off_a = basis_inv @ (p_a_world - o0)
        if is_cap:
            off_b = basis_inv @ (p_b_world - o0)
            set_enum_ci(col, "shape_type", "Capsule")
            col.shape.capsule.offset = (float(off_a.x), float(off_a.y), float(off_a.z))
            col.shape.capsule.tail = (float(off_b.x), float(off_b.y), float(off_b.z))
            col.shape.capsule.radius = radius_arm
        else:
            set_enum_ci(col, "shape_type", "Sphere")
            col.shape.sphere.offset = (float(off_a.x), float(off_a.y), float(off_a.z))
            col.shape.sphere.radius = radius_arm
        return {
            "uuid": ensure_uuid(col),
            "name": getattr(col, "name", ""),
            "bone": bname,
            "region": classify_collider_region(bname),
            "is_cap": is_cap,
            "p_a": p_a_world,
            "p_b": p_b_world,
            "r_world": radius_arm * avg_arm_scale,
        }

    col_records_by_subkey = {}
    grp_to_subkeys = {}
    subkeys_by_region = {}
    col_count = 0
    bones_with_colliders = set()

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
            rec = build_collider_entry(bname, is_cap, p_a_world, p_b_world, final_r)

            subkey = (grp_key, bname)
            col_records_by_subkey.setdefault(subkey, []).append(rec)
            grp_to_subkeys.setdefault(grp_key, set()).add(subkey)
            subkeys_by_region.setdefault(rec["region"], set()).add(subkey)
            bones_with_colliders.add(bname)
            col_count += 1

    # 自动补全原 MMD 漏绑的四肢胶囊碰撞体（大腿/小腿/大臂/小臂），防止踢腿挥手穿模
    auto_limb_cnt = 0
    limb_defaults = (
        ("UpperLegL", ("LowerLegL",), 0.058),
        ("UpperLegR", ("LowerLegR",), 0.058),
        ("LowerLegL", ("FootL",), 0.044),
        ("LowerLegR", ("FootR",), 0.044),
        ("UpperArmL", ("LowerArmL",), 0.042),
        ("UpperArmR", ("LowerArmR",), 0.042),
        ("LowerArmL", ("HandL",), 0.032),
        ("LowerArmR", ("HandR",), 0.032),
    )
    for bname, child_cands, def_r in limb_defaults:
        if bname not in bones or bname in bones_with_colliders:
            continue
        b_obj = bones[bname]
        ch_b = next((bones[c] for c in child_cands if c in bones), None)
        if not ch_b and b_obj.children:
            ch_b = b_obj.children[0]
        p_a_world = arm_mat @ b_obj.head_local
        p_b_world = arm_mat @ (ch_b.head_local if ch_b else b_obj.tail_local)
        if (p_b_world - p_a_world).length < 0.04:
            continue
        rec = build_collider_entry(bname, True, p_a_world, p_b_world, def_r)
        subkey = ("99", bname)
        col_records_by_subkey.setdefault(subkey, []).append(rec)
        grp_to_subkeys.setdefault("99", set()).add(subkey)
        subkeys_by_region.setdefault(rec["region"], set()).add(subkey)
        bones_with_colliders.add(bname)
        col_count += 1
        auto_limb_cnt += 1

    sb1 = get_sb1(armature_obj)
    subkey_to_cg_ref = {}
    for subkey, recs in sorted(
        col_records_by_subkey.items(), key=lambda x: (int(x[0][0]), x[0][1])
    ):
        cg = sb1.collider_groups.add()
        cg_uuid = ensure_uuid(cg)
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

    fitted_cg_cache = {}
    fitted_col_count = 0

    def get_fitted_cg_ref(subkey, recs, moving_pts):
        nonlocal fitted_col_count, col_count
        fitted_recs = []
        sig_parts = []
        for r_idx, rec in enumerate(recs):
            max_safe_r_w = rec["r_world"]
            for pt_w, j_hit_r in moving_pts:
                d_w = (
                    point_segment_distance(pt_w, rec["p_a"], rec["p_b"])
                    if rec["is_cap"]
                    else (pt_w - rec["p_a"]).length
                )
                max_safe_r_w = min(max_safe_r_w, d_w - j_hit_r - 0.002)

            if max_safe_r_w < 0.015:
                continue
            r_fit_arm = math.floor((max_safe_r_w / avg_arm_scale) / 0.005) * 0.005
            if r_fit_arm < 0.015:
                continue
            r_fit_arm = min(r_fit_arm, rec["r_world"] / avg_arm_scale)
            sig_parts.append((r_idx, round(r_fit_arm, 3)))
            fitted_recs.append((rec, r_fit_arm))

        if not fitted_recs:
            return None

        cache_key = (subkey, tuple(sig_parts))
        if cache_key in fitted_cg_cache:
            return fitted_cg_cache[cache_key]

        cg = sb1.collider_groups.add()
        cg_uuid = ensure_uuid(cg)
        cg_name = f"MMD_Fit_{subkey[0]}_{subkey[1]}_{len(fitted_cg_cache)}"
        if hasattr(cg, "vrm_name"):
            cg.vrm_name = cg_name
        elif hasattr(cg, "name"):
            cg.name = cg_name

        for rec, r_fit_arm in fitted_recs:
            f_rec = build_collider_entry(
                rec["bone"], rec["is_cap"], rec["p_a"], rec["p_b"], r_fit_arm
            )
            col_count += 1
            fitted_col_count += 1
            ref = cg.colliders.add()
            if hasattr(ref, "collider_uuid"):
                ref.collider_uuid = f_rec["uuid"]
            elif hasattr(ref, "collider_name"):
                ref.collider_name = f_rec["name"]

        cg_ref = (cg_uuid, getattr(cg, "vrm_name", getattr(cg, "name", cg_name)))
        fitted_cg_cache[cache_key] = cg_ref
        return cg_ref

    t_solve_start = time.perf_counter()
    cat_counts = {}
    cat_metrics = {}
    created_springs = 0
    total_joints = 0
    masked_overlap_links = 0
    fitted_overlap_links = 0
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
            default_r = j_spec["params"][0] if "params" in j_spec else 0.015
            valid_joints.append(
                {
                    "bone": bname,
                    "hit_radius": j_spec.get("hit_radius", default_r),
                    "sp_norm": j_spec.get("sp_norm", 0.35),
                }
            )
        if len(valid_joints) < 2:
            continue

        cat = sp_spec.get("part") or classify_spring_part(valid_joints[0]["bone"])
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

        seg_lens_chain = [
            (
                bones[valid_joints[i + 1]["bone"]].head_local
                - bones[valid_joints[i]["bone"]].head_local
            ).length
            for i in range(len(valid_joints) - 1)
        ]
        avg_sp = sum(j["sp_norm"] for j in valid_joints) / len(valid_joints)
        solved_params, metrics = solve_chain_spring_params(
            cat, seg_lens_chain, sp_norm=avg_sp
        )
        cat_metrics.setdefault(cat, []).append(metrics)

        resolved_joints = []
        for idx_j, j_info in enumerate(valid_joints):
            k_i, d_i, g_i = solved_params[idx_j]
            resolved_joints.append(
                (j_info["bone"], (j_info["hit_radius"], k_i, d_i, g_i))
            )

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

        candidate_subkeys = set()
        for grp_key in sp_spec.get("groups", []):
            candidate_subkeys.update(grp_to_subkeys.get(grp_key, set()))

        if cat in ("front_skirt", "side_skirt", "skirt"):
            candidate_subkeys.update(subkeys_by_region.get("lower_body", set()))
            candidate_subkeys.update(subkeys_by_region.get("arms", set()))
            for sk in subkeys_by_region.get("torso", set()):
                if "spine" in sk[1].lower() or "下半身" in sk[1] or "腰" in sk[1]:
                    candidate_subkeys.add(sk)
        elif cat == "sleeve":
            candidate_subkeys.update(subkeys_by_region.get("arms", set()))
            candidate_subkeys.update(subkeys_by_region.get("torso", set()))
        elif cat in ("hair", "bangs"):
            candidate_subkeys.update(subkeys_by_region.get("head", set()))
            candidate_subkeys.update(subkeys_by_region.get("arms", set()))
        elif cat == "bust":
            candidate_subkeys = {
                sk
                for sk in candidate_subkeys
                if sk not in subkeys_by_region.get("torso", set())
                and sk not in subkeys_by_region.get("lower_body", set())
                and sk not in subkeys_by_region.get("head", set())
            }

        sp.collider_groups.clear()
        added_cg_uuids = set()
        for subkey in sorted(candidate_subkeys, key=lambda x: (int(x[0]), x[1])):
            recs = col_records_by_subkey.get(subkey, [])
            if not recs:
                continue
            overlaps = False
            for rec in recs:
                for pt_w, j_hit_r in moving_pts:
                    d_w = (
                        point_segment_distance(pt_w, rec["p_a"], rec["p_b"])
                        if rec["is_cap"]
                        else (pt_w - rec["p_a"]).length
                    )
                    if d_w < rec["r_world"] + j_hit_r - 0.002:
                        overlaps = True
                        break
                if overlaps:
                    break

            if overlaps:
                cg_ref = get_fitted_cg_ref(subkey, recs, moving_pts)
                if cg_ref:
                    fitted_overlap_links += 1
                else:
                    masked_overlap_links += 1
                    continue
            else:
                cg_ref = subkey_to_cg_ref.get(subkey)

            if cg_ref and cg_ref[0] not in added_cg_uuids:
                added_cg_uuids.add(cg_ref[0])
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
        f"   🧮 [运动解算器收敛] 耗时 {time.perf_counter() - t_solve_start:.2f}s | "
        f"seg_len={sl_str}, alpha60={al_str}"
    )
    for part_k, m_list in cat_metrics.items():
        if not m_list:
            continue
        max_w = max(m["walk_deg"] for m in m_list)
        max_s = max(m["sway_deg"] for m in m_list)
        avg_mp = sum(m["overshoot"] for m in m_list) / len(m_list) * 100.0
        avg_t = sum(m["settle_time"] for m in m_list) / len(m_list)
        ok_cnt = sum(1 for m in m_list if m["stable_30fps"])
        print(
            f"      - {part_k}({len(m_list)}条): 行走最大后仰={max_w:.1f}°, "
            f"左右峰值摆角={max_s:.1f}°, 平均回弹={avg_mp:.0f}%, 稳定时间={avg_t:.2f}s, "
            f"30fps稳定={ok_cnt}/{len(m_list)}"
        )
    print(
        f"   🌸 [SpringBone 写入] springs={created_springs} 条（joints={total_joints} 个, 过滤零长={dropped_zero_joints} 个, 分布={cat_counts}, center={centers_stat}），"
        f"colliders={col_count} 个（自动补全四肢+{auto_limb_cnt}个, 微缩贴合+{fitted_col_count}个），"
        f"colliderGroups={len(subkey_to_cg_ref) + len(fitted_cg_cache)} 组，"
        f"穿插微缩保碰={fitted_overlap_links} 对 / 彻底免碰={masked_overlap_links} 对。"
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
