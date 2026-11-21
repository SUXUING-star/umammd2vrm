import json
import os

import bpy

from step0_mat_map import classify_material_role, extract_material_base_image


def load_baked_img(texture_dir, filename, colorspace="sRGB"):
    if not texture_dir or not filename:
        return None
    fpath = os.path.join(texture_dir, "vrm_temp_baked", filename)
    if not os.path.exists(fpath):
        fpath = os.path.join(texture_dir, filename)
    if os.path.exists(fpath):
        img = bpy.data.images.load(fpath, check_existing=True)
        try:
            img.colorspace_settings.name = colorspace
        except Exception:
            pass
        try:
            img.pack()
        except Exception:
            pass
        return img
    return None


def extract_mmd_or_bsdf_props(mat):
    diffuse = (1.0, 1.0, 1.0)
    alpha = 1.0
    double_sided = True

    mmd_mat = getattr(mat, "mmd_material", None)
    if mmd_mat:
        try:
            dc = mmd_mat.diffuse_color
            diffuse = (float(dc[0]), float(dc[1]), float(dc[2]))
            alpha = float(mmd_mat.alpha)
            double_sided = bool(mmd_mat.is_double_sided)
            return diffuse, alpha, double_sided
        except Exception:
            pass

    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED":
                bc = node.inputs.get("Base Color")
                if bc and not bc.is_linked:
                    c = bc.default_value
                    diffuse = (float(c[0]), float(c[1]), float(c[2]))
                al = node.inputs.get("Alpha")
                if al and not al.is_linked:
                    alpha = float(al.default_value)
                break

    return diffuse, alpha, double_sided


def detect_part_key(mat_name, role):
    """兼容 step4_bake_texture.py 的部位贴图命名映射"""
    name = mat_name.lower()
    if role == "eye" or (
        "eye" in name
        and not any(kw in name for kw in ["brow", "lash", "line", "shadow"])
    ):
        return "eye"
    if any(kw in name for kw in ["mayu", "face", "kao", "顔"]):
        return "face"
    if any(kw in name for kw in ["skin", "hada", "肌", "素体"]):
        return "skin"
    if role == "hair" or any(kw in name for kw in ["hair", "kami", "髪"]):
        return "hair"
    if any(kw in name for kw in ["tail", "shippo"]):
        return "tail"
    if any(kw in name for kw in ["bdy", "body", "karada", "体"]):
        return "bdy"
    return role


def get_shade_tint_tuple(shading_role):
    """沿用原版暖肉色皮肤阴影与微紫灰卡通暗部，避免发灰发脏"""
    if shading_role in ("face", "skin"):
        return (0.92, 0.76, 0.74)
    if shading_role in ("eye", "fx_overlay"):
        return (0.95, 0.94, 0.97)
    if shading_role == "hair":
        return (0.80, 0.78, 0.85)
    return (0.80, 0.78, 0.85)


def run(texture_dir):
    print(">>> [步骤 5] 绑定 VRM MToon 1.0 材质 (融合原版皮肤柔光调色与多通道贴图)...")

    # 1. 尝试读取 ww_bake_manifest.json（兼容新流程）
    manifest = {}
    if texture_dir:
        m_path = os.path.join(texture_dir, "vrm_temp_baked", "ww_bake_manifest.json")
        if os.path.exists(m_path):
            with open(m_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

    # 2. 预加载 step4_bake_texture.py 烘焙的多通道部位贴图（兼容原流程）
    part_imgs = {}
    eye_baked_img = None
    if texture_dir and os.path.exists(texture_dir):
        eye_baked_img = load_baked_img(texture_dir, "tex_eye_baked_perfect.png", "sRGB")
        for part in ["bdy", "face", "hair", "tail"]:
            part_imgs[part] = {
                "lit": load_baked_img(
                    texture_dir, f"tex_{part}_lit_color_vrm.png", "sRGB"
                ),
                "shade": load_baked_img(
                    texture_dir, f"tex_{part}_shade_color_vrm.png", "sRGB"
                ),
                "shift": load_baked_img(
                    texture_dir, f"tex_{part}_shading_shift_vrm.png", "Non-Color"
                ),
                "emissive": load_baked_img(
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
        "alpha",
    ]

    converted = 0
    total = 0

    for mat in bpy.data.materials:
        if not mat or getattr(mat, "users", 0) == 0:
            continue
        if getattr(mat, "is_grease_pencil", False):
            continue
        total += 1

        orig_img = extract_material_base_image(mat)
        diffuse_rgb, mat_alpha, is_double_sided = extract_mmd_or_bsdf_props(mat)
        orig_img_name = orig_img.name if orig_img else ""
        role = classify_material_role(mat.name, orig_img_name)
        part_key = detect_part_key(mat.name, role)

        # 确定用于决定 MToon 光影参数的逻辑分类
        if role in ("face", "skin") or part_key in ("face", "skin"):
            shading_role = "face"
        elif role in ("eye", "fx_overlay") or part_key == "eye":
            shading_role = role if role in ("eye", "fx_overlay") else "eye"
        elif role == "hair" or part_key == "hair":
            shading_role = "hair"
        else:
            shading_role = role or part_key

        info = manifest.get(orig_img_name, {})

        # 贴图优先级：manifest > step4_bake_texture 部位烘焙图 > 原材质贴图
        lit_img = load_baked_img(texture_dir, info.get("lit"), "sRGB")
        shade_img = load_baked_img(texture_dir, info.get("shade"), "sRGB")
        shift_img = load_baked_img(texture_dir, info.get("shading_shift"), "Non-Color")
        emissive_img = load_baked_img(texture_dir, info.get("emissive"), "sRGB")

        if not lit_img:
            if part_key == "eye" and eye_baked_img:
                lit_img = eye_baked_img
                shade_img = shade_img or eye_baked_img
            elif part_key in part_imgs and part_imgs[part_key]["lit"]:
                lit_img = part_imgs[part_key]["lit"]
                shade_img = shade_img or part_imgs[part_key]["shade"]
                shift_img = shift_img or part_imgs[part_key]["shift"]
                emissive_img = emissive_img or part_imgs[part_key]["emissive"]
            elif (
                part_key == "skin"
                and "bdy" in part_imgs
                and part_imgs["bdy"]["lit"]
                and (not orig_img or "bdy" in orig_img_name.lower())
            ):
                lit_img = part_imgs["bdy"]["lit"]
                shade_img = shade_img or part_imgs["bdy"]["shade"]

        if not lit_img:
            lit_img = orig_img

        ext = getattr(mat, "vrm_addon_extension", None)
        if ext is None or not hasattr(ext, "mtoon1"):
            print(f"   ⚠️ 材质 [{mat.name}] 未找到 vrm_addon_extension.mtoon1")
            continue

        mat.use_nodes = True
        gltf = ext.mtoon1
        gltf.enabled = True
        gltf.double_sided = (
            True
            if role in ("lash_brow", "cutout_cloth", "fx_overlay", "hair")
            else is_double_sided
        )

        # 核心修复：只要存在贴图，base_color_factor 保持纯白 (1, 1, 1, alpha)，
        # 避免 MMD 默认偏暗/偏色的 diffuse_color 把皮肤染脏！
        if lit_img:
            try:
                lit_img.pack()
            except Exception:
                pass
            gltf.pbr_metallic_roughness.base_color_factor = (1.0, 1.0, 1.0, mat_alpha)
            gltf.pbr_metallic_roughness.base_color_texture.index.source = lit_img
        else:
            r, g, b = diffuse_rgb if max(diffuse_rgb) > 0.02 else (1.0, 1.0, 1.0)
            gltf.pbr_metallic_roughness.base_color_factor = (r, g, b, mat_alpha)

        if emissive_img:
            gltf.emissive_texture.index.source = emissive_img
            gltf.emissive_factor = (1.0, 1.0, 1.0)
        else:
            gltf.emissive_factor = (0.0, 0.0, 0.0)

        # Alpha 模式：同时兼容 manifest 与原版关键字（防止 mayu/睫毛变黑块）
        mat_name_lower = mat.name.lower()
        is_alpha_kw = any(kw in mat_name_lower for kw in ALLOW_ALPHA_KEYWORDS)
        suggested_alpha = info.get("alpha_mode", "OPAQUE")

        if mat_alpha < 0.99 or role == "fx_overlay" or suggested_alpha == "BLEND":
            gltf.alpha_mode = "BLEND"
        elif (
            suggested_alpha == "MASK"
            or (
                role in ("lash_brow", "cutout_cloth")
                and (not info or info.get("has_alpha"))
            )
            or is_alpha_kw
        ):
            gltf.alpha_mode = "MASK"
            gltf.alpha_cutoff = 0.5
        else:
            gltf.alpha_mode = "OPAQUE"

        mtoon = gltf.extensions.vrmc_materials_mtoon
        mtoon.transparent_with_z_write = False
        mtoon.render_queue_offset_number = 1 if gltf.alpha_mode == "BLEND" else 0

        # 1. 暗部颜色配置：有独立烘焙暗部图时优先使用，否则使用原版暖色/卡通矩阵
        if shade_img and shade_img != lit_img:
            mtoon.shade_multiply_texture.index.source = shade_img
            mtoon.shade_color_factor = (1.0, 1.0, 1.0)
        else:
            tint = get_shade_tint_tuple(shading_role)
            if lit_img:
                mtoon.shade_multiply_texture.index.source = lit_img
                mtoon.shade_color_factor = tint
            else:
                r, g, b = diffuse_rgb if max(diffuse_rgb) > 0.02 else (1.0, 1.0, 1.0)
                mtoon.shade_color_factor = (r * tint[0], g * tint[1], b * tint[2])

        # 2. 阴影推移图：脸部/皮肤/眼睛不绑推移图，防止压缩噪点破坏皮肤光滑感
        if shift_img and shading_role not in ("face", "skin", "eye", "fx_overlay"):
            mtoon.shading_shift_texture.index.source = shift_img
            if hasattr(mtoon.shading_shift_texture, "scale"):
                mtoon.shading_shift_texture.scale = 0.12

        # 3. 沿用原版明暗交界与 GI 均等化调色参数
        if shading_role in ("face", "skin"):
            mtoon.shading_shift_factor = 0.12
            mtoon.shading_toony_factor = 0.22
            mtoon.gi_equalization_factor = 0.90
        elif shading_role in ("eye", "fx_overlay"):
            mtoon.shading_shift_factor = 0.0
            mtoon.shading_toony_factor = 0.15
            mtoon.gi_equalization_factor = 0.95
        elif shading_role == "hair":
            mtoon.shading_shift_factor = 0.0
            mtoon.shading_toony_factor = 0.55
            mtoon.gi_equalization_factor = 0.75
        else:
            mtoon.shading_shift_factor = 0.05
            mtoon.shading_toony_factor = 0.38
            mtoon.gi_equalization_factor = 0.80

        mtoon.outline_width_mode = "none"
        if mat.node_tree:
            mat.node_tree.update_tag()
        converted += 1

    try:
        bpy.ops.outliner.orphans_purge(
            do_local_ids=True, do_linked_ids=True, do_recursive=True
        )
    except Exception:
        pass
    for img in list(bpy.data.images):
        if img.users == 0:
            bpy.data.images.remove(img)

    print(f"✅ [步骤 5] MToon 1.0 材质转换完成：{converted}/{total} 个材质。")
