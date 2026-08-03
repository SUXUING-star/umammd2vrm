# --- START OF FILE step5_new_texture_nodes.py ---
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
        ">>> [步骤 5] 正在调用 VRM 官方算子将 Principled BSDF 彻底重构为 MToon 卡通节点树..."
    )

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    files = os.listdir(texture_dir)
    temp_dir = os.path.join(texture_dir, "vrm_temp_baked")
    temp_files = os.listdir(temp_dir) if os.path.exists(temp_dir) else []

    def find_tex(part_kw, type_kw):
        for f in temp_files:
            fl = f.lower()
            if part_kw in fl and type_kw in fl:
                return load_img(texture_dir, f)
        for f in files:
            fl = f.lower()
            if part_kw in fl and type_kw in fl:
                return load_img(texture_dir, f)
        return None

    parts = ["bdy", "face", "hair", "tail"]

    # 加载带有完美 Alpha 通道的彩色主贴图
    imgs = {}
    for part in parts:
        baked_lit = f"tex_{part}_lit_color_vrm.png"
        img_lit = (
            load_img(texture_dir, baked_lit)
            or find_tex(part, "diff")
            or find_tex(part, "base")
        )
        imgs[part] = {"lit_color": img_lit}

    # 严格的半透明判定
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

        # 匹配对应部位贴图
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

        target_img = None
        if part_key == "eye":
            target_img = load_img(texture_dir, "tex_eye_baked_perfect.png")
            if not target_img:
                target_img = find_tex("eye", "diff") or find_tex("eye", "color")
        elif part_key:
            target_img = imgs.get(part_key, {}).get("lit_color")

        if not target_img:
            target_img = find_tex(mat_name, "diff") or find_tex(mat_name, "color")

        if not target_img:
            continue

        # ==================== 🎯 核心解决：彻底将物理材质转成原生 MToon 节点组 ====================
        try:
            # 1. 调用 VRM 官方算子。这会清空 BSDF，自动在节点网中生成标准的 MToon 卡通着色器组
            bpy.ops.vrm.add_mtoon_material_group(material_name=mat.name)
            print(
                f"   [MToon 转换] 成功将材质 [{mat.name}] 从物理 BSDF 转换为官方 MToon 节点组结构！"
            )
        except Exception as e:
            print(
                f"   ⚠️ 无法调用官方 MToon 转换算子: {e}，尝试使用备用元数据路径设置。"
            )

        # 2. 严格遵循 VRM 1.0 官方文档路径，写入原生卡通参数，保障材质在 Web 环境完美解算
        ext = getattr(mat, "vrm_addon_extension", None)
        if ext is not None and hasattr(ext, "mtoon1"):
            gltf = ext.mtoon1
            gltf.enabled = True

            # 写入主色与主贴图（Lit Texture）
            gltf.pbr_metallic_roughness.base_color_factor = (1.0, 1.0, 1.0, 1.0)
            gltf.pbr_metallic_roughness.base_color_texture.index.source = target_img

            # 透明模式设定
            if is_transparent:
                gltf.alpha_mode = "MASK"
                gltf.alpha_cutoff = 0.5
            else:
                gltf.alpha_mode = "OPAQUE"

            gltf.double_sided = True

            # 配置 MToon 卡通渲染核心数据块 (vrmc_materials_mtoon)
            mtoon = gltf.extensions.vrmc_materials_mtoon

            # 【阴影贴图映射】
            mtoon.shade_multiply_texture.index.source = target_img

            # 🎯 核心调优：根据不同部位，定制防发灰、防脏的二次元专属阴影参数
            if part_key == "face" or part_key == "bdy":
                # 🌟 皮肤与脸部：使用明亮且饱满的蜜桃暖粉色（Peach-Pink），彻底消灭脏灰色
                mtoon.shade_color_factor = (0.96, 0.84, 0.83)  # 极干净的血色感暖阴影
                mtoon.shading_shift_factor = (
                    -0.05
                )  # 稍微收紧面部阴影范围，防止脸部出现大片阴影
                mtoon.shading_toony_factor = (
                    0.98  # 极锐利的阴影边缘，彻底消除渐变产生的脏影
                )

            elif part_key == "hair":
                # 🌟 头发：使用浅紫灰色调阴影，保持发丝的蓬松通透感，避免发闷
                mtoon.shade_color_factor = (0.88, 0.84, 0.88)
                mtoon.shading_shift_factor = 0.02
                mtoon.shading_toony_factor = 0.95

            else:
                # 🌟 衣服、尾巴及其他通用部件：使用高通透度浅灰，保持干净
                mtoon.shade_color_factor = (0.85, 0.83, 0.86)
                mtoon.shading_shift_factor = 0.05
                mtoon.shading_toony_factor = 0.90

            # 消除场景光源强度对卡通材质的二次过曝叠加
            mtoon.gi_equalization_factor = 0.5
