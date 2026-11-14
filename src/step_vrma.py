import os

import bpy


def run(config):
    raw_paths = []
    if config.get("vrma_path"):
        raw_paths.append(config["vrma_path"])
    if isinstance(config.get("vrma_paths"), list):
        raw_paths.extend([p for p in config["vrma_paths"] if p])

    if not raw_paths:
        print("ℹ️ [步骤 VRMA] config.json 未配置 vrma_path，跳过动作导入。")
        return

    armature_obj = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if not armature_obj:
        print("⚠️ [步骤 VRMA] 未找到骨骼对象，跳过 VRMA 导入。")
        return

    ext = getattr(armature_obj.data, "vrm_addon_extension", None)
    if not ext:
        print("⚠️ [步骤 VRMA] 未开启 VRM 插件，跳过 VRMA 导入。")
        return

    # VRM 插件导入 VRMA 要求目标模型为 VRM 1.0
    if ext.spec_version != "1.0":
        ext.spec_version = "1.0"

    bpy.context.view_layer.objects.active = armature_obj
    armature_obj.select_set(True)

    if not armature_obj.animation_data:
        armature_obj.animation_data_create()

    imported_count = 0
    for vrma_path in raw_paths:
        if not os.path.exists(vrma_path):
            print(f"⚠️ [步骤 VRMA] 文件不存在，已跳过: {vrma_path}")
            continue

        actions_before = set(bpy.data.actions)
        result = bpy.ops.import_scene.vrma(
            filepath=vrma_path,
            armature_object_name=armature_obj.name,
        )
        if result != {"FINISHED"}:
            print(f"⚠️ [步骤 VRMA] 导入失败 ({result}): {vrma_path}")
            continue

        clip_name = os.path.splitext(os.path.basename(vrma_path))[0]
        new_actions = [
            a
            for a in (set(bpy.data.actions) - actions_before)
            if a.name != "Expressions"
        ]

        # 单个动作直接设为当前激活 Action；多个动作推入 NLA 轨道避免互相覆盖
        if len(raw_paths) == 1 and new_actions:
            act = new_actions[0]
            act.name = clip_name
            armature_obj.animation_data.action = act
        else:
            for act in new_actions:
                act.name = (
                    clip_name if len(new_actions) == 1 else f"{clip_name}_{act.name}"
                )
                track = armature_obj.animation_data.nla_tracks.new()
                track.name = act.name
                track.strips.new(act.name, int(act.frame_range[0]), act)

        imported_count += 1
        print(f"   🎬 已导入 VRMA 动作: {clip_name}")

    print(f"✅ [步骤 VRMA] 完成！共导入 {imported_count} 个 VRMA 动作。")
