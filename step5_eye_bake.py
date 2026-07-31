# --- START OF FILE step5_eye_bake.py ---
import os

import bpy


def run(texture_dir):
    print(">>> [步骤 5/6] 开始制作赛马娘眼睛高光烘焙贴图...")

    if not os.path.exists(texture_dir):
        print(f"❌ 贴图目录不存在: {texture_dir}")
        return

    eye0_p = os.path.join(texture_dir, "tex_chr1074_30_eye0.png")
    hi00_p = os.path.join(texture_dir, "tex_chr1074_30_eyehi00.png")
    hi01_p = os.path.join(texture_dir, "tex_chr1074_30_eyehi01.png")
    hi02_p = os.path.join(texture_dir, "tex_chr1074_30_eyehi02.png")

    if not os.path.exists(eye0_p):
        print("⚠️ 未找到基础眼睛贴图(tex_chr1074_30_eye0.png)，跳过高光烘焙步骤。")
        return

    try:
        import numpy as np
        from PIL import Image

        print("   正在执行多层高光无损混合运算...")
        base_img = Image.open(eye0_p).convert("RGBA")
        w, h = base_img.size
        base_arr = np.array(base_img, dtype=np.float32)

        def process_hi_texture(path):
            if not os.path.exists(path):
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
        out_p = os.path.join(texture_dir, "tex_eye_baked_perfect.png")
        baked_img.save(out_p)

        img_data = bpy.data.images.load(out_p, check_existing=False)
        try:
            img_data.colorspace_settings.name = "sRGB"
        except Exception:
            pass
        img_data.pack()
        print("✅ [步骤 5/6] 眼睛贴图高光烘焙与数据打包完成！")
    except Exception as e:
        print(f"⚠️ 烘焙眼睛贴图时遇到异常: {e}")
