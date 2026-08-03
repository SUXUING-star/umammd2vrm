import os

import bpy

import step0_clean
import step1_skeleton
import step2_expressions
import step3_bind_vrm
import step4_eye_bake
import step5_new_texture_nodes
import step6_metadata


def resolve_config_paths(config):
    """
    统一解析 config 中的相对路径：
    - blend_dir: .blend 文件所在目录 (如 public/mejiro bright mizugi/)
    - project_root: 项目根目录 (即 public/ 的上级目录)
    """
    blend_dir = bpy.path.abspath("//")
    project_root = os.path.abspath(os.path.join(blend_dir, "..", ".."))

    # 1. 解析 texture_dir (相对 .blend 目录)
    tex_dir = config.get("texture_dir", "Texture2D")
    if not os.path.isabs(tex_dir):
        config["texture_dir"] = os.path.abspath(os.path.join(blend_dir, tex_dir))

    # 2. 解析 models_dir 与 blenders_dir (相对项目根目录 project_root)
    models_dir = config.get("models_dir", "public")
    if not os.path.isabs(models_dir):
        config["models_dir"] = os.path.abspath(os.path.join(project_root, models_dir))

    blenders_dir = config.get("blenders_dir", "public")
    if not os.path.isabs(blenders_dir):
        config["blenders_dir"] = os.path.abspath(
            os.path.join(project_root, blenders_dir)
        )

    # 3. 解析 metadata 中的缩略图路径 (若存在)
    meta = config.get("metadata", {})
    thumb = meta.get("thumbnail_path", "")
    if thumb and not os.path.isabs(thumb):
        meta["thumbnail_path"] = os.path.abspath(os.path.join(blend_dir, thumb))

    return config


def run(config):
    # 规整并补全 config 中的所有路径
    config = resolve_config_paths(config)

    jp = config["jp_name"]
    en = config["en_name"]
    tex = config["texture_dir"]

    print(f"\n>>> 开始处理模型: {jp} -> {en}")
    print(f"   [路径] 模型/文件根目录: {config['models_dir']}")
    print(f"   [路径] 贴图绝对路径: {tex}")

    step0_clean.run()
    step1_skeleton.run(jp, en)  # 执行改名主逻辑
    step2_expressions.run()
    step3_bind_vrm.run()
    step4_eye_bake.run(tex)
    step5_new_texture_nodes.run(tex)

    # 传入规整后的 config 给 metadata 步骤
    step6_metadata.run(config)
