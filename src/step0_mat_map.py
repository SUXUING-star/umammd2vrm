import os
import re

_NON_BASE_NODE_PREFIXES = ("mmd_toon_tex", "mmd_sphere_tex", "mmd_sub_tex")
_NON_BASE_IMG_KEYWORDS = (
    "spa",
    "sph",
    "toon",
    "hair hi light",
    "alphamc",
    "bodymc",
    "mc12",
)
_TOON_BMP_STEMS = {"hair", "skin", "toon", "toon_defo", "defo", "shadow"}


def _is_toon_or_sphere_image(img) -> bool:
    if not img:
        return True
    name_low = img.name.lower()
    fp_norm = (img.filepath or "").replace("\\", "/").lower()

    if any(seg in fp_norm for seg in ("/spa/", "/sph/", "/toon/", "/toons/")):
        return True
    if fp_norm.endswith((".spa", ".sph")) or name_low.endswith((".spa", ".sph")):
        return True
    if any(kw in name_low for kw in _NON_BASE_IMG_KEYWORDS):
        return True

    stem = os.path.splitext(re.sub(r"\.\d{3}$", "", name_low))[0]
    ext = os.path.splitext(re.sub(r"\.\d{3}$", "", name_low))[1]
    if ext == ".bmp" and (stem in _TOON_BMP_STEMS or stem.startswith("toon")):
        return True
    return False


def extract_material_base_image(mat):
    """准确提取 mmd_tools 或 Principled BSDF 中的 Base 贴图（避开 ZZZ/原神 的 spa/toon .bmp）"""
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None
    nodes = mat.node_tree.nodes

    base_node = nodes.get("mmd_base_tex")
    if base_node and base_node.type == "TEX_IMAGE" and base_node.image:
        if not _is_toon_or_sphere_image(base_node.image):
            return base_node.image

    mmd_shader = nodes.get("mmd_shader")
    if mmd_shader and "Base Tex" in mmd_shader.inputs:
        inp = mmd_shader.inputs["Base Tex"]
        if inp.is_linked:
            src = inp.links[0].from_node
            if (
                src.type == "TEX_IMAGE"
                and src.image
                and not _is_toon_or_sphere_image(src.image)
            ):
                return src.image
        return None

    for node in nodes:
        if node.type == "BSDF_PRINCIPLED":
            inp = node.inputs.get("Base Color")
            if inp and inp.is_linked:
                src = inp.links[0].from_node
                if (
                    src.type == "TEX_IMAGE"
                    and src.image
                    and not _is_toon_or_sphere_image(src.image)
                ):
                    return src.image

    for node in nodes:
        if node.type == "TEX_IMAGE" and node.image:
            if node.name.lower().startswith(_NON_BASE_NODE_PREFIXES):
                continue
            if _is_toon_or_sphere_image(node.image):
                continue
            return node.image
    return None


def _clean_blender_suffix(name: str) -> str:
    return re.sub(r"\.\d{3}$", "", name.strip().lower())


def _has_token(text: str, pattern: str) -> bool:
    return bool(re.search(rf"(^|[_\-\s\.\d\+])({pattern})($|[_\-\s\.\d\+])", text))


def classify_material_role(mat_name: str, img_name: str = "") -> str:
    """结合材质名与贴图名，识别绝区零(ZZZ)/原神 MMD 中/英/日/拼音材质角色"""
    m = _clean_blender_suffix(mat_name)
    i = _clean_blender_suffix(img_name)
    s = f"{m} {i}"

    # 1. 眼部高光 / 眼影 / 腮红(含照れ) / 表情贴片 / 玻璃 / 镜片 / 特效（BLEND + 黑底自动扣透明）
    if (
        any(
            kw in m
            for kw in (
                "目光",
                "目影",
                "眼影",
                "eyeshadow",
                "eye_shadow",
                "eyehi",
                "eye hi",
                "eyelight",
                "eye_light",
                "emo",
                "cheek",
                "照れ",
                "tere",
                "heng",
                "boli",
                "glass",
                "lens",
                "镜片",
                "玻璃",
                "yeti",
                "liquid",
                "液体",
                "fx",
                "effect",
                "特效",
                "光效",
                "光环",
                "halo",
                "腮红",
                "红晕",
                "脸红",
                "高光",
                "gaoguang",
                "saihong",
                "泪",
                "yanlei",
                "sticker",
                "贴纸",
                "decal",
                "半透",
            )
        )
        or any(
            kw in i
            for kw in (
                "eyehi",
                "eyelight",
                "eyeshadow",
                "cheek",
                "照れ",
                "tere",
                "sticker",
                "decal",
            )
        )
        or _has_token(m, r"hi\d*")
        or (
            _has_token(i, r"hi\d*")
            and "hair" not in i
            and "bangs" not in i
            and "发" not in i
        )
    ):
        return "fx_overlay"

    # 2. 眉毛 / 睫毛 / 双眼皮线 / 眼线 / 口线
    if any(
        kw in m
        for kw in (
            "lash",
            "mayu",
            "brow",
            "eyeline",
            "futae",
            "kuchisen",
            "二重",
            "双眼皮",
            "睫",
            "眉",
            "眼线",
            "口线",
            "口線",
            "唇线",
            "jiemao",
            "meimao",
            "yanxian",
        )
    ) or re.match(r"^(mei|jie)\d*$", m):
        return "lash_brow"

    # 3. 口腔内 / 舌头 / 牙齿
    if any(
        kw in m
        for kw in (
            "teeth",
            "tooth",
            "tongue",
            "mouth_in",
            "口舌",
            "口腔",
            "口内",
            "口中",
            "舌",
            "歯",
            "牙",
            "齿",
            "kounei",
        )
    ) or re.match(r"^(she|chi|ya)\d*$", m):
        return "mouth_inner"

    # 4. 眼睛 / 眼白
    if any(
        kw in m
        for kw in (
            "eye",
            "iris",
            "sclera",
            "hitomi",
            "目白",
            "白目",
            "眼白",
            "瞳",
            "目",
            "眼",
            "yanbai",
            "tongkong",
        )
    ) or ("eye" in i and "emo" not in i and "shadow" not in i and "hi" not in i):
        return "eye"

    # 5. 需要透明裁剪的翅膀 / 羽毛 / 蕾丝 / 镂空 / 薄纱 / 头发高光片
    is_hair_plus_tex = ("发+" in m or "髮+" in m or "hair+" in m) and (
        "发+" in i or "髮+" in i or "hair+" in i or "_hi" in i or "sp" in i
    )
    if (
        is_hair_plus_tex
        or any(
            kw in s
            for kw in (
                "alpha",
                "cutout",
                "lace",
                "fur",
                "frill",
                "feather",
                "wing",
                "翅膀",
                "羽毛",
                "蕾丝",
                "镂空",
                "网纱",
                "薄纱",
                "毛绒",
                "流苏",
            )
        )
        or (("hair" in i or "bangs" in i) and "_hi" in i)
    ):
        return "cutout_cloth"

    # 6. 脸部 / 鼻子
    if any(
        kw in m
        for kw in ("face", "kao", "nose", "颜", "顔", "脸", "面部", "鼻", "lian")
    ) or ("face" in i and "emo" not in i and "cheek" not in i):
        return "face"

    # 7. 身体纯皮肤
    is_hand_skin = m.startswith("手") and not any(
        ex in m for ex in ("套", "环", "链", "饰", "甲", "护", "2")
    )
    is_skin_tex = any(kw in i for kw in ("肌", "skin", "hada", "jifu", "pifu"))
    if (
        is_hand_skin
        or is_skin_tex
        or "指甲" in m
        or "nail" in m
        or any(
            kw in m
            for kw in (
                "skin",
                "hada",
                "naked",
                "sink",
                "肌",
                "素体",
                "皮肤",
                "jifu",
                "pifu",
            )
        )
    ):
        return "skin"

    # 8. 头发 / 刘海（排除发饰/发卡/发带等配件）
    is_hair_accessory = any(
        kw in m
        for kw in (
            "发饰",
            "髪飾",
            "发卡",
            "发夹",
            "发带",
            "发圈",
            "发簪",
            "发冠",
            "发箍",
            "发结",
            "髮饰",
            "髮飾",
        )
    )
    if not is_hair_accessory and any(
        kw in s
        for kw in (
            "hair",
            "bangs",
            "kami",
            "ahoge",
            "twintail",
            "ponytail",
            "髪",
            "髮",
            "头发",
            "前发",
            "后发",
            "侧发",
            "刘海",
            "呆毛",
            "鬓",
            "马尾",
            "辫",
            "toufa",
            "liuhai",
            "发",
        )
    ):
        return "hair"

    # 9. 金属 / 武器 / 镜框 / 拉链
    if any(
        kw in m
        for kw in (
            "金属",
            "metal",
            "武器",
            "weapon",
            "镜框",
            "拉链",
            "铁",
            "钢",
            "铜",
            "徽章",
        )
    ) or any(kw in i for kw in ("金属", "metal", "weapon")):
        return "metal"

    return "cloth"


def classify_surface_for_normals(
    obj_name: str, mat_name: str, img_name: str = ""
) -> str:
    """用于步骤 0 皮肤法线光滑分类"""
    role = classify_material_role(mat_name, img_name)
    m = _clean_blender_suffix(mat_name)

    if role == "face":
        if "nose" in m or "鼻" in m or "zhou" in m:
            return "other"
        return "face_skin"

    if role == "skin":
        # 手部/手指/指甲几何体极细，严禁进 SMOOTH 代理平滑，否则手指会被压瘪导致法线翻转变黑
        if (
            m.startswith("手")
            or "hand" in m
            or "finger" in m
            or "指甲" in m
            or "nail" in m
        ):
            return "other"
        return "body_skin"

    if role in (
        "fx_overlay",
        "lash_brow",
        "mouth_inner",
        "eye",
        "cutout_cloth",
        "hair",
        "metal",
    ):
        return "other"

    if any(
        kw in m
        for kw in (
            "披风",
            "娃娃",
            "鞋",
            "靴",
            "袜",
            "链",
            "穗",
            "花",
            "辫",
            "金属",
            "手",
            "头",
            "饰",
            "戒指",
            "袖",
        )
    ):
        return "other"

    s = f"{m} {_clean_blender_suffix(img_name)}"
    if (
        m in ("体", "体上", "体下", "体2", "身体")
        or any(
            kw in s
            for kw in (
                "bdy",
                "body",
                "karada",
                "体上",
                "体下",
                "连衣裙",
                "上衣",
                "下装",
            )
        )
        or _has_token(s, r"(up|down)\d*")
    ):
        return "body_mixed"

    return "other"
