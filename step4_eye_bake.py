# --- START OF FILE step4_eye_bake.py ---
import os

import bpy
import numpy as np
from PIL import Image


def run(texture_dir):
    print(">>> [步骤 4] 开始执行多通道贴图分离与自发光烘焙...")

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    # 新建专属临时导出文件夹，实现临时生成件与原版资源物理隔离
    temp_dir = os.path.join(texture_dir, "vrm_temp_baked")
    os.makedirs(temp_dir, exist_ok=True)
    print(f"   已建立/确认临时导出文件夹: {temp_dir}")

    files = os.listdir(texture_dir)

    # ================= 1. 动态匹配眼睛贴图（彻底告别硬编码） =================
    eye0_file = None

    # A. 模糊检索主眼瞳贴图 (含有 eye 且含有 0 或 base 且不含 hi/highlight)
    for f in files:
        fl = f.lower()
        if "eye" in fl and ("0" in fl or "base" in fl) and "hi" not in fl:
            eye0_file = f
            break

    # B. 兜底检索：若未匹配到带有 0 的，寻找任何包含 eye 且不含 hi 的贴图
    if not eye0_file:
        for f in files:
            fl = f.lower()
            if "eye" in fl and "hi" not in fl:
                eye0_file = f
                break

    if eye0_file:
        try:
            print(f"   🎯 成功识别到当前角色主眼瞳贴图: {eye0_file}")
            eye0_p = os.path.join(texture_dir, eye0_file)

            # 提取动态命名的前缀 (如从 tex_chr1074_30_eye0.png 提取出 tex_chr1074_30_)
            prefix = ""
            for kw in ["eye0", "eye_0", "eye"]:
                if kw in eye0_file.lower():
                    idx = eye0_file.lower().rfind(kw)
                    prefix = eye0_file[:idx]
                    break

            # 动态拼接并定位对应的三层眼瞳高光贴图
            hi00_p = None
            hi01_p = None
            hi02_p = None

            if prefix:
                print(f"   📁 提取到当前角色贴图命名主前缀: '{prefix}'")
                # 尝试基于前缀推导常见命名组合
                for ext_name in [".png", ".tga", ".jpg"]:
                    c00 = os.path.join(texture_dir, f"{prefix}eyehi00{ext_name}")
                    c01 = os.path.join(texture_dir, f"{prefix}eyehi01{ext_name}")
                    c02 = os.path.join(texture_dir, f"{prefix}eyehi02{ext_name}")

                    if os.path.exists(c00):
                        hi00_p = c00
                    if os.path.exists(c01):
                        hi01_p = c01
                    if os.path.exists(c02):
                        hi02_p = c02

            # 兜底检索：若基于前缀没匹配上，进行全局模糊匹配
            if not hi00_p:
                for f in files:
                    fl = f.lower()
                    if "eyehi00" in fl or ("eye" in fl and "hi" in fl and "00" in fl):
                        hi00_p = os.path.join(texture_dir, f)
                        break
            if not hi01_p:
                for f in files:
                    fl = f.lower()
                    if "eyehi01" in fl or ("eye" in fl and "hi" in fl and "01" in fl):
                        hi01_p = os.path.join(texture_dir, f)
                        break
            if not hi02_p:
                for f in files:
                    fl = f.lower()
                    if "eyehi02" in fl or ("eye" in fl and "hi" in fl and "02" in fl):
                        hi02_p = os.path.join(texture_dir, f)
                        break

            # 开始无损合成
            print("   正在进行多层眼睛高光无损混合...")
            base_img = Image.open(eye0_p).convert("RGBA")
            w, h = base_img.size
            base_arr = np.array(base_img, dtype=np.float32)

            def process_hi_texture(path):
                if not path or not os.path.exists(path):
                    return None
                img = Image.open(path).convert("RGB")
                half_h = h // 2
                scaled = img.resize((w, half_h), Image.Resampling.LANCZOS)
                tiled = Image.new("RGB", (w, h))
                tiled.paste(scaled, (0, 0))
                tiled.paste(scaled, (0, half_h))
                return np.array(tiled, dtype=np.float32)

            hi00_arr = process_hi_texture(hi00_p)
            hi01_arr = process_hi_texture(hi01_p)
            hi02_arr = process_hi_texture(hi02_p)

            rgb = base_arr[:, :, :3]
            if hi02_arr is not None:
                rgb = rgb + hi02_arr * 0.35
            if hi00_arr is not None:
                rgb = rgb + hi00_arr * 0.8
            if hi01_arr is not None:
                rgb = rgb + hi01_arr * 0.8

            rgb = np.clip(rgb, 0, 255)
            base_arr[:, :, :3] = rgb

            baked_img = Image.fromarray(base_arr.astype(np.uint8), mode="RGBA")
            out_p = os.path.join(temp_dir, "tex_eye_baked_perfect.png")
            baked_img.save(out_p)

            img_data = bpy.data.images.load(out_p, check_existing=False)
            try:
                img_data.colorspace_settings.name = "sRGB"
            except Exception:
                pass
            img_data.pack()
            print("   ✅ 眼睛高光烘焙贴图保存至临时文件夹！")
        except Exception as e:
            print(f"   ⚠️ 眼睛高光烘焙失败: {e}")
    else:
        print("   ⚠️ 未在目录中检索到任何眼睛材质贴图，跳过眼睛高光烘焙。")

    # ================= 2. 多通道控制贴图拆解并导出至临时文件夹 =================
    parts = ["bdy", "face", "hair", "tail"]

    def find_file(part_kw, type_kw):
        for f in files:
            fl = f.lower()
            if part_kw in fl and type_kw in fl:
                return os.path.join(texture_dir, f)
        return None

    for part in parts:
        diff_path = find_file(part, "diff")
        base_path = find_file(part, "base")
        ctrl_path = find_file(part, "ctrl")

        if not diff_path:
            continue

        try:
            # 🌟 载入原本彩色、且自带完美 Alpha 透明通道的原始 diff 贴图
            diff_img = Image.open(diff_path).convert("RGBA")
            diff_arr = np.array(diff_img, dtype=np.float32)

            # 拆分 base 的通道
            if base_path:
                base_img = Image.open(base_path).convert("RGBA")
                base_arr = np.array(base_img, dtype=np.float32)

                # A. 提取阴影控制（Shading Grade）-> 采用 base 贴图的 R 通道
                r_chan = base_arr[:, :, 0]
                sg_arr = np.stack(
                    [r_chan, r_chan, r_chan, np.ones_like(r_chan) * 255], axis=-1
                )
                sg_arr = np.clip(sg_arr, 0, 255).astype(np.uint8)
                sg_img = Image.fromarray(sg_arr, mode="RGBA")
                sg_out = os.path.join(temp_dir, f"tex_{part}_shading_grade_vrm.png")
                sg_img.save(sg_out)

            # 保存合成处理后的标准彩色 Lit Color 贴图至临时文件夹（保持原装完美 Alpha 状态）
            out_diff_path = os.path.join(temp_dir, f"tex_{part}_lit_color_vrm.png")
            final_diff_img = Image.fromarray(
                np.clip(diff_arr, 0, 255).astype(np.uint8), mode="RGBA"
            )
            final_diff_img.save(out_diff_path)

            # 拆分 ctrl 的通道并提取自发光
            if ctrl_path:
                ctrl_img = Image.open(ctrl_path).convert("RGBA")
                ctrl_arr = np.array(ctrl_img, dtype=np.float32)

                # 提取 ctrl.b 自发光并与彩色图相乘
                b_chan_ctrl = ctrl_arr[:, :, 2] / 255.0
                diff_rgb = diff_arr[:, :, :3]
                em_rgb = diff_rgb * b_chan_ctrl[:, :, np.newaxis]
                em_alpha = ctrl_arr[:, :, 2]

                em_arr = np.zeros_like(diff_arr)
                em_arr[:, :, :3] = em_rgb
                em_arr[:, :, 3] = em_alpha

                em_img = Image.fromarray(
                    np.clip(em_arr, 0, 255).astype(np.uint8), mode="RGBA"
                )
                em_out = os.path.join(temp_dir, f"tex_{part}_emissive_baked.png")
                em_img.save(em_out)

            print(f"   ✅ [处理完成] 部位 [{part}] 的贴图已解出并输出到临时目录。")
        except Exception as e:
            print(f"   ⚠️ 部位 [{part}] 通道拆解失败: {e}")

    print("✅ [步骤 4] 所有合成、拆分产生的贴图均已安全存入 vrm_temp_baked 文件夹下！")
