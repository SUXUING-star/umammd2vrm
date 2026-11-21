import os

import bpy

import step0_clean
import step1_skeleton
import step2_shapekey
import step3_bind_vrm
import step4_bake_texture
import step5_mtoon_materials
import step6_metadata
import step_vrma


def resolve_config_paths(config):
    blend_dir = bpy.path.abspath("//")

    tex_dir = config.get("texture_dir")
    if not tex_dir:
        tex_dir = (
            "TEX" if os.path.exists(os.path.join(blend_dir, "TEX")) else "Texture2D"
        )
    if not os.path.isabs(tex_dir):
        config["texture_dir"] = os.path.abspath(os.path.join(blend_dir, tex_dir))

    models_dir = config.get("models_dir") or "."
    if not os.path.isabs(models_dir):
        config["models_dir"] = os.path.abspath(os.path.join(blend_dir, models_dir))

    blenders_dir = config.get("blenders_dir") or "."
    if not os.path.isabs(blenders_dir):
        config["blenders_dir"] = os.path.abspath(os.path.join(blend_dir, blenders_dir))

    meta = config.get("metadata", {})
    thumb = meta.get("thumbnail_path", "")
    if thumb and not os.path.isabs(thumb):
        meta["thumbnail_path"] = os.path.abspath(os.path.join(blend_dir, thumb))

    vrma = config.get("vrma_path", "")
    if vrma and not os.path.isabs(vrma):
        config["vrma_path"] = os.path.abspath(os.path.join(blend_dir, vrma))

    if isinstance(config.get("vrma_paths"), list):
        config["vrma_paths"] = [
            os.path.abspath(os.path.join(blend_dir, p))
            if p and not os.path.isabs(p)
            else p
            for p in config["vrma_paths"]
        ]

    return config


def run(config):
    config = resolve_config_paths(config)

    jp = config["jp_name"]
    en = config["en_name"]
    tex = config["texture_dir"]
    max_tex_size = int(config.get("max_tex_size", 1024))
    max_bones = int(config.get("max_bones", 240))
    ground_to_zero = bool(config.get("ground_to_zero", True))
    fix_high_heel_rig = bool(config.get("fix_high_heel_rig", False))

    print(f"\n>>> [umammd2vrm] 开始处理模型: {jp} -> {en}")
    print(f"   [路径] VRM 导出目录: {config['models_dir']}")
    print(
        f"   [路径] 贴图绝对路径: {tex} "
        f"(max_tex_size={max_tex_size}, max_bones={max_bones}, ground_to_zero={ground_to_zero}, fix_high_heel_rig={fix_high_heel_rig})"
    )

    step0_clean.run()
    step1_skeleton.run(
        jp,
        en,
        max_bones=max_bones,
        ground_to_zero=ground_to_zero,
        fix_high_heel_rig=True,
    )
    step2_shapekey.run()
    step3_bind_vrm.run()
    step4_bake_texture.run(tex)
    step5_mtoon_materials.run(tex)
    step_vrma.run(config)
    step6_metadata.run(config)
