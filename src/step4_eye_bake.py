# --- START OF FILE step4_eye_bake.py ---
import os

import bpy
import numpy as np
from PIL import Image


def run(texture_dir):
    print(">>> [步骤 4] 开始执行多通道数据提取、阴影合成与贴图烘焙...")

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    temp_dir = os.path.join(texture_dir, "vrm_temp_baked")
    os.makedirs(temp_dir, exist_ok=True)

    files = os.listdir(texture_dir)

    # ================= 1. 眼睛贴图无损高光合成 =================
    eye0_file = None
    for f in files:
        fl = f.lower()
        if "eye" in fl and ("0" in fl or "base" in fl) and "hi" not in fl:
            eye0_file = f
            break
    if not eye0_file:
        for f in files:
            fl = f.lower()
            if "eye" in fl and "hi" not in fl:
                eye0_file = f
                break

    if eye0_file:
        try:
            eye0_p = os.path.join(texture_dir, eye0_file)
            prefix = ""
            for kw in ["eye0", "eye_0", "eye"]:
                if kw in eye0_file.lower():
                    idx = eye0_file.lower().rfind(kw)
                    prefix = eye0_file[:idx]
                    break

            hi00_p, hi01_p, hi02_p = None, None, None
            if prefix:
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
                rgb += hi02_arr * 0.35
            if hi00_arr is not None:
                rgb += hi00_arr * 0.8
            if hi01_arr is not None:
                rgb += hi01_arr * 0.8

            base_arr[:, :, :3] = np.clip(rgb, 0, 255)
            baked_img = Image.fromarray(base_arr.astype(np.uint8), mode="RGBA")
            out_p = os.path.join(temp_dir, "tex_eye_baked_perfect.png")
            baked_img.save(out_p)

            img_data = bpy.data.images.load(out_p, check_existing=False)
            try:
                img_data.colorspace_settings.name = "sRGB"
            except Exception:
                pass
            img_data.pack()
        except Exception as e:
            print(f"   ⚠️ 眼睛高光烘焙失败: {e}")

    # ================= 2. 多通道数据解算（diff, shad_c, base, ctrl, rfl） =================
    parts = ["bdy", "face", "hair", "tail"]

    def find_file(part_kw, type_kw):
        for f in files:
            fl = f.lower()
            if part_kw in fl and type_kw in fl:
                return os.path.join(texture_dir, f)
        return None

    for part in parts:
        diff_path = find_file(part, "diff") or find_file(part, "base")
        shad_path = find_file(part, "shad")  # 包含 shad_c 或 shad
        base_path = find_file(part, "base")  # 包含数据遮罩 (R: Shading Grade)
        ctrl_path = find_file(part, "ctrl")  # 包含数据遮罩 (B: Emissive)
        rfl_path = find_file(part, "rfl")  # 包含 MatCap 高光数据

        if not diff_path:
            continue

        try:
            diff_img = Image.open(diff_path).convert("RGBA")
            diff_arr = np.array(diff_img, dtype=np.float32)

            # A. 导出的 Lit Color 通道
            out_diff_path = os.path.join(temp_dir, f"tex_{part}_lit_color_vrm.png")
            diff_img.save(out_diff_path)

            # B. 阴影贴图 (Shade Color) 解析
            shade_out = os.path.join(temp_dir, f"tex_{part}_shade_color_vrm.png")
            if shad_path and os.path.exists(shad_path):
                # 优先使用提取出的专用阴影色彩贴图 shad_c / shad
                shad_img = Image.open(shad_path).convert("RGBA")
                shad_img.save(shade_out)
            elif base_path and os.path.exists(base_path):
                # 若无 shad_c，利用 base 贴图的 R 通道 (Shading Grade Map) 与 diff 像素相乘，合成准确阴影
                base_img = Image.open(base_path).convert("RGBA")
                base_arr = np.array(base_img, dtype=np.float32)
                shading_grade = base_arr[:, :, 0] / 255.0  # R Channel Shading Grade

                shade_rgb = diff_arr[:, :, :3] * shading_grade[:, :, np.newaxis]
                shade_arr = np.dstack([shade_rgb, diff_arr[:, :, 3]])
                shade_img = Image.fromarray(
                    np.clip(shade_arr, 0, 255).astype(np.uint8), mode="RGBA"
                )
                shade_img.save(shade_out)

            # C. 提取 ctrl.b 自发光通道
            if ctrl_path and os.path.exists(ctrl_path):
                ctrl_img = Image.open(ctrl_path).convert("RGBA")
                ctrl_arr = np.array(ctrl_img, dtype=np.float32)

                b_chan_ctrl = ctrl_arr[:, :, 2] / 255.0
                em_rgb = diff_arr[:, :, :3] * b_chan_ctrl[:, :, np.newaxis]
                em_alpha = ctrl_arr[:, :, 2]

                em_arr = np.dstack([em_rgb, em_alpha])
                em_img = Image.fromarray(
                    np.clip(em_arr, 0, 255).astype(np.uint8), mode="RGBA"
                )
                em_out = os.path.join(temp_dir, f"tex_{part}_emissive_baked.png")
                em_img.save(em_out)

            # D. 提取 rfl 通道 (MatCap 高光反射)
            if rfl_path and os.path.exists(rfl_path):
                rfl_img = Image.open(rfl_path).convert("RGBA")
                rfl_out = os.path.join(temp_dir, f"tex_{part}_matcap_vrm.png")
                rfl_img.save(rfl_out)

            print(f"   ✅ [解算完成] 部位 [{part}] 的通道数据已解出输出到临时目录。")
        except Exception as e:
            print(f"   ⚠️ 部位 [{part}] 通道解算失败: {e}")

    print("✅ [步骤 4] 多通道数据拆解与阴影合成完毕！")
