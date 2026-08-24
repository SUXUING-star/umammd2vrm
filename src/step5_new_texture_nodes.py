import os

import bpy


def load_img(texture_dir, filename, colorspace="sRGB"):
    temp_path = os.path.join(texture_dir, "vrm_temp_baked", filename)
    if os.path.exists(temp_path):
        fpath = temp_path
    else:
        fpath = os.path.join(texture_dir, filename)

    if os.path.exists(fpath):
        img = bpy.data.images.load(fpath, check_existing=True)
        try:
            # 根据数据类型严格分配 sRGB 或 Non-Color（消除 VRM 插件色彩空间警告）
            img.colorspace_settings.name = colorspace
        except Exception:
            pass
        img.pack()
        return img
    return None


def run(texture_dir):
    print(">>> [步骤 5] 绑定 VRM MToon 材质 (已规范色彩空间设定，消除非色彩警告)...")

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    parts = ["bdy", "face", "hair", "tail"]

    imgs = {}
    for part in parts:
        imgs[part] = {
            # 色彩贴图 -> sRGB
            "lit_color": load_img(
                texture_dir, f"tex_{part}_lit_color_vrm.png", colorspace="sRGB"
            ),
            "shade_color": load_img(
                texture_dir,
                f"tex_{part}_shade_color_vrm.png",
                colorspace="sRGB",
            ),
            # 数据推移图 -> Non-Color (消除警告核心)
            "shading_shift": load_img(
                texture_dir,
                f"tex_{part}_shading_shift_vrm.png",
                colorspace="Non-Color",
            ),
            "emissive": load_img(
                texture_dir, f"tex_{part}_emissive_baked.png", colorspace="sRGB"
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

        # 匹配对应部位
        part_key = None
        if "eye" in mat_name and not any(
            kw in mat_name for kw in ["brow", "lash", "line", "shadow"]
        ):
            part_key = "eye"
        elif "mayu" in mat_name or "face" in mat_name or "kao" in mat_name:
            part_key = "face"
        elif "hair" in mat_name or "kami" in mat_name:
            part_key = "hair"
        elif "tail" in mat_name or "shippo" in mat_name:
            part_key = "tail"
        elif "bdy" in mat_name or "body" in mat_name or "karada" in mat_name:
            part_key = "bdy"

        lit_img = None
        shade_img = None
        shift_img = None
        emissive_img = None

        if part_key == "eye":
            lit_img = load_img(
                texture_dir, "tex_eye_baked_perfect.png", colorspace="sRGB"
            )
            shade_img = lit_img
        elif part_key and part_key in imgs:
            lit_img = imgs[part_key]["lit_color"]
            shade_img = imgs[part_key]["shade_color"]
            shift_img = imgs[part_key]["shading_shift"]
            emissive_img = imgs[part_key]["emissive"]

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

            # 1. 固有色
            gltf.pbr_metallic_roughness.base_color_factor = (1.0, 1.0, 1.0, 1.0)
            gltf.pbr_metallic_roughness.base_color_texture.index.source = lit_img

            # 2. 自发光
            if emissive_img:
                gltf.emissive_texture.index.source = emissive_img
                gltf.emissive_factor = (0.15, 0.15, 0.15)
            else:
                gltf.emissive_factor = (0.0, 0.0, 0.0)

            # 透明度模式
            if is_transparent:
                gltf.alpha_mode = "MASK"
                gltf.alpha_cutoff = 0.5
            else:
                gltf.alpha_mode = "OPAQUE"

            gltf.double_sided = True

            # 3. 驱动 MToon 1.0 着色器参数
            mtoon = gltf.extensions.vrmc_materials_mtoon

            # 【暗部阴影贴图】
            if shade_img:
                mtoon.shade_multiply_texture.index.source = shade_img
                mtoon.shade_color_factor = (1.0, 1.0, 1.0)
            else:
                mtoon.shade_multiply_texture.index.source = lit_img
                mtoon.shade_color_factor = (0.85, 0.85, 0.85)

            # 【阴影推移图 (Non-Color)】
            if shift_img:
                mtoon.shading_shift_texture.index.source = shift_img
                if hasattr(mtoon.shading_shift_texture, "scale"):
                    mtoon.shading_shift_texture.scale = 1.0

            # 材质参数
            if part_key == "face":
                mtoon.shading_shift_factor = -0.15
                mtoon.shading_toony_factor = 0.88
                mtoon.gi_equalization_factor = 0.08
            elif part_key == "hair":
                mtoon.shading_shift_factor = -0.05
                mtoon.shading_toony_factor = 0.75
                mtoon.gi_equalization_factor = 0.0
            else:  # bdy
                mtoon.shading_shift_factor = -0.05
                mtoon.shading_toony_factor = 0.68
                mtoon.gi_equalization_factor = 0.0

            # 描边配置
            if part_key in ["eye", "face"] or is_transparent:
                mtoon.outline_width_mode = "none"
            else:
                mtoon.outline_width_mode = "worldCoordinates"
                mtoon.outline_width_factor = 0.0010
                mtoon.outline_color_factor = (0.05, 0.02, 0.02)
                mtoon.outline_lighting_mix_factor = 0.5

    print("✅ [步骤 5] 材质与色彩空间配置完成！")
