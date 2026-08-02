import re

import bpy


def auto_assign_vrm_humanoid(armature_obj):
    ext = getattr(armature_obj.data, "vrm_addon_extension", None)
    if not ext:
        return

    mapping = {
        "hips": ["Hips", "Hip", "下半身"],
        "spine": ["Spine", "上半身"],
        "chest": ["Chest", "上半身2", "胸"],
        "neck": ["Neck", "首"],
        "head": ["Head", "頭"],
        "leftShoulder": ["ShoulderL", "Shoulder_L", "左肩"],
        "leftUpperArm": ["UpperArmL", "Arm_L", "左腕"],
        "leftLowerArm": ["LowerArmL", "Elbow_L", "左ひじ"],
        "leftHand": ["HandL", "Wrist_L", "Hand_L", "左手首"],
        "rightShoulder": ["ShoulderR", "Shoulder_R", "右肩"],
        "rightUpperArm": ["UpperArmR", "Arm_R", "右腕"],
        "rightLowerArm": ["LowerArmR", "Elbow_R", "右ひじ"],
        "rightHand": ["HandR", "Wrist_R", "Hand_R", "右手首"],
        "leftUpperLeg": ["UpperLegL", "Leg_L", "左足"],
        "leftLowerLeg": ["LowerLegL", "Knee_L", "左ひざ"],
        "leftFoot": ["FootL", "Ankle_L", "左足首"],
        "leftToes": ["ToesL", "Toe_L", "左つま先"],
        "rightUpperLeg": ["UpperLegR", "Leg_R", "右足"],
        "rightLowerLeg": ["LowerLegR", "Knee_R", "右ひざ"],
        "rightFoot": ["FootR", "Ankle_R", "右足首"],
        "rightToes": ["ToesR", "Toe_R", "右つま先"],
    }

    if hasattr(ext, "vrm0") and hasattr(ext.vrm0, "humanoid"):
        for hb in ext.vrm0.humanoid.human_bones:
            vrm_key = hb.bone
            if vrm_key in mapping:
                for candidate in mapping[vrm_key]:
                    if candidate in armature_obj.data.bones:
                        hb.node.bone_name = candidate
                        break

    if hasattr(ext, "vrm1") and hasattr(ext.vrm1, "humanoid"):
        h_bones = ext.vrm1.humanoid.human_bones
        for attr_name, candidates in mapping.items():
            if hasattr(h_bones, attr_name):
                hb_item = getattr(h_bones, attr_name)
                for candidate in candidates:
                    if candidate in armature_obj.data.bones:
                        if hasattr(hb_item, "node"):
                            hb_item.node.bone_name = candidate
                        break


def run(jp_model_name, en_model_name):

    GARBAGE_BONE_KEYWORDS = [
        "Pole",
        "Target",
        "Handle",
        "mmd_shadow",
        "mmd_dummy",
        "dummy",
        "shadow",
        "IK_parent",
        "eye_control",
        "_end",
    ]

    CUSTOM_BONE_MAP = {
        "Position": "Root",
        "全ての亲": "Root",
        "Hip": "Hips",
        "下半身": "Hips",
        "hips": "Hips",
        "Spine": "Spine",
        "上半身": "Spine",
        "spine": "Spine",
        "Chest": "Chest",
        "上半身2": "Chest",
        "胸": "Chest",
        "chest": "Chest",
        "upperChest": "Chest",
        "Neck": "Neck",
        "首": "Neck",
        "neck": "Neck",
        "Head": "Head",
        "頭": "Head",
        "head": "Head",
        "Shoulder_L": "ShoulderL",
        "左肩": "ShoulderL",
        "leftShoulder": "ShoulderL",
        "Arm_L": "UpperArmL",
        "UpperArm_L": "UpperArmL",
        "左腕": "UpperArmL",
        "leftUpperArm": "UpperArmL",
        "Elbow_L": "LowerArmL",
        "LowerArm_L": "LowerArmL",
        "左ひじ": "LowerArmL",
        "leftLowerArm": "LowerArmL",
        "Wrist_L": "HandL",
        "Hand_L": "HandL",
        "左手首": "HandL",
        "leftHand": "HandL",
        "Shoulder_R": "ShoulderR",
        "rightShoulder": "ShoulderR",
        "Arm_R": "UpperArmR",
        "UpperArm_R": "UpperArmR",
        "右腕": "UpperArmR",
        "rightUpperArm": "UpperArmR",
        "Elbow_R": "LowerArmR",
        "LowerArm_R": "LowerArmR",
        "右ひじ": "LowerArmR",
        "rightLowerArm": "LowerArmR",
        "Wrist_R": "HandR",
        "Hand_R": "HandR",
        "右手首": "HandR",
        "rightHand": "HandR",
        "Thigh_L": "UpperLegL",
        "Leg_L": "UpperLegL",
        "左足": "UpperLegL",
        "leftUpperLeg": "UpperLegL",
        "Knee_L": "LowerLegL",
        "左ひざ": "LowerLegL",
        "leftLowerLeg": "LowerLegL",
        "Ankle_L": "FootL",
        "Foot_L": "FootL",
        "左足首": "FootL",
        "leftFoot": "FootL",
        "Toe_L": "ToesL",
        "左つま先": "ToesL",
        "leftToes": "ToesL",
        "Thigh_R": "UpperLegR",
        "Leg_R": "UpperLegR",
        "右足": "UpperLegR",
        "rightUpperLeg": "UpperLegR",
        "Knee_R": "LowerLegR",
        "rightLowerLeg": "LowerLegR",
        "Ankle_R": "FootR",
        "Foot_R": "FootR",
        "右足首": "FootR",
        "rightFoot": "FootR",
        "Toe_R": "ToesR",
        "右つま先": "ToesR",
        "rightToes": "ToesR",
    }

    print(">>> [步骤 1] 规整骨骼命名与层级...")
    armature_obj = next(
        (obj for obj in bpy.data.objects if obj.type == "ARMATURE"), None
    )
    if armature_obj:
        bpy.context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode="EDIT")
        edit_bones = armature_obj.data.edit_bones

        bones_to_remove = [
            b.name
            for b in edit_bones
            if any(kw in b.name for kw in GARBAGE_BONE_KEYWORDS)
        ]
        for b_name in bones_to_remove:
            if b_name in edit_bones:
                edit_bones.remove(edit_bones[b_name])

        root_b = edit_bones.get("Position") or edit_bones.get("Root")
        hips_b = edit_bones.get("Hip") or edit_bones.get("Hips")
        if hips_b and root_b:
            hips_b.parent = root_b

        bpy.ops.object.mode_set(mode="OBJECT")

        for bone in armature_obj.data.bones:
            if bone.name in CUSTOM_BONE_MAP:
                bone.name = CUSTOM_BONE_MAP[bone.name]

        for child in armature_obj.children:
            if child.type == "MESH":
                for vg in child.vertex_groups:
                    if vg.name in CUSTOM_BONE_MAP:
                        vg.name = CUSTOM_BONE_MAP[vg.name]

        auto_assign_vrm_humanoid(armature_obj)

    for obj in bpy.data.objects:
        if jp_model_name in obj.name and not re.search(r"\.\d+$", obj.name):
            obj.name = obj.name.replace(jp_model_name, en_model_name)
    for mesh in bpy.data.meshes:
        if jp_model_name in mesh.name:
            mesh.name = mesh.name.replace(jp_model_name, en_model_name)
    for arm in bpy.data.armatures:
        if jp_model_name in arm.name:
            arm.name = arm.name.replace(jp_model_name, en_model_name)
    for coll in bpy.data.collections:
        if jp_model_name in coll.name:
            coll.name = coll.name.replace(jp_model_name, en_model_name)
    print("✅ [步骤 1] 骨骼与命名处理完成！")
