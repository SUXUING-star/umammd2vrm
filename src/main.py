import os

import bpy
import step_vrma

import step0_clean
import step1_skeleton
import step2_expressions
import step3_bind_vrm
import step4_bake_texture
import step5_mtoon_materials
import step6_metadata


def resolve_config_paths(config):
    blend_dir = bpy.path.abspath("//")
    project_root = os.path.abspath(os.path.join(blend_dir, "..", ".."))

    tex_dir = config.get("texture_dir", "Texture2D")
    if not os.path.isabs(tex_dir):
        config["texture_dir"] = os.path.abspath(os.path.join(blend_dir, tex_dir))

    models_dir = config.get("models_dir", "public")
    if not os.path.isabs(models_dir):
        config["models_dir"] = os.path.abspath(os.path.join(project_root, models_dir))

    blenders_dir = config.get("blenders_dir", "public")
    if not os.path.isabs(blenders_dir):
        config["blenders_dir"] = os.path.abspath(
            os.path.join(project_root, blenders_dir)
        )

    meta = config.get("metadata", {})
    thumb = meta.get("thumbnail_path", "")
    if thumb and not os.path.isabs(thumb):
        meta["thumbnail_path"] = os.path.abspath(os.path.join(blend_dir, thumb))

    # 解析单个 vrma_path（相对 .blend 目录）
    vrma = config.get("vrma_path", "")
    if vrma and not os.path.isabs(vrma):
        config["vrma_path"] = os.path.abspath(os.path.join(blend_dir, vrma))

    # 兼容多个 vrma_paths 列表
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

    print(f"\n>>> 开始处理模型: {jp} -> {en}")
    print(f"   [路径] 模型/文件根目录: {config['models_dir']}")
    print(f"   [路径] 贴图绝对路径: {tex}")

    step0_clean.run()
    step1_skeleton.run(jp, en)
    step2_expressions.run()
    step3_bind_vrm.run()
    step4_bake_texture.run(tex)
    step5_mtoon_materials.run(tex)
    step_vrma.run(config)
    step6_metadata.run(config)
