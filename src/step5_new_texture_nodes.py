# --- START OF FILE step5_new_texture_nodes.py ---
import os

import bpy


def load_img(texture_dir, filename, is_data=False):
    temp_path = os.path.join(texture_dir, "vrm_temp_baked", filename)
    if os.path.exists(temp_path):
        fpath = temp_path
    else:
        fpath = os.path.join(texture_dir, filename)

    if os.path.exists(fpath):
        img = bpy.data.images.load(fpath, check_existing=True)
        try:
            # 🌟 核心修复：数据遮罩（Shading Shift, Rim Mask 等）严格指定为 Non-Color
            if is_data:
                img.colorspace_settings.name = "Non-Color"
            else:
                img.colorspace_settings.name = "sRGB"
        except Exception:
            pass
        img.pack()
        return img
    return None


def safe_set_tex_ref(tex_ref_obj, image_obj):
    if not tex_ref_obj or not image_obj:
        return
    try:
        if hasattr(tex_ref_obj, "index") and hasattr(tex_ref_obj.index, "source"):
            tex_ref_obj.index.source = image_obj
        elif hasattr(tex_ref_obj, "source"):
            tex_ref_obj.source = image_obj
        elif hasattr(tex_ref_obj, "value"):
            tex_ref_obj.value = image_obj
    except Exception:
        pass


def run(texture_dir):
    print(">>> [步骤 5] 构建官方 MToon 材质，关联多通道数据遮罩...")

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    files = os.listdir(texture_dir)
    temp_dir = os.path.join(texture_dir, "vrm_temp_baked")
    temp_files = os.listdir(temp_dir) if os.path.exists(temp_dir) else []

    def find_tex(part_kw, type_kw, is_data=False):
        for f in temp_files:
            fl = f.lower()
            if part_kw in fl and type_kw in fl:
                return load_img(texture_dir, f, is_data=is_data)
        for f in files:
            fl = f.lower()
            if part_kw in fl and type_kw in fl:
                return load_img(texture_dir, f, is_data=is_data)
        return None

    # 环境反射 MatCap 贴图 (Color)
    env_img = load_img(texture_dir, "tex_chr_env000.png") or find_tex(
        "", "rfl", is_data=False
    )

    parts = ["bdy", "face", "hair", "tail"]
    imgs = {}
    for part in parts:
        imgs[part] = {
            "lit_color": load_img(
                texture_dir, f"tex_{part}_lit_color_vrm.png", is_data=False
            )
            or find_tex(part, "diff", is_data=False),
            "shade_color": load_img(
                texture_dir, f"tex_{part}_shade_color_vrm.png", is_data=False
            )
            or find_tex(part, "shad_c", is_data=False),
            # 🌟 数据遮罩设为 is_data=True
            "shading_shift": load_img(
                texture_dir, f"tex_{part}_shading_shift_vrm.png", is_data=True
            ),
            "emissive": load_img(
                texture_dir, f"tex_{part}_emissive_baked.png", is_data=False
            ),
            "rim_mask": load_img(
                texture_dir, f"tex_{part}_rim_mask_vrm.png", is_data=True
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
        elif "mayu" in mat_name or "face" in mat_name or "kao" in mat_name:
            part_key = "face"
        elif "hair" in mat_name or "kami" in mat_name:
            part_key = "hair"
        elif "tail" in mat_name or "shippo" in mat_name:
            part_key = "tail"
        elif "bdy" in mat_name or "body" in mat_name or "karada" in mat_name:
            part_key = "bdy"

        # 获取材质对应贴图资源
        lit_img, shade_img, shift_img, em_img, rim_img = None, None, None, None, None
        if part_key == "eye":
            lit_img = load_img(
                texture_dir, "tex_eye_baked_perfect.png", is_data=False
            ) or find_tex("eye", "diff", is_data=False)
            shade_img = lit_img
        elif part_key:
            p_data = imgs.get(part_key, {})
            lit_img = p_data.get("lit_color")
            shade_img = p_data.get("shade_color") or lit_img
            shift_img = p_data.get("shading_shift")
            em_img = p_data.get("emissive")
            rim_img = p_data.get("rim_mask")

        if not lit_img:
            lit_img = find_tex(mat_name, "diff", is_data=False) or find_tex(
                mat_name, "color", is_data=False
            )
            shade_img = find_tex(mat_name, "shad_c", is_data=False) or lit_img

        if not lit_img:
            continue

        # 转换为 VRM 官方 MToon 材质组
        try:
            bpy.ops.vrm.add_mtoon_material_group(material_name=mat.name)
        except Exception as e:
            print(f"   ⚠️ MToon 转换警告 [{mat.name}]: {e}")

        ext = getattr(mat, "vrm_addon_extension", None)
        if ext is not None and hasattr(ext, "mtoon1"):
            gltf = ext.mtoon1
            gltf.enabled = True

            # 1. Lit Color (主贴图)
            gltf.pbr_metallic_roughness.base_color_factor = (1.0, 1.0, 1.0, 1.0)
            safe_set_tex_ref(gltf.pbr_metallic_roughness.base_color_texture, lit_img)

            # 2. 透明模式
            if is_transparent:
                gltf.alpha_mode = "MASK"
                gltf.alpha_cutoff = 0.5
            else:
                gltf.alpha_mode = "OPAQUE"

            gltf.double_sided = True

            # 3. Emissive (自发光 - 取自 ctrl 通道 B)
            if em_img:
                safe_set_tex_ref(gltf.emissive_texture, em_img)
                gltf.emissive_factor = (1.0, 1.0, 1.0)

            # 4. MToon 卡通着色数据映射
            mtoon = gltf.extensions.vrmc_materials_mtoon

            # A. 影色贴图：直接关联原生 shad_c 影色图！
            safe_set_tex_ref(mtoon.shade_multiply_texture, shade_img)
            mtoon.shade_color_factor = (1.0, 1.0, 1.0)

            # B. Shading Shift：使用 base R 通道提取的 Non-Color 遮罩贴图
            if shift_img:
                safe_set_tex_ref(mtoon.shading_shift_texture, shift_img)
                mtoon.shading_shift_factor = 0.0

            mtoon.shading_toony_factor = 0.95

            # C. MatCap 环境反射
            if env_img:
                safe_set_tex_ref(mtoon.matcap_texture, env_img)

            # D. Rim 边缘光遮罩 (来自 ctrl 通道 R 的 Non-Color 贴图)
            if rim_img:
                safe_set_tex_ref(mtoon.rim_multiply_texture, rim_img)
                mtoon.parametric_rim_color_factor = (1.0, 1.0, 1.0)

            mtoon.gi_equalization_factor = 0.5

            print(f"   ✅ [MToon 精准映射] 材质 [{mat.name}] 已成功绑定多通道遮罩。")
