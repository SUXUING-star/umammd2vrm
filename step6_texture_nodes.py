# --- START OF FILE step6_texture_nodes.py ---
import os

import bpy

from utils import safe_set_socket_value, safe_set_vrm_tex


def load_img(texture_dir, filename):
    fpath = os.path.join(texture_dir, filename)
    if os.path.exists(fpath):
        img = bpy.data.images.load(fpath, check_existing=True)
        try:
            img.colorspace_settings.name = "sRGB"
        except Exception:
            pass
        img.pack()
        return img
    return None


def run(texture_dir):
    print(">>> [步骤 6/6] 重建纯净材质节点，还原原始 Cygames 防爆白设置...")

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    files = os.listdir(texture_dir)

    def find_tex(part_kw, type_kw):
        for f in files:
            fl = f.lower()
            if part_kw in fl and type_kw in fl:
                return load_img(texture_dir, f)
        return None

    parts = ["bdy", "face", "hair", "tail"]
    tex_types = ["diff", "shad_c", "ctrl", "rfl"]

    imgs = {}
    for part in parts:
        imgs[part] = {}
        for ttype in tex_types:
            imgs[part][ttype] = find_tex(part, ttype)

    pbr_inputs = [
        "Metallic",
        "Specular",
        "Specular IOR Level",
        "Specular Tint",
        "Coat",
        "Coat Weight",
        "Sheen",
        "Sheen Weight",
        "Anisotropic",
        "Subsurface",
        "Subsurface Weight",
    ]

    for mat in bpy.data.materials:
        if not mat:
            continue

        mat.use_nodes = True
        mat_name = mat.name.lower()
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        nodes.clear()

        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.location = (100, 300)

        n_out = nodes.new("ShaderNodeOutputMaterial")
        n_out.location = (400, 300)

        links.new(bsdf.outputs["BSDF"], n_out.inputs["Surface"])

        for inp_name in pbr_inputs:
            if inp_name in bsdf.inputs:
                inp_sock = bsdf.inputs[inp_name]
                safe_set_socket_value(inp_sock, 0.0)

        if "Roughness" in bsdf.inputs:
            safe_set_socket_value(bsdf.inputs["Roughness"], 1.0)

        part_key = None
        if "eye" in mat_name:
            part_key = "eye"
        elif "mayu" in mat_name or "face" in mat_name or "kao" in mat_name:
            part_key = "face"
        elif "hair" in mat_name or "kami" in mat_name:
            part_key = "hair"
        elif "tail" in mat_name or "shippo" in mat_name:
            part_key = "tail"
        elif "bdy" in mat_name or "body" in mat_name or "karada" in mat_name:
            part_key = "bdy"

        if not part_key:
            continue

        if part_key == "eye":
            # 读取已合成的烘焙图，若不存在则回退至原版基础眼睛图
            baked_eye_name = "tex_eye_baked_perfect.png"
            baked_eye_path = os.path.join(texture_dir, baked_eye_name)
            if os.path.exists(baked_eye_path):
                eye_img = load_img(texture_dir, baked_eye_name)
            else:
                eye_img = load_img(texture_dir, "tex_chr1074_30_eye0.png")

            n_eye = nodes.new("ShaderNodeTexImage")
            n_eye.image = eye_img
            n_eye.location = (-400, 300)

            base_s = bsdf.inputs["Base Color"]
            links.new(n_eye.outputs["Color"], base_s)

            emission_s = (
                "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
            )
            if emission_s in bsdf.inputs:
                em_sock = bsdf.inputs[emission_s]
                links.new(n_eye.outputs["Color"], em_sock)

            if "Emission Strength" in bsdf.inputs:
                safe_set_socket_value(bsdf.inputs["Emission Strength"], 0.20)

            try:
                mat.blend_method = "CLIP"
            except TypeError:
                mat.blend_method = "ALPHA_CLIP"

            mtoon_ext = getattr(mat, "vrm_addon_extension", None)
            if mtoon_ext:
                v1_mtoon = getattr(mtoon_ext, "mtoon1", None)
                if v1_mtoon and hasattr(v1_mtoon, "lit_color_texture"):
                    safe_set_vrm_tex(v1_mtoon.lit_color_texture, eye_img)

                v0_mat = getattr(mtoon_ext, "vrm0_material", None)
                if v0_mat and hasattr(v0_mat, "texture_properties"):
                    for prop in v0_mat.texture_properties:
                        if prop.name == "_MainTex":
                            safe_set_vrm_tex(prop, eye_img)

            print(f"✅ 眼睛材质 [{mat.name}] 处理完成！")
            continue

        part_imgs = imgs.get(part_key, {})
        diff_img = part_imgs.get("diff")
        shad_img = part_imgs.get("shad_c")
        ctrl_img = part_imgs.get("ctrl")
        rfl_img = part_imgs.get("rfl")

        if diff_img:
            n_diff = nodes.new("ShaderNodeTexImage")
            n_diff.label = "Base Color (diff)"
            n_diff.image = diff_img
            n_diff.location = (-400, 300)

            base_s = bsdf.inputs["Base Color"]
            links.new(n_diff.outputs["Color"], base_s)

            if "Emission Strength" in bsdf.inputs:
                safe_set_socket_value(bsdf.inputs["Emission Strength"], 0.0)

            is_alpha_mesh = "alpha" in mat_name or "mayu" in mat_name
            if is_alpha_mesh:
                if "Alpha" in bsdf.inputs:
                    alpha_s = bsdf.inputs["Alpha"]
                    links.new(n_diff.outputs["Alpha"], alpha_s)
                try:
                    mat.blend_method = "CLIP"
                except TypeError:
                    mat.blend_method = "ALPHA_CLIP"
            else:
                if "Alpha" in bsdf.inputs:
                    alpha_s = bsdf.inputs["Alpha"]
                    safe_set_socket_value(alpha_s, 1.0)
                try:
                    mat.blend_method = "OPAQUE"
                except TypeError:
                    mat.blend_method = "OPAQUE"

        if shad_img:
            n_shad = nodes.new("ShaderNodeTexImage")
            n_shad.label = "Shade Color (shad_c)"
            n_shad.image = shad_img
            n_shad.location = (-400, 50)

        if rfl_img:
            n_rfl = nodes.new("ShaderNodeTexImage")
            n_rfl.label = "Reflection Map (rfl)"
            n_rfl.image = rfl_img
            n_rfl.location = (-400, -250)

        mtoon_ext = getattr(mat, "vrm_addon_extension", None)
        if mtoon_ext:
            v1_mtoon = getattr(mtoon_ext, "mtoon1", None)
            if v1_mtoon:
                if diff_img and hasattr(v1_mtoon, "lit_color_texture"):
                    safe_set_vrm_tex(v1_mtoon.lit_color_texture, diff_img)
                if shad_img and hasattr(v1_mtoon, "shade_multiply_texture"):
                    safe_set_vrm_tex(v1_mtoon.shade_multiply_texture, shad_img)
                if rfl_img and hasattr(v1_mtoon, "matcap_texture"):
                    safe_set_vrm_tex(v1_mtoon.matcap_texture, rfl_img)

            v0_mat = getattr(mtoon_ext, "vrm0_material", None)
            if v0_mat and hasattr(v0_mat, "texture_properties"):
                for prop in v0_mat.texture_properties:
                    if prop.name == "_MainTex" and diff_img:
                        safe_set_vrm_tex(prop, diff_img)
                    elif prop.name == "_ShadeTexture" and shad_img:
                        safe_set_vrm_tex(prop, shad_img)
                    elif prop.name == "_SphereAdd" and rfl_img:
                        safe_set_vrm_tex(prop, rfl_img)

        print(f"✅ 材质 [{mat.name}] 已完成 Cygames 规格 MToon 绑定！")
