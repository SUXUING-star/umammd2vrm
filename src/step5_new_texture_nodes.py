import os

import bpy


def load_img(texture_dir, filename):
    temp_path = os.path.join(texture_dir, "vrm_temp_baked", filename)
    if os.path.exists(temp_path):
        fpath = temp_path
    else:
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
    print(
        ">>> [步骤 5] 将提取的通道数据全自动绑定至 VRM MToon 材质 (含抗 VRoid Hub 死亡侧光配置)..."
    )

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    parts = ["bdy", "face", "hair", "tail"]

    imgs = {}
    for part in parts:
        imgs[part] = {
            "lit_color": load_img(texture_dir, f"tex_{part}_lit_color_vrm.png"),
            "shade_color": load_img(texture_dir, f"tex_{part}_shade_color_vrm.png"),
            "emissive": load_img(texture_dir, f"tex_{part}_emissive_baked.png"),
            "matcap": load_img(texture_dir, f"tex_{part}_matcap_vrm.png"),
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
        emissive_img = None
        matcap_img = None

        if part_key == "eye":
            lit_img = load_img(texture_dir, "tex_eye_baked_perfect.png")
            shade_img = lit_img
        elif part_key and part_key in imgs:
            lit_img = imgs[part_key]["lit_color"]
            shade_img = imgs[part_key]["shade_color"]
            emissive_img = imgs[part_key]["emissive"]
            matcap_img = imgs[part_key]["matcap"]

        if not lit_img:
            continue

        # 转换为 MToon 节点组结构
        try:
            bpy.ops.vrm.add_mtoon_material_group(material_name=mat.name)
        except Exception as e:
            print(f"   ⚠️ 材质 [{mat.name}] MToon 转换警告: {e}")

        ext = getattr(mat, "vrm_addon_extension", None)
        if ext is not None and hasattr(ext, "mtoon1"):
            gltf = ext.mtoon1
            gltf.enabled = True

            # 1. 主色与 Lit Color 贴图
            gltf.pbr_metallic_roughness.base_color_factor = (1.0, 1.0, 1.0, 1.0)
            gltf.pbr_metallic_roughness.base_color_texture.index.source = lit_img

            # 2. 绑定自发光 (Emissive)
            if emissive_img:
                gltf.emissive_texture.index.source = emissive_img
                gltf.emissive_factor = (1.0, 1.0, 1.0)

            # 透明度模式
            if is_transparent:
                gltf.alpha_mode = "MASK"
                gltf.alpha_cutoff = 0.5
            else:
                gltf.alpha_mode = "OPAQUE"

            gltf.double_sided = True

            # 3. 驱动 MToon 着色器参数
            mtoon = gltf.extensions.vrmc_materials_mtoon

            # 【暗部阴影贴图】: 绑定真实 shade_c/合成贴图，因子设为纯白 (1.0, 1.0, 1.0) 保持原色彩
            if shade_img:
                mtoon.shade_multiply_texture.index.source = shade_img
                mtoon.shade_color_factor = (1.0, 1.0, 1.0)
            else:
                mtoon.shade_multiply_texture.index.source = lit_img
                mtoon.shade_color_factor = (0.85, 0.85, 0.85)

            # 【MatCap 高光贴图】
            if matcap_img:
                mtoon.matcap_texture.index.source = matcap_img

            # 🎯🎯🎯 核心配置：针对脸部设置抗 VRoid Hub 侧光黑斑的防御参数 🎯🎯🎯
            if part_key == "face":
                # -0.25 的阴影推移可以让脸部在强侧光下依然保持干净，绝不出黑色斑块
                mtoon.shading_shift_factor = -0.25
                mtoon.shading_toony_factor = 0.98
                # 强制填充环境光，防止暗部出现死黑
                mtoon.gi_equalization_factor = 1.0
            elif part_key == "hair":
                mtoon.shading_shift_factor = 0.0
                mtoon.shading_toony_factor = 0.95
                mtoon.gi_equalization_factor = 0.5
            else:
                mtoon.shading_shift_factor = 0.0
                mtoon.shading_toony_factor = 0.92
                mtoon.gi_equalization_factor = 0.5

    print("✅ [步骤 5] MToon 材质构建与抗侧光暗部保护全部完成！")
