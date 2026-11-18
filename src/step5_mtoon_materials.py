import os

import bpy


def load_img(texture_dir, filename, colorspace="sRGB"):
    temp_path = os.path.join(texture_dir, "vrm_temp_baked", filename)
    fpath = (
        temp_path if os.path.exists(temp_path) else os.path.join(texture_dir, filename)
    )

    if os.path.exists(fpath):
        img = bpy.data.images.load(fpath, check_existing=True)
        try:
            img.colorspace_settings.name = colorspace
        except Exception:
            pass
        img.pack()
        return img
    return None


def find_existing_base_image(mat):
    """兜底方案：针对通用 MMD 模型，直接读取原材质节点中的 Base Color 贴图"""
    if not mat or not mat.use_nodes or not mat.node_tree:
        return None
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            inp = node.inputs.get("Base Color")
            if inp and inp.is_linked:
                src = inp.links[0].from_node
                if src.type == "TEX_IMAGE" and src.image:
                    return src.image
    for node in mat.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image:
            return node.image
    return None


def run(texture_dir):
    print(">>> [步骤 5] 绑定 VRM MToon 材质 (已针对平滑皮肤/柔和交界优化)...")

    parts = ["bdy", "face", "hair", "tail"]
    imgs = {}
    if texture_dir and os.path.exists(texture_dir):
        for part in parts:
            imgs[part] = {
                "lit_color": load_img(
                    texture_dir, f"tex_{part}_lit_color_vrm.png", "sRGB"
                ),
                "shade_color": load_img(
                    texture_dir, f"tex_{part}_shade_color_vrm.png", "sRGB"
                ),
                "shading_shift": load_img(
                    texture_dir, f"tex_{part}_shading_shift_vrm.png", "Non-Color"
                ),
                "emissive": load_img(
                    texture_dir, f"tex_{part}_emissive_baked.png", "sRGB"
                ),
            }

    ALLOW_ALPHA_KEYWORDS = [
        "lash",
        "mayu",
        "eyelash",
        "shadow",
        "dec",
        "trans",
        "眉",
        "睫",
        "透",
        "eyeline",
    ]

    for mat in bpy.data.materials:
        if not mat:
            continue

        mat_name = mat.name.lower()
        is_transparent = any(kw in mat_name for kw in ALLOW_ALPHA_KEYWORDS)

        part_key = None
        if "eye" in mat_name and not any(
            kw in mat_name for kw in ["brow", "lash", "line", "shadow"]
        ):
            part_key = "eye"
        elif any(kw in mat_name for kw in ["mayu", "face", "kao", "顔"]):
            part_key = "face"
        elif any(kw in mat_name for kw in ["skin", "hada", "肌", "素体"]):
            part_key = "skin"
        elif any(kw in mat_name for kw in ["hair", "kami", "髪"]):
            part_key = "hair"
        elif any(kw in mat_name for kw in ["tail", "shippo"]):
            part_key = "tail"
        elif any(kw in mat_name for kw in ["bdy", "body", "karada", "体"]):
            part_key = "bdy"

        lit_img = None
        shade_img = None
        shift_img = None
        emissive_img = None

        if part_key == "eye" and texture_dir:
            lit_img = load_img(texture_dir, "tex_eye_baked_perfect.png", "sRGB")
            shade_img = lit_img
        elif part_key in imgs:
            lit_img = imgs[part_key]["lit_color"]
            shade_img = imgs[part_key]["shade_color"]
            shift_img = imgs[part_key]["shading_shift"]
            emissive_img = imgs[part_key]["emissive"]
        elif part_key == "skin" and "bdy" in imgs:
            lit_img = imgs["bdy"]["lit_color"]
            shade_img = imgs["bdy"]["shade_color"]

        # 兜底：普通 MMD 模型没有按部位拆分的烘焙图时，保留其原有贴图并转为 MToon
        if not lit_img:
            lit_img = find_existing_base_image(mat)
            if not lit_img:
                continue

        try:
            bpy.ops.vrm.add_mtoon_material_group(material_name=mat.name)
        except Exception as e:
            print(f"   ⚠️ 材质 [{mat.name}] MToon 转换警告: {e}")

        ext = getattr(mat, "vrm_addon_extension", None)
        if ext is not None and hasattr(ext, "mtoon1"):
            gltf = ext.mtoon1
            gltf.enabled = True

            gltf.pbr_metallic_roughness.base_color_factor = (1.0, 1.0, 1.0, 1.0)
            gltf.pbr_metallic_roughness.base_color_texture.index.source = lit_img

            if emissive_img:
                gltf.emissive_texture.index.source = emissive_img
                gltf.emissive_factor = (1.0, 1.0, 1.0)
            else:
                gltf.emissive_factor = (0.0, 0.0, 0.0)

            if is_transparent:
                gltf.alpha_mode = "MASK"
                gltf.alpha_cutoff = 0.5
            else:
                gltf.alpha_mode = "OPAQUE"

            gltf.double_sided = True

            mtoon = gltf.extensions.vrmc_materials_mtoon

            # 1. 暗部颜色配置
            if shade_img and shade_img != lit_img:
                mtoon.shade_multiply_texture.index.source = shade_img
                mtoon.shade_color_factor = (1.0, 1.0, 1.0)
            else:
                mtoon.shade_multiply_texture.index.source = lit_img
                if part_key in ("face", "skin"):
                    mtoon.shade_color_factor = (
                        0.92,
                        0.76,
                        0.74,
                    )  # 暖肉色阴影，拒绝发灰
                else:
                    mtoon.shade_color_factor = (0.80, 0.78, 0.85)

            # 2. 阴影推移图：纯脸部/皮肤不绑推移图，避免压缩噪点破坏光滑感
            if shift_img and part_key not in ("face", "skin"):
                mtoon.shading_shift_texture.index.source = shift_img
                if hasattr(mtoon.shading_shift_texture, "scale"):
                    mtoon.shading_shift_texture.scale = 0.12

            # 3. 核心：软化明暗交界 + 拉高 GI 均等化
            if part_key in ("face", "skin"):
                mtoon.shading_shift_factor = 0.12
                mtoon.shading_toony_factor = 0.22
                mtoon.gi_equalization_factor = 0.90
            elif part_key == "hair":
                mtoon.shading_shift_factor = 0.0
                mtoon.shading_toony_factor = 0.55
                mtoon.gi_equalization_factor = 0.75
            else:  # bdy 及其他
                mtoon.shading_shift_factor = 0.05
                mtoon.shading_toony_factor = 0.38
                mtoon.gi_equalization_factor = 0.80

            mtoon.outline_width_mode = "none"

    print("✅ [步骤 5] 材质配置完毕，皮肤已切换为柔光卡通过渡！")
