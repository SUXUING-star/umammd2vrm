import os

import bpy
import numpy as np
from PIL import Image


def run(texture_dir):
    print(">>> [步骤 4] 开始根据 HLSL 渲染方程解算多通道贴图与阴影烘焙...")

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    temp_dir = os.path.join(texture_dir, "vrm_temp_baked")
    os.makedirs(temp_dir, exist_ok=True)

    files = os.listdir(texture_dir)

    # ================= 1. 眼睛贴图：HLSL 阈值截断加法合成 (HLSL Eye Frag) =================
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

            # -------------------------------------------------------------
            # 【HLSL 核心修复】：还原 Eye PS 阶段高光门限截断计算
            # HLSL 公式: r1.x = hi * weight - _Limit (默认 0.1)
            #           r0.y = max(0, step(0, r1.x) * r1.x)
            # -------------------------------------------------------------
            LIMIT = 0.1 * 255.0  # 映射到 0-255 空间

            def apply_hlsl_eye_hi_threshold(base_rgb, hi_arr, weight):
                if hi_arr is None:
                    return base_rgb
                # 提取单通道灰度 * 权重
                hi_val = hi_arr[:, :, 0] * weight
                # 减去 _Limit 截断门限，小于 0 的强行归零
                hi_val = np.maximum(0.0, hi_val - LIMIT)
                # 加色混合到基色
                return base_rgb + hi_val[:, :, np.newaxis]

            rgb = apply_hlsl_eye_hi_threshold(rgb, hi02_arr, 0.35)
            rgb = apply_hlsl_eye_hi_threshold(rgb, hi00_arr, 0.80)
            rgb = apply_hlsl_eye_hi_threshold(rgb, hi01_arr, 0.80)

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

    # ================= 2. 多通道数据解算（diff, shad_c, base, ctrl） =================
    parts = ["bdy", "face", "hair", "tail"]

    def find_file(part_kw, type_kw):
        for f in files:
            fl = f.lower()
            if part_kw in fl and type_kw in fl:
                return os.path.join(texture_dir, f)
        return None

    for part in parts:
        diff_path = find_file(part, "diff") or find_file(part, "base")
        shad_path = find_file(part, "shad")
        base_path = find_file(part, "base")
        ctrl_path = find_file(part, "ctrl")
        emiss_path = find_file(part, "emissive") or find_file(part, "emi")

        if not diff_path:
            continue

        try:
            diff_img = Image.open(diff_path).convert("RGBA")
            diff_arr = np.array(diff_img, dtype=np.float32)

            # A. 固有色 (Lit Color)
            out_diff_path = os.path.join(temp_dir, f"tex_{part}_lit_color_vrm.png")
            diff_img.save(out_diff_path)

            # B. 提取 base.r 阴影推移图 (Shading Shift)
            # HLSL 物理含义: base.r 是 HalfLambert 的乘算系数 (1.0=受光, 0.0=锁死阴影)
            if base_path and os.path.exists(base_path):
                base_img = Image.open(base_path).convert("RGBA")
                base_arr = np.array(base_img, dtype=np.float32)

                shading_shift_arr = base_arr[:, :, 0].astype(np.uint8)
                shift_img = Image.fromarray(shading_shift_arr, mode="L")
                shift_out = os.path.join(temp_dir, f"tex_{part}_shading_shift_vrm.png")
                shift_img.save(shift_out)

            # C. 阴影贴图 (Shade Color)
            shade_out = os.path.join(temp_dir, f"tex_{part}_shade_color_vrm.png")
            if shad_path and os.path.exists(shad_path):
                # 存在官方暗部贴图 (shad_c) 时直接使用
                shad_img = Image.open(shad_path).convert("RGBA")
                shad_img.save(shade_out)
            else:
                # -------------------------------------------------------------
                # 【HLSL 核心修复】：缺失 shad_c 时的降级阴影公式
                # 修正：绝不能拿 base.r 乘 diff！改为应用 HLSL 的冷色调压暗矩阵
                # -------------------------------------------------------------
                cool_dark_tint = np.array(
                    [0.72, 0.70, 0.80], dtype=np.float32
                )  # HLSL _ToonDarkColor 默认冷灰色调
                shade_rgb = (
                    diff_arr[:, :, :3] * cool_dark_tint[np.newaxis, np.newaxis, :]
                )
                shade_arr = np.dstack([shade_rgb, diff_arr[:, :, 3]])
                shade_img = Image.fromarray(
                    np.clip(shade_arr, 0, 255).astype(np.uint8), mode="RGBA"
                )
                shade_img.save(shade_out)

            # D. 自发光 (Emissive)
            # -------------------------------------------------------------
            # 【HLSL 核心修复】：纠正 OptionMask.b 不是自发光 Mask 的错误
            # HLSL 中自发光独立采样 _EmissiveTex。若不存在则不生成假自发光
            # -------------------------------------------------------------
            if emiss_path and os.path.exists(emiss_path):
                em_img = Image.open(emiss_path).convert("RGBA")
                em_out = os.path.join(temp_dir, f"tex_{part}_emissive_baked.png")
                em_img.save(em_out)

            print(f"   ✅ [解算完成] 部位 [{part}] 通道数据提取完毕。")
        except Exception as e:
            print(f"   ⚠️ 部位 [{part}] 通道解算失败: {e}")

    print("✅ [步骤 4] 贴图解算完毕！")
