# --- START OF FILE step4_eye_bake.py ---
import os

import bpy
import numpy as np
from PIL import Image


def run(texture_dir):
    print(">>> [步骤 4] 开始执行多通道贴图拆解与数据遮罩提取...")

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    temp_dir = os.path.join(texture_dir, "vrm_temp_baked")
    os.makedirs(temp_dir, exist_ok=True)
    print(f"   已建立/确认临时导出文件夹: {temp_dir}")

    files = os.listdir(texture_dir)

    # ================= 1. 动态匹配眼睛贴图与高光合成 =================
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
            print(f"   🎯 成功识别主眼瞳贴图: {eye0_file}")
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

            if not hi00_p:
                for f in files:
                    if "eyehi00" in f.lower():
                        hi00_p = os.path.join(texture_dir, f)
                        break
            if not hi01_p:
                for f in files:
                    if "eyehi01" in f.lower():
                        hi01_p = os.path.join(texture_dir, f)
                        break
            if not hi02_p:
                for f in files:
                    if "eyehi02" in f.lower():
                        hi02_p = os.path.join(texture_dir, f)
                        break

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

            base_arr[:, :, :3] = np.clip(rgb, 0, 255)
            baked_img = Image.fromarray(base_arr.astype(np.uint8), mode="RGBA")
            baked_img.save(os.path.join(temp_dir, "tex_eye_baked_perfect.png"))
            print("   ✅ 眼睛高光烘焙完成。")
        except Exception as e:
            print(f"   ⚠️ 眼睛高光烘焙失败: {e}")

    # ================= 2. 多通道数据通道提取 (base, ctrl, shad_c) =================
    parts = ["bdy", "face", "hair", "tail"]

    def find_file(part_kw, type_kw):
        for f in files:
            fl = f.lower()
            if part_kw in fl and type_kw in fl:
                return os.path.join(texture_dir, f)
        return None

    for part in parts:
        diff_path = find_file(part, "diff")
        shad_c_path = find_file(part, "shad_c")
        base_path = find_file(part, "base")
        ctrl_path = find_file(part, "ctrl")

        if not diff_path:
            continue

        try:
            # A. 提取 Diffuse (Lit Color)
            diff_img = Image.open(diff_path).convert("RGBA")
            diff_img.save(os.path.join(temp_dir, f"tex_{part}_lit_color_vrm.png"))

            # B. 提取 Shad_C (Shade Color - 正常的原生影色图)
            if shad_c_path and os.path.exists(shad_c_path):
                shad_c_img = Image.open(shad_c_path).convert("RGBA")
                shad_c_img.save(
                    os.path.join(temp_dir, f"tex_{part}_shade_color_vrm.png")
                )

            # C. 解析 Base 多通道数据图 (提取 R 通道 -> Shading Shift 阴影偏移遮罩)
            if base_path and os.path.exists(base_path):
                base_img = Image.open(base_path).convert("RGBA")
                base_arr = np.array(base_img, dtype=np.float32)
                r_chan = base_arr[:, :, 0]  # R 通道为阴影阈值遮罩

                # 输出单通道/RGB 阴影偏移贴图
                shift_arr = np.stack(
                    [r_chan, r_chan, r_chan, np.ones_like(r_chan) * 255], axis=-1
                )
                shift_img = Image.fromarray(
                    np.clip(shift_arr, 0, 255).astype(np.uint8), mode="RGBA"
                )
                shift_img.save(
                    os.path.join(temp_dir, f"tex_{part}_shading_shift_vrm.png")
                )

            # D. 解析 Ctrl 多通道数据图 (提取 R 通道 -> Rim 遮罩, B 通道 -> Emissive 自发光)
            if ctrl_path and os.path.exists(ctrl_path):
                ctrl_img = Image.open(ctrl_path).convert("RGBA")
                ctrl_arr = np.array(ctrl_img, dtype=np.float32)

                # R 通道: Rim Mask
                r_chan = ctrl_arr[:, :, 0]
                if np.max(r_chan) > 5:
                    rim_arr = np.stack(
                        [r_chan, r_chan, r_chan, np.ones_like(r_chan) * 255], axis=-1
                    )
                    rim_img = Image.fromarray(
                        np.clip(rim_arr, 0, 255).astype(np.uint8), mode="RGBA"
                    )
                    rim_img.save(os.path.join(temp_dir, f"tex_{part}_rim_mask_vrm.png"))

                # B 通道: Emissive
                b_chan = ctrl_arr[:, :, 2]
                if np.max(b_chan) > 5:
                    diff_arr = np.array(diff_img, dtype=np.float32)
                    em_factor = (b_chan / 255.0)[:, :, np.newaxis]
                    em_rgb = diff_arr[:, :, :3] * em_factor
                    em_arr = np.zeros_like(diff_arr)
                    em_arr[:, :, :3] = em_rgb
                    em_arr[:, :, 3] = b_chan
                    em_img = Image.fromarray(
                        np.clip(em_arr, 0, 255).astype(np.uint8), mode="RGBA"
                    )
                    em_img.save(
                        os.path.join(temp_dir, f"tex_{part}_emissive_baked.png")
                    )

            print(f"   ✅ 部位 [{part}] 数据通道提取完成。")
        except Exception as e:
            print(f"   ⚠️ 部位 [{part}] 通道拆解失败: {e}")

    print("✅ [步骤 4] 所有贴图与多通道遮罩提取完成！")
