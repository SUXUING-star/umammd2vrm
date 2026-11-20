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
        img.pack()
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


def get_shade_tint_tuple(role):
    if role in ("face", "skin"):
        return (0.93, 0.78, 0.75)
    if role in ("eye", "fx_overlay"):
        return (0.95, 0.94, 0.97)
    if role == "hair":
        return (0.76, 0.73, 0.84)
    return (0.77, 0.76, 0.84)


def run(texture_dir):
    print(">>> [步骤 5] 绑定 VRM MToon 1.0 材质...")

    manifest = {}
    if texture_dir:
        m_path = os.path.join(texture_dir, "vrm_temp_baked", "ww_bake_manifest.json")
        if os.path.exists(m_path):
            with open(m_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

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

        info = manifest.get(orig_img_name, {})
        lit_img = load_baked_img(texture_dir, info.get("lit"), "sRGB") or orig_img
        emissive_img = load_baked_img(texture_dir, info.get("emissive"), "sRGB")

        ext = getattr(mat, "vrm_addon_extension", None)
        if ext is None or not hasattr(ext, "mtoon1"):
            print(f"   ⚠️ 材质 [{mat.name}] 未找到 vrm_addon_extension.mtoon1")
            continue

        mat.use_nodes = True
        gltf = ext.mtoon1
        gltf.enabled = True
        gltf.double_sided = is_double_sided

        if lit_img:
            try:
                lit_img.pack()
            except Exception:
                pass
            r, g, b = diffuse_rgb if max(diffuse_rgb) > 0.02 else (1.0, 1.0, 1.0)
            gltf.pbr_metallic_roughness.base_color_factor = (r, g, b, mat_alpha)
            gltf.pbr_metallic_roughness.base_color_texture.index.source = lit_img
        else:
            r, g, b = diffuse_rgb
            gltf.pbr_metallic_roughness.base_color_factor = (r, g, b, mat_alpha)

        if emissive_img:
            gltf.emissive_texture.index.source = emissive_img
            gltf.emissive_factor = (1.0, 1.0, 1.0)
        else:
            gltf.emissive_factor = (0.0, 0.0, 0.0)

        suggested_alpha = info.get("alpha_mode", "OPAQUE")
        if mat_alpha < 0.99 or role == "fx_overlay" or suggested_alpha == "BLEND":
            gltf.alpha_mode = "BLEND"
        elif role in ("lash_brow", "cutout_cloth") and (
            suggested_alpha == "MASK" or info.get("has_alpha")
        ):
            gltf.alpha_mode = "MASK"
            gltf.alpha_cutoff = 0.5
        else:
            gltf.alpha_mode = "OPAQUE"

        mtoon = gltf.extensions.vrmc_materials_mtoon
        mtoon.transparent_with_z_write = False
        mtoon.render_queue_offset_number = 1 if gltf.alpha_mode == "BLEND" else 0

        tint = get_shade_tint_tuple(role)
        if lit_img:
            mtoon.shade_multiply_texture.index.source = lit_img
        mtoon.shade_color_factor = (r * tint[0], g * tint[1], b * tint[2])

        if role in ("face", "skin"):
            mtoon.shading_shift_factor = 0.10
            mtoon.shading_toony_factor = 0.25
            mtoon.gi_equalization_factor = 0.88
        elif role in ("eye", "fx_overlay"):
            mtoon.shading_shift_factor = 0.0
            mtoon.shading_toony_factor = 0.15
            mtoon.gi_equalization_factor = 0.95
        elif role == "hair":
            mtoon.shading_shift_factor = 0.0
            mtoon.shading_toony_factor = 0.50
            mtoon.gi_equalization_factor = 0.75
        else:
            mtoon.shading_shift_factor = 0.02
            mtoon.shading_toony_factor = 0.40
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
