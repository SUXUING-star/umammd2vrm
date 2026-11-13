import bpy

from step2_expressions import get_armature_and_shape_meshes


def is_mouth_key(name: str) -> bool:
    low = name.lower()
    return any(kw in low for kw in ["mouth", "kuti", "lip", "talk", "口", "歯", "舌"])


def is_eye_closing_key(name: str) -> bool:
    low = name.lower()
    return any(
        kw in low
        for kw in [
            "close",
            "warai",
            "blink",
            "まばたき",
            "ウィンク",
            "ウインク",
            "笑い",
            "にこり",
        ]
    )


def get_key_weight(key_name: str, is_vrm0: bool) -> float:
    w = 0.55 if "mouth_" in key_name.lower() else 1.0
    return round(w * 100.0, 2) if is_vrm0 else w


def match_keys_in_meshes(
    mesh_objs,
    exact_names=(),
    substrings=(),
    exclude_substrings=(),
    prefer_first_per_mesh=False,
):
    results = []
    exact_low = {e.lower() for e in exact_names}
    subs_low = [s.lower() for s in substrings]
    excl_low = [e.lower() for e in exclude_substrings]

    for mesh_obj in mesh_objs:
        if not mesh_obj.data or not mesh_obj.data.shape_keys:
            continue
        mesh_hits = []
        for kb in mesh_obj.data.shape_keys.key_blocks:
            k_low = kb.name.lower()
            if k_low in ["basis", "base", "基础", "ベース"]:
                continue
            if any(ex in k_low for ex in excl_low):
                continue

            if k_low in exact_low or any(sub in k_low for sub in subs_low):
                mesh_hits.append(kb.name)

        if mesh_hits:
            if prefer_first_per_mesh:
                mesh_hits.sort(
                    key=lambda n: (0 if n.lower() in exact_low else 1, len(n))
                )
                results.append((mesh_obj, mesh_hits[0]))
            else:
                for k_name in mesh_hits:
                    results.append((mesh_obj, k_name))

    return results


def set_vrm0_preset_safe(group, preset_name):
    try:
        prop = group.bl_rna.properties.get("preset_name")
        if prop and prop.type == "ENUM":
            valid = {item.identifier for item in prop.enum_items}
            if preset_name in valid:
                group.preset_name = preset_name
                return
    except Exception:
        pass
    group.preset_name = "unknown"


def set_vrm1_bind_node(bind, mesh_obj):
    if hasattr(bind.node, "mesh_object_name"):
        bind.node.mesh_object_name = mesh_obj.name
    if hasattr(bind.node, "bpy_object"):
        try:
            bind.node.bpy_object = mesh_obj
        except Exception:
            pass


def set_vrm1_override(expr_item, attr_name, target_value="block"):
    if not hasattr(expr_item, attr_name):
        return
    try:
        prop = expr_item.bl_rna.properties.get(attr_name)
        if prop and prop.type == "ENUM":
            for item in prop.enum_items:
                if item.identifier.lower() == target_value.lower():
                    setattr(expr_item, attr_name, item.identifier)
                    return
    except Exception:
        pass


def run():
    print(">>> [步骤 3/4] 开始将标准表情绑定到 VRM 表情系统中...")

    armature_obj, mesh_objs = get_armature_and_shape_meshes()
    if not armature_obj or not mesh_objs:
        print("⚠️ 警告：未找到骨骼或含形态键网格，跳过 VRM 绑定。")
        return

    ext = getattr(armature_obj.data, "vrm_addon_extension", None)
    if not ext:
        print("⚠️ 警告：未开启 VRM 插件，跳过绑定。")
        return

    # 1. 映射 VRM 标准表情（兼容马娘命名 + 通用日/英 MMD 命名）
    lip_a = match_keys_in_meshes(
        mesh_objs,
        exact_names=("TalkA_A_L", "TalkA_A", "あ", "A", "aa"),
        substrings=("TalkA_A_L", "TalkA_A", "Mouth_A", "kuti_a", "あ2", "あ"),
        prefer_first_per_mesh=True,
    )
    lip_i = match_keys_in_meshes(
        mesh_objs,
        exact_names=("TalkA_I_L", "TalkA_I", "い", "I", "ih"),
        substrings=("TalkA_I_L", "TalkA_I", "Mouth_I", "kuti_i", "い"),
        prefer_first_per_mesh=True,
    )
    lip_u = match_keys_in_meshes(
        mesh_objs,
        exact_names=("TalkA_U_L", "TalkA_U", "う", "U", "ou"),
        substrings=("TalkA_U_L", "TalkA_U", "Mouth_U", "kuti_u", "う"),
        prefer_first_per_mesh=True,
    )
    lip_e = match_keys_in_meshes(
        mesh_objs,
        exact_names=("TalkA_E_L", "TalkA_E", "え", "E", "ee"),
        substrings=("TalkA_E_L", "TalkA_E", "Mouth_E", "kuti_e", "え"),
        prefer_first_per_mesh=True,
    )
    lip_o = match_keys_in_meshes(
        mesh_objs,
        exact_names=("TalkA_O_L", "TalkA_O", "お", "O", "oh"),
        substrings=("TalkA_O_L", "TalkA_O", "Mouth_O", "kuti_o", "お"),
        prefer_first_per_mesh=True,
    )

    blink_all = match_keys_in_meshes(
        mesh_objs,
        exact_names=("CloseA", "まばたき", "blink"),
        substrings=("CloseA", "まばたき", "Eye_Close"),
        exclude_substrings=("_L", "_R", "右", "左", "left", "right"),
    )
    blink_l = match_keys_in_meshes(
        mesh_objs,
        exact_names=("ウィンク", "ウィンク左", "ウインク", "blink_l", "blink_left"),
        substrings=("Eye_2_L", "CloseA_L", "ウィンク", "ウインク", "blink_l"),
        exclude_substrings=("右", "_R", "right"),
    )
    blink_r = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "ウィンク右",
            "ウィンク２",
            "ウィンク2",
            "ウインク右",
            "blink_r",
            "blink_right",
        ),
        substrings=(
            "Eye_2_R",
            "CloseA_R",
            "ウィンク右",
            "ウィンク2",
            "ウィンク２",
            "ウインク右",
            "blink_r",
        ),
    )
    if not blink_all:
        blink_all = match_keys_in_meshes(mesh_objs, substrings=("CloseA", "まばたき"))

    joy_pairs = match_keys_in_meshes(
        mesh_objs,
        exact_names=("笑い", "にこり", "笑顔", "joy", "happy"),
        substrings=(
            "WaraiA",
            "Ear_9_R(Tanosi)",
            "Ear_9_L(Tanosi)",
            "笑い",
            "にこり",
            "笑顔",
        ),
    )
    angry_pairs = match_keys_in_meshes(
        mesh_objs,
        exact_names=("怒り", "おこ", "angry"),
        substrings=("IkariA", "Ear_8_R(Ikari)", "Ear_8_L(Ikari)", "怒り", "おこ"),
    )
    sorrow_pairs = match_keys_in_meshes(
        mesh_objs,
        exact_names=("悲しい", "哀", "悲しみ", "sorrow", "sad"),
        substrings=(
            "KanasiA",
            "Ear_2_R(Kanasi)",
            "Ear_2_L(Kanasi)",
            "悲しい",
            "悲しみ",
        ),
    )
    fun_pairs = match_keys_in_meshes(
        mesh_objs,
        exact_names=("楽しい", "楽", "fun", "relaxed"),
        substrings=("WaraiB", "楽しい"),
        exclude_substrings=("mouth", "kuti", "lip", "口"),
    )
    surprised_pairs = match_keys_in_meshes(
        mesh_objs,
        exact_names=("びっくり", "驚き", "驚", "surprised"),
        substrings=("OdorokiA", "Ear_6_R(Biku)", "Ear_6_L(Biku)", "びっくり", "驚き"),
    )

    STANDARD_MAP_VRM0 = {
        "neutral": [],
        "a": lip_a,
        "i": lip_i,
        "u": lip_u,
        "e": lip_e,
        "o": lip_o,
        "blink": blink_all,
        "blink_l": blink_l,
        "blink_r": blink_r,
        "joy": joy_pairs,
        "angry": angry_pairs,
        "sorrow": sorrow_pairs,
        "fun": fun_pairs,
    }

    STANDARD_MAP_VRM1 = {
        "neutral": [],
        "aa": lip_a,
        "ih": lip_i,
        "ou": lip_u,
        "ee": lip_e,
        "oh": lip_o,
        "blink": blink_all,
        "blink_left": blink_l,
        "blink_right": blink_r,
        "happy": joy_pairs,
        "angry": angry_pairs,
        "sad": sorrow_pairs,
        "relaxed": fun_pairs,
        "surprised": surprised_pairs,
    }

    bound_pairs_set = set()
    for pairs in STANDARD_MAP_VRM1.values():
        for m_obj, k_name in pairs:
            bound_pairs_set.add((m_obj.name, k_name))

    # ================= 绑定 VRM 0.x =================
    if hasattr(ext, "vrm0") and hasattr(ext.vrm0, "blend_shape_master"):
        vrm0_groups = ext.vrm0.blend_shape_master.blend_shape_groups
        vrm0_groups.clear()

        for preset_name, pairs in STANDARD_MAP_VRM0.items():
            if not pairs and preset_name != "neutral":
                continue
            group = vrm0_groups.add()
            group.name = preset_name
            set_vrm0_preset_safe(group, preset_name)
            for m_obj, k_name in pairs:
                bind = group.binds.add()
                bind.mesh.mesh_object_name = m_obj.name
                bind.index = k_name
                bind.weight = get_key_weight(k_name, is_vrm0=True)

        if surprised_pairs:
            group = vrm0_groups.add()
            group.name = "surprised"
            set_vrm0_preset_safe(group, "unknown")
            for m_obj, k_name in surprised_pairs:
                bind = group.binds.add()
                bind.mesh.mesh_object_name = m_obj.name
                bind.index = k_name
                bind.weight = get_key_weight(k_name, is_vrm0=True)

    # ================= 绑定 VRM 1.0 =================
    if hasattr(ext, "vrm1") and hasattr(ext.vrm1, "expressions"):
        vrm1_p = ext.vrm1.expressions.preset
        for preset_attr, pairs in STANDARD_MAP_VRM1.items():
            if not hasattr(vrm1_p, preset_attr):
                continue
            expr_item = getattr(vrm1_p, preset_attr)
            if hasattr(expr_item, "morph_target_binds"):
                expr_item.morph_target_binds.clear()
                for m_obj, k_name in pairs:
                    bind = expr_item.morph_target_binds.add()
                    set_vrm1_bind_node(bind, m_obj)
                    bind.index = k_name
                    bind.weight = get_key_weight(k_name, is_vrm0=False)

                if preset_attr in ("happy", "relaxed") or any(
                    is_eye_closing_key(k) for _, k in pairs
                ):
                    if preset_attr not in ("blink", "blink_left", "blink_right"):
                        set_vrm1_override(expr_item, "override_blink", "block")
                if preset_attr == "surprised" and any(
                    is_mouth_key(k) for _, k in pairs
                ):
                    set_vrm1_override(expr_item, "override_mouth", "block")

        if hasattr(ext.vrm1.expressions, "custom"):
            ext.vrm1.expressions.custom.clear()

    print(
        f"✅ [步骤 3/4] 表情绑定成功！已安全保护并记录 {len(bound_pairs_set)} 个核心表情形态键。"
    )

    # ------------------ 步骤 3.5 瘦身防卡死清理 ------------------
    print(">>> [步骤 3.5/4] 开始清理未调用的冗余形态键与 NLA 动画...")

    valid_mesh_names = {m.name for m in mesh_objs}
    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and obj.name not in valid_mesh_names:
            if obj.parent != armature_obj:
                bpy.data.objects.remove(obj, do_unlink=True)

    for mesh_obj in mesh_objs:
        if not mesh_obj.data or not mesh_obj.data.shape_keys:
            continue
        key_blocks = mesh_obj.data.shape_keys.key_blocks
        keys_to_delete = []
        for key in key_blocks:
            k_name_lower = key.name.lower()
            if k_name_lower in ["basis", "base", "基础", "ベース"]:
                continue
            if (mesh_obj.name, key.name) in bound_pairs_set:
                continue
            if (
                "toothhide" in k_name_lower
                or "eyelidhide" in k_name_lower
                or "normal" in k_name_lower
            ):
                continue
            keys_to_delete.append(key)

        if keys_to_delete:
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
