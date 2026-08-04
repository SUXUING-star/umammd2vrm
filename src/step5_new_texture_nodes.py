# --- START OF FILE step5_new_texture_nodes.py ---
import os

import bpy


def force_colorspace(image_obj, target_space):
    """强效色彩空间同步函数，兼容不同 Blender OCIO 配置"""
    if not image_obj or not hasattr(image_obj, "colorspace_settings"):
        return
    try:
        valid_names = [
            elem.identifier
            for elem in image_obj.colorspace_settings.bl_rna.properties[
                "name"
            ].enum_items
        ]
        if target_space in valid_names:
            image_obj.colorspace_settings.name = target_space
        else:
            target_clean = target_space.lower().replace("-", "").replace(" ", "")
            for v_name in valid_names:
                v_clean = v_name.lower().replace("-", "").replace(" ", "")
                if target_clean in v_clean:
                    image_obj.colorspace_settings.name = v_name
                    break
    except Exception as e:
        print(f"⚠️ 设置色彩空间失败 [{image_obj.name} -> {target_space}]: {e}")


def load_img(texture_dir, filename, is_data=False):
    temp_path = os.path.join(texture_dir, "vrm_temp_baked", filename)
    if os.path.exists(temp_path):
        fpath = temp_path
    else:
        fpath = os.path.join(texture_dir, filename)

    if os.path.exists(fpath):
        img = bpy.data.images.load(fpath, check_existing=True)
        target_cs = "Non-Color" if is_data else "sRGB"
        force_colorspace(img, target_cs)
        img.pack()
        return img
    return None


def safe_set_tex_ref(tex_ref_obj, image_obj):
    if not tex_ref_obj:
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

    # 环境反射 MatCap 贴图 (sRGB)
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
            # Shading Shift 要求 Non-Color
            "shading_shift": load_img(
                texture_dir, f"tex_{part}_shading_shift_vrm.png", is_data=True
            ),
            "emissive": load_img(
                texture_dir, f"tex_{part}_emissive_baked.png", is_data=False
            ),
            # Rim Multiply Texture 要求 sRGB
            "rim_mask": load_img(
                texture_dir, f"tex_{part}_rim_mask_vrm.png", is_data=False
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

            # 1. Lit Color
            gltf.pbr_metallic_roughness.base_color_factor = (1.0, 1.0, 1.0, 1.0)
            safe_set_tex_ref(gltf.pbr_metallic_roughness.base_color_texture, lit_img)

            # 2. 哑光材质参数
            gltf.pbr_metallic_roughness.metallic_factor = 0.0
            gltf.pbr_metallic_roughness.roughness_factor = 1.0

            # 3. 透明模式
            if is_transparent:
                gltf.alpha_mode = "MASK"
                gltf.alpha_cutoff = 0.5
            else:
                gltf.alpha_mode = "OPAQUE"

            gltf.double_sided = True

            # 4. Emissive
            if em_img:
                safe_set_tex_ref(gltf.emissive_texture, em_img)
                gltf.emissive_factor = (1.0, 1.0, 1.0)
            else:
                safe_set_tex_ref(gltf.emissive_texture, None)
                gltf.emissive_factor = (0.0, 0.0, 0.0)

            # 5. MToon
            mtoon = gltf.extensions.vrmc_materials_mtoon

            # A. 影色贴图
            safe_set_tex_ref(mtoon.shade_multiply_texture, shade_img)
            mtoon.shade_color_factor = (1.0, 1.0, 1.0)

            # B. Shading Shift
            if shift_img:
                safe_set_tex_ref(mtoon.shading_shift_texture, shift_img)
                mtoon.shading_shift_factor = 0.0

            mtoon.shading_toony_factor = 0.95

            # C. MatCap
            if env_img and part_key not in ["face", "eye"]:
                safe_set_tex_ref(mtoon.matcap_texture, env_img)
            else:
                safe_set_tex_ref(mtoon.matcap_texture, None)

            # D. Rim 边缘光
            if rim_img:
                safe_set_tex_ref(mtoon.rim_multiply_texture, rim_img)
                mtoon.parametric_rim_color_factor = (0.3, 0.3, 0.3)
            else:
                mtoon.parametric_rim_color_factor = (0.0, 0.0, 0.0)

            mtoon.gi_equalization_factor = 0.5

            # 🌟🌟🌟 6. 强制纠正所有贴图槽位及节点树中的色彩空间，彻底消除警告 🌟🌟🌟
            if (
                hasattr(gltf.pbr_metallic_roughness, "base_color_texture")
                and gltf.pbr_metallic_roughness.base_color_texture.index.source
            ):
                force_colorspace(
                    gltf.pbr_metallic_roughness.base_color_texture.index.source,
                    "sRGB",
                )

            if hasattr(gltf, "emissive_texture") and gltf.emissive_texture.index.source:
                force_colorspace(gltf.emissive_texture.index.source, "sRGB")

            if (
                hasattr(mtoon, "shade_multiply_texture")
                and mtoon.shade_multiply_texture.index.source
            ):
                force_colorspace(mtoon.shade_multiply_texture.index.source, "sRGB")

            if (
                hasattr(mtoon, "shading_shift_texture")
                and mtoon.shading_shift_texture.index.source
            ):
                force_colorspace(mtoon.shading_shift_texture.index.source, "Non-Color")

            if hasattr(mtoon, "matcap_texture") and mtoon.matcap_texture.index.source:
                force_colorspace(mtoon.matcap_texture.index.source, "sRGB")

            if (
                hasattr(mtoon, "rim_multiply_texture")
                and mtoon.rim_multiply_texture.index.source
            ):
                force_colorspace(mtoon.rim_multiply_texture.index.source, "sRGB")

            # 遍历材质节点树中的图像节点同步修改
            if mat.use_nodes and mat.node_tree:
                for node in mat.node_tree.nodes:
                    if node.type == "TEX_IMAGE" and node.image:
                        if "shading_shift" in node.image.name.lower():
                            force_colorspace(node.image, "Non-Color")
                        else:
                            force_colorspace(node.image, "sRGB")

            print(
                f"   ✅ [MToon 着色完成] 材质 [{mat.name}] 已完成映射与色彩空间校正。"
            )
