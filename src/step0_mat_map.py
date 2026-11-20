import re


def extract_material_base_image(mat):
    """准确提取 mmd_tools 或 Principled BSDF 中的 Base 贴图（避开 toon/sphere/matcap 贴图）"""
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None
    nodes = mat.node_tree.nodes

    base_node = nodes.get("mmd_base_tex")
    if base_node and base_node.type == "TEX_IMAGE" and base_node.image:
        return base_node.image

    mmd_shader = nodes.get("mmd_shader")
    if mmd_shader and "Base Tex" in mmd_shader.inputs:
        inp = mmd_shader.inputs["Base Tex"]
        if inp.is_linked:
            src = inp.links[0].from_node
            if src.type == "TEX_IMAGE" and src.image:
                return src.image

    for node in nodes:
        if node.type == "BSDF_PRINCIPLED":
            inp = node.inputs.get("Base Color")
            if inp and inp.is_linked:
                src = inp.links[0].from_node
                if src.type == "TEX_IMAGE" and src.image:
                    return src.image

    for node in nodes:
        if node.type == "TEX_IMAGE" and node.image:
            if node.name in ("mmd_toon_tex", "mmd_sphere_tex"):
                continue
            img_low = node.image.name.lower()
            if any(
                kw in img_low
                for kw in (
                    "spa",
                    "sph",
                    "toon",
                    "hair hi light",
                    "alphamc",
                    "bodymc",
                    "mc12",
                )
            ):
                continue
            return node.image
    return None


def _has_token(text: str, pattern: str) -> bool:
    return bool(re.search(rf"(^|[_\-\s\.\d])({pattern})($|[_\-\s\.\d])", text))


def classify_material_role(mat_name: str, img_name: str = "") -> str:
    """结合材质名与贴图名，识别中/英/拼音混杂材质角色"""
    m = mat_name.lower()
    i = img_name.lower()
    s = f"{m} {i}"

    # 1. 叠加高光 / 腮红 / 表情贴片 / 玻璃 / 液体 / 特效（BLEND + 黑底扣透明）
    if (
        any(
            kw in s
            for kw in (
                "eyehi",
                "eye hi",
                "eyelight",
                "emo",
                "cheek",
                "heng",
                "boli",
                "glass",
                "yeti",
                "liquid",
                "fx",
                "hi li",
                "xing",
                "玻璃",
                "液体",
                "特效",
                "腮红",
                "高光",
                "gaoguang",
                "saihong",
                "yanlei",
            )
        )
        or _has_token(m, r"hi\d*")
        or (_has_token(i, r"hi\d*") and "hair" not in i and "bangs" not in i)
    ):
        return "fx_overlay"

    # 2. 眉毛 / 睫毛 / 眼线（含拼音 mei / jie / yanxian）
    if any(
        kw in m
        for kw in (
            "lash",
            "mayu",
            "brow",
            "eyeline",
            "睫",
            "眉",
            "jiemao",
            "meimao",
            "yanxian",
        )
    ) or re.match(r"^(mei|jie)\d*$", m):
        return "lash_brow"

    # 3. 口腔内 / 舌头 / 牙齿（含拼音 she / chi / ya）
    if any(
        kw in m
        for kw in (
            "teeth",
            "tooth",
            "tongue",
            "mouth_in",
            "舌",
            "歯",
            "牙",
            "齿",
            "kounei",
        )
    ) or re.match(r"^(she|chi|ya)\d*$", m):
        return "mouth_inner"

    # 4. 眼睛 / 眼白（含拼音 bai / yan / tongkong）
    if any(
        kw in m for kw in ("eye", "bai", "瞳", "目", "眼", "yanbai", "tongkong")
    ) or ("eye" in i and "emo" not in i):
        return "eye"

    # 5. 需要透明裁剪的毛绒 / 蕾丝 / 镂空布料 / 头发高光片
    if any(
        kw in s
        for kw in (
            "alpha",
            "lace",
            "fur",
            "frill",
            "feather",
            "蕾丝",
            "镂空",
            "毛绒",
            "半透",
        )
    ) or (("hair" in i or "bangs" in i) and "_hi" in i):
        return "cutout_cloth"

    # 6. 脸部 / 鼻子（含 face / kao / lian / nose）
    if any(kw in m for kw in ("face", "kao", "nose", "顔", "脸", "鼻", "lian")) or (
        "face" in i and "emo" not in i and "cheek" not in i
    ):
        return "face"

    # 7. 身体纯皮肤（含 肌肤 / jifu / skin / hada / 素体）
    if any(
        kw in s
        for kw in (
            "skin",
            "hada",
            "naked",
            "sink",
            "肌",
            "肌肤",
            "素体",
            "皮肤",
            "jifu",
            "pifu",
        )
    ):
        return "skin"

    # 8. 头发 / 刘海（含拼音 toufa / liuhai）
    if any(
        kw in s for kw in ("hair", "bangs", "kami", "髪", "刘海", "toufa", "liuhai")
    ):
        return "hair"

    return "cloth"


def classify_surface_for_normals(
    obj_name: str, mat_name: str, img_name: str = ""
) -> str:
    """用于步骤 0 皮肤法线光滑分类"""
    role = classify_material_role(mat_name, img_name)
    m = mat_name.lower()

    if role == "face":
        # 鼻子/眼周小线条不参与整脸椭球法线平滑
        if "nose" in m or "鼻" in m or "zhou" in m:
            return "other"
        return "face_skin"

    if role == "skin":
        return "body_skin"

    if role in (
        "fx_overlay",
        "lash_brow",
        "mouth_inner",
        "eye",
        "cutout_cloth",
        "hair",
    ):
        return "other"

    # 身体与衣服混合贴图（Up / Down / Body）才做柔和曲面平滑，纯披风/鞋子/娃娃/饰品跳过
    s = f"{m} {img_name.lower()}"
    if any(
        kw in m
        for kw in (
            "披风",
            "娃娃",
            "鞋",
            "靴",
            "链",
            "穗",
            "花",
            "辫",
            "金属",
            "手",
            "头",
        )
    ):
        return "other"
    if any(
        kw in s
        for kw in ("bdy", "body", "karada", "体", "连衣裙", "裙", "上衣", "下装")
    ) or _has_token(s, r"(up|down)\d*"):
        return "body_mixed"

    return "other"
