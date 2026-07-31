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
    print(">>> [步骤 6] 重建纯净材质节点，配置全身无损自发光卡渲视口...")

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    # 指向步骤 5 生成的独立隔离临时文件夹
    temp_dir = os.path.join(texture_dir, "vrm_temp_baked")
    files = os.listdir(texture_dir)

    def find_tex(part_kw, type_kw):
        for f in files:
            fl = f.lower()
            if part_kw in fl and type_kw in fl:
                return load_img(texture_dir, f)
        return None

    parts = ["bdy", "face", "hair", "tail"]

    # 预先加载各部位资源：合成生成的图片从临时目录加载，原图从原资源目录加载
    imgs = {}
    for part in parts:
        imgs[part] = {
            # 从临时图片文件夹中安全载入合成图
            "lit_color": load_img(temp_dir, f"tex_{part}_lit_color_vrm.png")
            or find_tex(part, "diff"),
            # 阴影原图：从原始贴图文件夹中加载
            "shad_c": find_tex(part, "shad_c") or find_tex(part, "shade"),
            # 阴影范围遮罩图：从临时贴图文件夹加载
            "shading_grade": load_img(temp_dir, f"tex_{part}_shading_grade_vrm.png"),
            # 自发光图：从临时贴图文件夹加载
            "emissive": load_img(temp_dir, f"tex_{part}_emissive_baked.png"),
            # 反射原图：从原始贴图文件夹加载
            "rfl": find_tex(part, "rfl") or load_img(texture_dir, "tex_chr_env000.png"),
        }

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
                safe_set_socket_value(bsdf.inputs[inp_name], 0.0)

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

        # ================= 1. 眼睛材质 =================
        if part_key == "eye":
            baked_eye_name = "tex_eye_baked_perfect.png"
            eye_img = load_img(temp_dir, baked_eye_name) or load_img(
                texture_dir, "tex_chr1074_30_eye0.png"
            )

            n_eye = nodes.new("ShaderNodeTexImage")
            n_eye.image = eye_img
            n_eye.location = (-400, 300)

            # 🌟 强自发光（平照卡渲）：Base Color 设为纯黑，颜色直接连接至自发光，强度设为 1.0
            safe_set_socket_value(bsdf.inputs["Base Color"], (0.0, 0.0, 0.0, 1.0))

            emission_s = (
                "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
            )
            if emission_s in bsdf.inputs:
                links.new(n_eye.outputs["Color"], bsdf.inputs[emission_s])
            if "Emission Strength" in bsdf.inputs:
                safe_set_socket_value(bsdf.inputs["Emission Strength"], 1.0)

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

            print(f"   ✅ 眼睛材质 [{mat.name}] 自发光配置完成！")
            continue

        # ================= 2. 其他材质 (bdy, face, hair, tail) =================
        part_imgs = imgs.get(part_key, {})

        lit_img = part_imgs.get("lit_color")
        shad_img = part_imgs.get("shad_c")
        sg_img = part_imgs.get("shading_grade")
        em_img = part_imgs.get("emissive")
        rfl_img = part_imgs.get("rfl")

        if lit_img:
            n_lit = nodes.new("ShaderNodeTexImage")
            n_lit.label = "Base Color (lit_color)"
            n_lit.image = lit_img
            n_lit.location = (-500, 300)

            # 剔除了面部材质透明度判定，保证头皮实心；保留睫毛、眼线、眉毛等透明判定
            is_alpha_mesh = any(
                kw in mat_name
                for kw in [
                    "alpha",
                    "mayu",
                    "lash",
                    "eyelash",
                    "eye",
                    "shadow",
                    "eyeline",
                    "眉",
                    "睫",
                    "透",
                ]
            )
            if is_alpha_mesh:
                if "Alpha" in bsdf.inputs:
                    links.new(n_lit.outputs["Alpha"], bsdf.inputs["Alpha"])
                try:
                    mat.blend_method = "CLIP"
                except TypeError:
                    mat.blend_method = "ALPHA_CLIP"
            else:
                if "Alpha" in bsdf.inputs:
                    safe_set_socket_value(bsdf.inputs["Alpha"], 1.0)
                try:
                    mat.blend_method = "OPAQUE"
                except TypeError:
                    mat.blend_method = "OPAQUE"

        # 🌟 统一配置全身无损自发光平照：
        # 将彩色亮面贴图直接连入自发光通道，强度设为 1.0，并将 Base Color 设为纯黑。
        # 这样在 Blender 视口中模型将呈现出绝对干净、没有 3D 投影和二次受光干扰的完美二次元手绘质感。
        if n_lit:
            emission_s = (
                "Emission Color" if "Emission Color" in bsdf.inputs else "Emission"
            )
            if emission_s in bsdf.inputs:
                links.new(n_lit.outputs["Color"], bsdf.inputs[emission_s])
            if "Emission Strength" in bsdf.inputs:
                safe_set_socket_value(bsdf.inputs["Emission Strength"], 1.0)

            safe_set_socket_value(bsdf.inputs["Base Color"], (0.0, 0.0, 0.0, 1.0))

        if shad_img:
            n_shad = nodes.new("ShaderNodeTexImage")
            n_shad.label = "Shade Color (shad_c)"
            n_shad.image = shad_img
            n_shad.location = (-500, 50)

        if sg_img:
            n_sg = nodes.new("ShaderNodeTexImage")
            n_sg.label = "Shading Grade"
            n_sg.image = sg_img
            n_sg.location = (-500, -200)

        if em_img:
            n_em = nodes.new("ShaderNodeTexImage")
            n_em.label = "Emissive (Baked)"
            n_em.image = em_img
            n_em.location = (-500, -450)

        if rfl_img:
            n_rfl = nodes.new("ShaderNodeTexImage")
            n_rfl.label = "Reflection Map (rfl)"
            n_rfl.image = rfl_img
            n_rfl.location = (-500, -700)

        # 绑定贴图至 VRM MToon 参数中（导出用数据源，游戏引擎中会完美恢复阴影与高光控制）
        mtoon_ext = getattr(mat, "vrm_addon_extension", None)
        if mtoon_ext:
            # 1. 适配 VRM 1.0 (MToon 1.0)
            v1_mtoon = getattr(mtoon_ext, "mtoon1", None)
            if v1_mtoon:
                if lit_img and hasattr(v1_mtoon, "lit_color_texture"):
                    safe_set_vrm_tex(v1_mtoon.lit_color_texture, lit_img)
                if shad_img and hasattr(v1_mtoon, "shade_multiply_texture"):
                    safe_set_vrm_tex(v1_mtoon.shade_multiply_texture, shad_img)
                if sg_img and hasattr(v1_mtoon, "shading_grade_multiply_texture"):
                    safe_set_vrm_tex(v1_mtoon.shading_grade_multiply_texture, sg_img)
                if em_img and hasattr(v1_mtoon, "emissive_texture"):
                    safe_set_vrm_tex(v1_mtoon.emissive_texture, em_img)
                if (
                    rfl_img
                    and hasattr(v1_mtoon, "matcap_texture")
                    and part_key != "face"
                ):
                    safe_set_vrm_tex(v1_mtoon.matcap_texture, rfl_img)

            # 2. 适配 VRM 0.0 (MToon 0.0)
            v0_mat = getattr(mtoon_ext, "vrm0_material", None)
            if v0_mat and hasattr(v0_mat, "texture_properties"):
                for prop in v0_mat.texture_properties:
                    if prop.name == "_MainTex" and lit_img:
                        safe_set_vrm_tex(prop, lit_img)
                    elif prop.name == "_ShadeTexture" and shad_img:
                        safe_set_vrm_tex(prop, shad_img)
                    elif prop.name == "_SphereAdd" and rfl_img and part_key != "face":
                        safe_set_vrm_tex(prop, rfl_img)
                    elif prop.name == "_EmissionMap" and em_img:
                        safe_set_vrm_tex(prop, em_img)

        print(f"   ✅ 材质 [{mat.name}] 已完成自发光平照视口映射！")
