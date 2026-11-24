import json
import re
import time

import bpy

from step0_springbone import (
    SNAPSHOT_PROP,
    apply_mmd_spring_snapshot_to_vrm,
    get_snapshot_spring_roots_and_colliders,
    snapshot_mmd_physics_to_armature,
)
from step1_bone_map import (
    BASE_BONE_RENAME_MAP,
    FLATTEN_CONTROL_BONES,
    GARBAGE_BONE_KEYWORDS,
    is_physics_or_spring_bone,
    translate_non_ascii_bone_name,
)
from utils.skeleton_utils import (
    apply_high_heel_retarget_fix,
    collect_existing_spring_bone_names,
    collect_weighted_bone_names,
    decimate_spring_chains_budgeted,
    ensure_bust_tip_bones,
    ensure_object_mode,
    find_first_bone,
    get_bound_meshes,
    ground_model_to_z0,
    is_ancestor,
    merge_excess_bones_to_limit,
    resolve_torso_chain,
    safe_rename_bone,
    validate_and_assign_vrm_humanoid,
)


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
        ensure_object_mode(armature_obj)
        for m in bound_meshes:
            ensure_object_mode(m)
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

        ensure_bust_tip_bones(armature_obj, final_rename_map)

        collider_bones = set()
        if SNAPSHOT_PROP in armature_obj:
            try:
                _snap = json.loads(armature_obj[SNAPSHOT_PROP])
                for cols in _snap.get("collider_groups", {}).values():
                    for c in cols:
                        if c.get("bone"):
                            collider_bones.add(
                                final_rename_map.get(c["bone"], c["bone"])
                            )
            except Exception:
                pass
        if not collider_bones:
            collider_bones = {
                final_rename_map.get(n, n)
                for n in get_snapshot_spring_roots_and_colliders(armature_obj)
            }

        protected_human_base = (
            set(assigned.values()) | {"Root", "Pelvis"} | collider_bones
        )

        budget_cnt, budget_map, surviving_spring_bones = (
            decimate_spring_chains_budgeted(
                armature_obj,
                protected_human_base,
                max_bones=max_bones,
                bound_meshes=bound_meshes,
                rename_map=final_rename_map,
            )
        )
        for src_b, dst_b in budget_map.items():
            record_rename(src_b, dst_b)

        protected_final = protected_human_base | surviving_spring_bones
        extra_cnt, extra_map = merge_excess_bones_to_limit(
            armature_obj,
            protected_final,
            max_bones=max_bones,
            bound_meshes=bound_meshes,
        )
        for src_b, dst_b in extra_map.items():
            record_rename(src_b, dst_b)
        merged_cnt = budget_cnt + extra_cnt

        if merged_cnt > 0:
            assigned = validate_and_assign_vrm_humanoid(
                armature_obj, skip_toes=skip_toes
            )

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
