import re

import bpy

from step2_expressions import get_armature_and_shape_meshes

_UMA_KEY_RE = re.compile(
    r"^(EyeBrow|Eye|Mouth|Ear)_(\d+)(?:_([LR0]))?\(([^)]+)\)(?:\[([^\]]+)\])?$",
    re.IGNORECASE,
)


def parse_uma_key(name: str):
    m = _UMA_KEY_RE.match(name.strip())
    if not m:
        return None
    part = m.group(1).lower()
    side = (m.group(3) or "0").upper()
    expr = m.group(4).lower()
    return part, side, expr


def is_uma_shape_mesh(mesh_obj) -> bool:
    if not mesh_obj.data or not mesh_obj.data.shape_keys:
        return False
    cnt = 0
    for kb in mesh_obj.data.shape_keys.key_blocks:
        if _UMA_KEY_RE.match(kb.name.strip()):
            cnt += 1
            if cnt >= 3:
                return True
    return False


def match_uma_keys_in_mesh(
    mesh_obj,
    uma_spec,
    side_filter=None,
    exclude_exprs=(),
):
    if not mesh_obj.data or not mesh_obj.data.shape_keys or not uma_spec:
        return []

    excl_low = {e.lower() for e in exclude_exprs}
    grouped = {}
    for kb in mesh_obj.data.shape_keys.key_blocks:
        parsed = parse_uma_key(kb.name)
        if not parsed:
            continue
        part, side, expr = parsed
        if side_filter and side != side_filter.upper():
            continue
        grouped.setdefault((part, expr), []).append(kb.name)

    results = []
    for part, candidates in uma_spec.items():
        part_low = part.lower()
        for cand in candidates:
            c_low = cand.lower()
            if c_low in excl_low:
                continue
            hits = grouped.get((part_low, c_low))
            if hits:
                for k_name in hits:
                    results.append((mesh_obj, k_name))
                break
    return results


def is_mouth_key(name: str) -> bool:
    low = name.lower()
    return any(
        kw in low for kw in ["mouth", "lip", "talk", "口", "嘴", "歯", "牙", "舌"]
    )


def is_eye_closing_key(name: str) -> bool:
    low = name.lower()
    return any(
        kw in low
        for kw in [
            "close",
            "blink",
            "wink",
            "smile",
            "warai",
            "half",
            "まばたき",
            "ウィンク",
            "ウインク",
            "笑い",
            "にこり",
            "眨眼",
            "闭眼",
        ]
    )


def get_key_weight(key_name: str, is_vrm0: bool) -> float:
    w = 1.0
    return round(w * 100.0, 2) if is_vrm0 else w


def strip_category_prefix(name: str) -> str:
    s = re.sub(
        r"^[【\[（(](?:口|嘴|眼|目|眉|顔|脸|表情|lip|mouth|eye|face)[】\]）)]\s*",
        "",
        name,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"^(?:口|嘴|眼|目|眉|顔|脸|表情)[_\-:\s]+", "", s, flags=re.IGNORECASE)
    return s.strip()


def match_keys_in_meshes(
    mesh_objs,
    exact_names=(),
    substrings=(),
    exclude_substrings=(),
    exclude_exact=(),
    prefer_first_per_mesh=True,
    uma_spec=None,
    uma_side=None,
    uma_exclude_exprs=(),
):
    results = []
    exact_rank = {e.lower(): idx for idx, e in enumerate(exact_names)}
    subs_low = [s.lower() for s in substrings]
    excl_low = [e.lower() for e in exclude_substrings]
    excl_exact_low = {e.lower() for e in exclude_exact}

    for mesh_obj in mesh_objs:
        if not mesh_obj.data or not mesh_obj.data.shape_keys:
            continue

        if uma_spec and is_uma_shape_mesh(mesh_obj):
            results.extend(
                match_uma_keys_in_mesh(
                    mesh_obj,
                    uma_spec=uma_spec,
                    side_filter=uma_side,
                    exclude_exprs=uma_exclude_exprs,
                )
            )
            continue

        mesh_hits = []
        for kb in mesh_obj.data.shape_keys.key_blocks:
            k_low = kb.name.lower()
            k_clean_low = strip_category_prefix(kb.name).lower()
            if k_low in ["basis", "base", "基础", "ベース"]:
                continue
            if k_low in excl_exact_low or k_clean_low in excl_exact_low:
                continue
            if any(ex in k_low for ex in excl_low):
                continue

            if k_low in exact_rank or k_clean_low in exact_rank:
                rank = exact_rank.get(k_low, exact_rank.get(k_clean_low, 999))
                mesh_hits.append((0, rank, len(kb.name), kb.name))
            else:
                sub_hit = next(
                    (
                        idx
                        for idx, sub in enumerate(subs_low)
                        if sub in k_low or sub in k_clean_low
                    ),
                    None,
                )
                if sub_hit is not None:
                    mesh_hits.append((1, sub_hit, len(kb.name), kb.name))

        if mesh_hits:
            mesh_hits.sort()
            if prefer_first_per_mesh:
                results.append((mesh_obj, mesh_hits[0][3]))
            else:
                for _, _, _, k_name in mesh_hits:
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


def is_mesh_bound_to_armature(obj, armature_obj):
    if obj.parent == armature_obj:
        return True
    for mod in obj.modifiers:
        if mod.type == "ARMATURE" and mod.object == armature_obj:
            return True
    return False


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

    ext.spec_version = "1.0"

    all_keys = [
        kb.name
        for m in mesh_objs
        for kb in m.data.shape_keys.key_blocks
        if kb.name.lower() not in ("basis", "base", "基础", "ベース")
    ]
    print(f"   📝 [原始形态键总览({len(all_keys)}个)] {all_keys}")

    lip_a = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "あ",
            "あ1",
            "あ2",
            "A",
            "aa",
            "ah",
            "Mouth_A",
            "M_A",
            "Lip_A",
            "vrc.v_aa",
            "啊",
            "阿",
            "张嘴",
            "张口",
            "开口",
        ),
        substrings=("Mouth_A", "Lip_A", "v_aa", "口あ", "あ2", "张嘴", "张口", "开口"),
        exclude_substrings=("あご", "あせ", "あわ", "怒", "angry"),
        prefer_first_per_mesh=True,
        uma_spec={
            "mouth": ("TalkA_A_L", "TalkA_A_S", "TalkB_A_L", "TalkB_A_S", "TalkC_A")
        },
    )
    lip_i = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "い",
            "い1",
            "I",
            "ih",
            "Mouth_I",
            "M_I",
            "Lip_I",
            "vrc.v_ih",
            "一",
            "衣",
            "伊",
        ),
        substrings=("Mouth_I", "Lip_I", "v_ih", "口い"),
        exclude_substrings=("いろ", "いか", "怒"),
        prefer_first_per_mesh=True,
        uma_spec={
            "mouth": ("TalkA_I_L", "TalkA_I_S", "TalkB_I_L", "TalkB_I_S", "TalkC_I")
        },
    )
    lip_u = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "う",
            "う1",
            "U",
            "ou",
            "Mouth_U",
            "M_U",
            "Lip_U",
            "vrc.v_ou",
            "呜",
            "乌",
        ),
        substrings=("Mouth_U", "Lip_U", "v_ou", "口う", "嘟嘴"),
        exclude_substrings=("うで", "うら"),
        prefer_first_per_mesh=True,
        uma_spec={
            "mouth": ("TalkA_U_L", "TalkA_U_S", "TalkB_U_L", "TalkB_U_S", "TalkC_U")
        },
    )
    lip_e = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "え",
            "え1",
            "E",
            "ee",
            "eh",
            "Mouth_E",
            "M_E",
            "Lip_E",
            "vrc.v_ee",
            "哎",
            "诶",
        ),
        substrings=("Mouth_E", "Lip_E", "v_ee", "口え"),
        exclude_substrings=("えり", "えがお"),
        prefer_first_per_mesh=True,
        uma_spec={
            "mouth": ("TalkA_E_L", "TalkA_E_S", "TalkB_E_L", "TalkB_E_S", "TalkC_E")
        },
    )
    lip_o = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "お",
            "お1",
            "O",
            "oh",
            "Mouth_O",
            "M_O",
            "Lip_O",
            "vrc.v_oh",
            "哦",
            "喔",
        ),
        substrings=("Mouth_O", "Lip_O", "v_oh", "口お"),
        exclude_substrings=("おこ", "おど"),
        prefer_first_per_mesh=True,
        uma_spec={
            "mouth": ("TalkA_O_L", "TalkA_O_S", "TalkB_O_L", "TalkB_O_S", "TalkC_O")
        },
    )

    blink_all = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "まばたき",
            "まばたき2",
            "両目",
            "目閉じ",
            "blink",
            "Eye_Blink",
            "Eye_Close",
            "眨眼",
            "闭眼",
            "双眼",
        ),
        substrings=("まばたき", "目閉じ", "Eye_Blink", "Eye_Close", "眨眼", "闭眼"),
        exclude_substrings=("_L", "_R", "右", "左", "left", "right", "笑", "smile"),
        prefer_first_per_mesh=True,
        uma_spec={"eye": ("CloseA", "CloseB", "Close")},
    )
    blink_l = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "ウィンク",
            "ウィンク左",
            "ウインク",
            "ウインク左",
            "blink_l",
            "blink_left",
            "wink_l",
            "Eye_Blink_L",
            "左眨眼",
            "左闭眼",
        ),
        substrings=(
            "ウィンク",
            "ウインク",
            "blink_l",
            "wink_l",
            "Eye_Blink_L",
            "Eye_Close_L",
            "左眨眼",
            "左闭眼",
        ),
        exclude_substrings=("右", "_R", "right", "２", "2"),
        prefer_first_per_mesh=True,
        uma_spec={"eye": ("CloseA", "CloseB", "Close")},
        uma_side="L",
    )
    blink_r = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "ウィンク右",
            "ウィンク２",
            "ウィンク2",
            "ウインク右",
            "ウインク２",
            "ウインク2",
            "blink_r",
            "blink_right",
            "wink_r",
            "Eye_Blink_R",
            "右眨眼",
            "右闭眼",
        ),
        substrings=(
            "ウィンク右",
            "ウィンク2",
            "ウィンク２",
            "ウインク右",
            "ウインク2",
            "ウインク２",
            "blink_r",
            "wink_r",
            "Eye_Blink_R",
            "Eye_Close_R",
            "右眨眼",
            "右闭眼",
        ),
        prefer_first_per_mesh=True,
        uma_spec={"eye": ("CloseA", "CloseB", "Close")},
        uma_side="R",
    )

    # happy 优先选 笑い / 笑顔 / happy；马娘模型同步联动 EyeBrow([M_Face]+[M_Mayu]) + Eye + Mouth + Ear
    joy_pairs = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "笑い",
            "笑顔",
            "にこり",
            "にっこり",
            "happy",
            "joy",
            "smile",
            "笑",
            "微笑",
            "开心",
            "高兴",
        ),
        substrings=(
            "笑い",
            "笑顔",
            "にこり",
            "Eye_Smile",
            "Happy",
            "Joy",
            "Smile",
            "开心",
            "微笑",
        ),
        exclude_substrings=("右", "左", "_L", "_R", "目"),
        prefer_first_per_mesh=True,
        uma_spec={
            "eyebrow": ("WaraiA", "WaraiB", "WaraiC", "WaraiD", "Warai"),
            "eye": ("WaraiA", "WaraiB", "WaraiC", "WaraiD", "Warai"),
            "mouth": ("WaraiA", "WaraiB", "WaraiC", "WaraiD", "WaraiE", "Warai"),
            "ear": ("Tanosi", "Warai"),
        },
    )
    if not joy_pairs:
        joy_pairs = match_keys_in_meshes(
            mesh_objs,
            exact_names=("笑い目", "にこり"),
            substrings=("笑い", "にこり"),
            prefer_first_per_mesh=True,
        )
    joy_used = [k for _, k in joy_pairs]
    joy_used_uma_exprs = {
        parsed[2] for _, k in joy_pairs if (parsed := parse_uma_key(k)) is not None
    }

    # relaxed 优先匹配 楽しい/楽/ほほえみ/微笑み，马娘模型使用未给 happy 用过的 WaraiB / DereA / HalfA
    fun_pairs = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "楽しい",
            "楽",
            "ほほえみ",
            "微笑み",
            "微笑",
            "にこり",
            "にこり2",
            "にっこり",
            "笑い目",
            "うっとり",
            "relaxed",
            "fun",
            "relax",
            "calm",
            "放松",
            "愉快",
        ),
        substrings=(
            "楽しい",
            "ほほえみ",
            "微笑",
            "にこり",
            "うっとり",
            "Relax",
            "Fun",
            "放松",
        ),
        exclude_substrings=(
            "mouth",
            "lip",
            "口",
            "嘴",
            "右",
            "左",
            "_L",
            "_R",
            "なごみ",
        ),
        exclude_exact=joy_used,
        prefer_first_per_mesh=True,
        uma_spec={
            "eyebrow": ("WaraiB", "DereA", "WaraiC", "WaraiD", "KusyoA", "RunA"),
            "eye": ("WaraiB", "DereA", "HalfA", "WaraiC", "WaraiD", "KusyoA", "RunA"),
            "mouth": (
                "WaraiB",
                "DereA",
                "WaraiC",
                "WaraiD",
                "WaraiE",
                "KusyoA",
                "RunA",
            ),
            "ear": ("Dere", "Tanosi"),
        },
        uma_exclude_exprs=joy_used_uma_exprs,
    )

    angry_pairs = match_keys_in_meshes(
        mesh_objs,
        exact_names=("怒り", "おこ", "angry", "生气", "愤怒", "怒"),
        substrings=("怒り", "おこ", "Angry", "生气", "愤怒"),
        exclude_substrings=("右", "左", "_L", "_R"),
        prefer_first_per_mesh=True,
        uma_spec={
            "eyebrow": ("IkariA", "IkariB", "Ikari"),
            "eye": ("IkariA", "IkariB", "Ikari"),
            "mouth": ("IkariA", "IkariB", "Ikari"),
            "ear": ("Ikari",),
        },
    )
    sorrow_pairs = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "悲しい",
            "悲しみ",
            "哀",
            "困る",
            "sorrow",
            "sad",
            "悲伤",
            "伤心",
            "难过",
            "委屈",
        ),
        substrings=(
            "悲しい",
            "悲しみ",
            "Sorrow",
            "Sad",
            "悲伤",
            "伤心",
            "委屈",
            "困る",
        ),
        exclude_substrings=("右", "左", "_L", "_R"),
        prefer_first_per_mesh=True,
        uma_spec={
            "eyebrow": ("KanasiA", "KomariA", "UreiA", "Kanasi"),
            "eye": ("KanasiA", "UreiA", "KomariA", "Kanasi"),
            "mouth": ("KanasiA", "KomariA", "UreiA", "Kanasi"),
            "ear": ("Kanasi",),
        },
    )
    surprised_pairs = match_keys_in_meshes(
        mesh_objs,
        exact_names=(
            "びっくり",
            "驚き",
            "驚",
            "見開き",
            "surprised",
            "surprise",
            "惊讶",
            "吃惊",
            "惊",
        ),
        substrings=("びっくり", "驚き", "Surprise", "Shock", "惊讶", "吃惊"),
        exclude_substrings=("右", "左", "_L", "_R"),
        prefer_first_per_mesh=True,
        uma_spec={
            "eyebrow": ("OdorokiA", "OdorokiB", "Odoroki"),
            "eye": ("OdorokiA", "OdorokiB", "OdorokiC", "Odoroki"),
            "mouth": ("OdorokiA", "OdorokiB", "Odoroki"),
            "ear": ("Biku",),
        },
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
    matched_presets = 0
    for preset_name, pairs in STANDARD_MAP_VRM1.items():
        if pairs or preset_name == "neutral":
            matched_presets += 1
            print(f"   🎭 [映射] {preset_name} -> {[k for _, k in pairs]}")
        for m_obj, k_name in pairs:
            bound_pairs_set.add((m_obj.name, k_name))

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
        f"✅ [步骤 3/4] 表情绑定完成！共激活 {matched_presets} 个标准预设，保护 {len(bound_pairs_set)} 个核心形态键。"
    )

    print(">>> [步骤 3.5/4] 开始清理未调用的冗余形态键与 NLA 动画...")

    valid_mesh_names = {m.name for m in mesh_objs}
    for obj in list(bpy.data.objects):
        if obj.type == "MESH" and obj.name not in valid_mesh_names:
            if not is_mesh_bound_to_armature(obj, armature_obj):
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
            keys_to_delete.append(key)

        if keys_to_delete:
            print(
                f"   正在从网格 [{mesh_obj.name}] 清理 {len(keys_to_delete)} 个冗余形态键..."
            )
            for key in keys_to_delete:
                mesh_obj.shape_key_remove(key)
        print(
            f"   📋 [{mesh_obj.name}] 清理后剩余形态键: {len(mesh_obj.data.shape_keys.key_blocks)} 个"
        )

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
