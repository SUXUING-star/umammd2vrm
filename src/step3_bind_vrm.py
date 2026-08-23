import bpy


def run():
    print(">>> [步骤 3/4] 开始将标准表情绑定 to VRM 表情系统中...")

    armature_obj = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    mesh_obj = None
    if armature_obj:
        for child in armature_obj.children:
            if child.type == "MESH" and child.data.shape_keys:
                if len(child.data.shape_keys.key_blocks) > 50:
                    mesh_obj = child
                    break

    if not armature_obj or not mesh_obj:
        print("⚠️ 警告：未找到骨骼或网格，跳过 VRM 绑定。")
        return

    ext = getattr(armature_obj.data, "vrm_addon_extension", None)
    if not ext:
        print("⚠️ 警告：未开启 VRM 插件，跳过绑定。")
        return

    shape_keys = {kb.name: kb for kb in mesh_obj.data.shape_keys.key_blocks}

    def find_keys(*keywords):
        matched = []
        for name in shape_keys.keys():
            for kw in keywords:
                if kw.lower() in name.lower():
                    matched.append(name)
                    break
        return matched

    # 🎯 关键修复：从 WaraiB 中过滤掉所有嘴巴形态（Mouth/kuti/lip），只保留眼睛和眉毛的放松笑意，防止张大嘴
    relaxed_fun_keys = [
        k
        for k in find_keys("WaraiB")
        if not any(kw in k.lower() for kw in ["mouth", "kuti", "lip", "口"])
    ]

    STANDARD_MAP_VRM0 = {
        "a": find_keys("TalkA_A_L"),
        "i": find_keys("TalkA_I_L"),
        "u": find_keys("TalkA_U_L"),
        "e": find_keys("TalkA_E_L"),
        "o": find_keys("TalkA_O_L"),
        "blink": find_keys("CloseA"),
        "blink_l": [k for k in find_keys("CloseA") if "Eye_2_L" in k],
        "blink_r": [k for k in find_keys("CloseA") if "Eye_2_R" in k],
        "joy": find_keys("WaraiA", "Ear_9_R(Tanosi)", "Ear_9_L(Tanosi)"),
        "angry": find_keys("IkariA", "Ear_8_R(Ikari)", "Ear_8_L(Ikari)"),
        "sorrow": find_keys("KanasiA", "Ear_2_R(Kanasi)", "Ear_2_L(Kanasi)"),
        "fun": relaxed_fun_keys,  # 不再包含张嘴形态
    }

    STANDARD_MAP_VRM1 = {
        "aa": STANDARD_MAP_VRM0["a"],
        "ih": STANDARD_MAP_VRM0["i"],
        "ou": STANDARD_MAP_VRM0["u"],
        "ee": STANDARD_MAP_VRM0["e"],
        "oh": STANDARD_MAP_VRM0["o"],
        "blink": STANDARD_MAP_VRM0["blink"],
        "blink_left": STANDARD_MAP_VRM0["blink_l"],
        "blink_right": STANDARD_MAP_VRM0["blink_r"],
        "happy": STANDARD_MAP_VRM0["joy"],
        "angry": STANDARD_MAP_VRM0["angry"],
        "sad": STANDARD_MAP_VRM0["sorrow"],
        "relaxed": STANDARD_MAP_VRM0["fun"],  # 对应闭嘴/纯眼眉放松
    }

    bound_keys_set = set()

    # ================= 绑定 VRM 0.x =================
    if hasattr(ext, "vrm0") and hasattr(ext.vrm0, "blend_shape_master"):
        vrm0_bsm = ext.vrm0.blend_shape_master
        vrm0_groups = vrm0_bsm.blend_shape_groups
        vrm0_groups.clear()

        for preset_name, matched_keys in STANDARD_MAP_VRM0.items():
            if not matched_keys:
                continue
            group = vrm0_groups.add()
            group.name = preset_name
            group.preset_name = preset_name
            for key_name in matched_keys:
                bind = group.binds.add()
                bind.mesh.mesh_object_name = mesh_obj.name
                bind.index = key_name

                if "mouth_" in key_name.lower():
                    bind.weight = 55.0 if hasattr(bind, "weight") else 0.55
                else:
                    bind.weight = 100.0 if hasattr(bind, "weight") else 1.0
                bound_keys_set.add(key_name)

        # 额外绑定 surprised 表情
        surprised_keys = find_keys("OdorokiA", "Ear_6_R(Biku)", "Ear_6_L(Biku)")
        if surprised_keys:
            group = vrm0_groups.add()
            group.name = "surprised"
            group.preset_name = "unknown"
            for key_name in surprised_keys:
                bind = group.binds.add()
                bind.mesh.mesh_object_name = mesh_obj.name
                bind.index = key_name

                if "mouth_" in key_name.lower():
                    bind.weight = 55.0 if hasattr(bind, "weight") else 0.55
                else:
                    bind.weight = 100.0 if hasattr(bind, "weight") else 1.0
                bound_keys_set.add(key_name)

    # ================= 绑定 VRM 1.0 =================
    if hasattr(ext, "vrm1") and hasattr(ext.vrm1, "expressions"):
        vrm1_p = ext.vrm1.expressions.preset

        for preset_attr, matched_keys in STANDARD_MAP_VRM1.items():
            if not matched_keys or not hasattr(vrm1_p, preset_attr):
                continue
            expr_item = getattr(vrm1_p, preset_attr)
            if hasattr(expr_item, "morph_target_binds"):
                expr_item.morph_target_binds.clear()
                for key_name in matched_keys:
                    bind = expr_item.morph_target_binds.add()
                    bind.node.bpy_object = mesh_obj
                    bind.index = key_name

                    if "mouth_" in key_name.lower():
                        bind.weight = 0.55
                    else:
                        bind.weight = 1.0
                    bound_keys_set.add(key_name)

        surprised_keys = find_keys("OdorokiA", "Ear_6_R(Biku)", "Ear_6_L(Biku)")
        if surprised_keys and hasattr(vrm1_p, "surprised"):
            expr_item = vrm1_p.surprised
            if hasattr(expr_item, "morph_target_binds"):
                expr_item.morph_target_binds.clear()
                for key_name in surprised_keys:
                    bind = expr_item.morph_target_binds.add()
                    bind.node.bpy_object = mesh_obj
                    bind.index = key_name

                    if "mouth_" in key_name.lower():
                        bind.weight = 0.55
                    else:
                        bind.weight = 1.0
                    bound_keys_set.add(key_name)

    print(
        f"✅ [步骤 3/4] 表情与马耳联动绑定成功！已安全保护并记录了 {len(bound_keys_set)} 个表情组件形态键。"
    )

    # ------------------ 步骤 3.5 瘦身防卡死清理 ------------------
    print(">>> [步骤 3.5/4] 开始清理未调用的冗余形态键与 NLA 动画...")

    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and obj != mesh_obj:
            if obj.parent != mesh_obj.parent:
                bpy.data.objects.remove(obj, do_unlink=True)

    if mesh_obj and mesh_obj.data.shape_keys:
        key_blocks = mesh_obj.data.shape_keys.key_blocks
        keys_to_delete = []
        for key in key_blocks:
            k_name_lower = key.name.lower()
            if k_name_lower in ["basis", "base", "基础"]:
                continue
            if key.name in bound_keys_set:
                continue

            if (
                "toothhide" in k_name_lower
                or "eyelidhide" in k_name_lower
                or "normal" in k_name_lower
            ):
                continue

            keys_to_delete.append(key)

        print(
            f"正在从网格 [{mesh_obj.name}] 彻底清理 {len(keys_to_delete)} 个未使用的冗余形态键..."
        )
        for key in keys_to_delete:
            mesh_obj.shape_key_remove(key)

    for obj in bpy.data.objects:
        if obj.animation_data:
            obj.animation_data_clear()

    try:
        bpy.ops.outliner.orphans_purge(
            do_local_ids=True, do_linked_ids=True, do_recursive=True
        )
    except Exception:
        pass

    print("✅ [步骤 3.5/4] 瘦身与防卡死清理完成！")
