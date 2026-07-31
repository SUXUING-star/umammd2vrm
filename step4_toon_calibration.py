import bpy

from utils import safe_set_vrm_prop


def run():
    print(">>> [步骤 4] 配置 MToon 着色器阴影与反射隔离...")
    try:
        bpy.context.scene.view_settings.view_transform = "Standard"
    except Exception:
        pass

    ALLOW_ALPHA_KEYWORDS = [
        "lash",
        "mayu",
        "eyelash",
        "shadow",
        "dec",
        "trans",
        "eye",
        "pupil",
        "highlight",
        "alpha",
        "眉",
        "睫",
        "透",
    ]

    armature_obj = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    mesh_obj = None
    if armature_obj:
        for child in armature_obj.children:
            if child.type == "MESH" and child.data.shape_keys:
                if len(child.data.shape_keys.key_blocks) > 50:
                    mesh_obj = child
                    break

    if mesh_obj:
        for mod in list(mesh_obj.modifiers):
            if mod.type != "ARMATURE":
                mesh_obj.modifiers.remove(mod)
        try:
            for poly in mesh_obj.data.polygons:
                poly.use_smooth = True
        except Exception:
            pass

    for mat in bpy.data.materials:
        if not mat or not mat.use_nodes:
            continue

        mat_name_lower = mat.name.lower()
        is_transparent = any(kw in mat_name_lower for kw in ALLOW_ALPHA_KEYWORDS)
        is_eye = any(
            kw in mat_name_lower for kw in ["eye", "pupil", "highlight", "目", "瞳"]
        )

        mat.use_backface_culling = True

        try:
            mat.blend_method = "CLIP" if (is_eye or is_transparent) else "OPAQUE"
        except TypeError:
            mat.blend_method = "ALPHA_CLIP" if (is_eye or is_transparent) else "OPAQUE"

        mtoon_ext = getattr(mat, "vrm_addon_extension", None)
        if mtoon_ext:
            is_clothes = any(
                kw in mat_name_lower
                for kw in ["bdy", "tail", "skirt", "dress", "cloth", "体", "服", "衣"]
            )
            is_face_or_hair = any(
                kw in mat_name_lower
                for kw in ["face", "kao", "skin", "hair", "kami", "顔", "肌", "髪"]
            )

            # 🌟 是否为皮肤、头发或布料材质
            is_skin_or_fabric = is_clothes or is_face_or_hair

            v0_mat = getattr(mtoon_ext, "vrm0_material", None)
            if v0_mat:
                if is_clothes and hasattr(v0_mat, "outline_width_mode"):
                    v0_mat.outline_width_mode = "none"
                for prop in v0_mat.vector_properties:
                    if prop.name == "_Color":
                        safe_set_vrm_prop(prop, "value", (1.0, 1.0, 1.0, 1.0))
                    if prop.name == "_ShadeColor":
                        safe_set_vrm_prop(prop, "value", (0.9, 0.9, 0.9, 1.0))
                    if prop.name == "_SphereAdd":
                        # 🌟 核心：如果是衣服、皮肤或头发，MatCap 反射颜色必须强制彻底设为黑色（0.0），屏蔽全局反光
                        if is_skin_or_fabric:
                            safe_set_vrm_prop(prop, "value", (0.0, 0.0, 0.0, 0.0))
                        else:
                            safe_set_vrm_prop(prop, "value", (0.3, 0.3, 0.3, 1.0))
                    if prop.name == "_EmissionColor" and not is_eye:
                        safe_set_vrm_prop(prop, "value", (0.0, 0.0, 0.0, 1.0))

                for prop in v0_mat.float_properties:
                    if prop.name == "_ShadingShift":
                        safe_set_vrm_prop(prop, "value", -0.15)
                    if prop.name == "_ShadingToony":
                        safe_set_vrm_prop(prop, "value", 0.98)

            v1_mtoon = getattr(mtoon_ext, "mtoon1", None)
            if v1_mtoon:
                if is_clothes and hasattr(v1_mtoon, "outline_width_mode"):
                    v1_mtoon.outline_width_mode = "none"
                if hasattr(v1_mtoon, "lit_color_factor"):
                    safe_set_vrm_prop(v1_mtoon, "lit_color_factor", (1.0, 1.0, 1.0))
                if hasattr(v1_mtoon, "shade_color"):
                    safe_set_vrm_prop(v1_mtoon, "shade_color", (0.9, 0.9, 0.9))
                if hasattr(v1_mtoon, "shading_shift_factor"):
                    safe_set_vrm_prop(v1_mtoon, "shading_shift_factor", -0.15)
                if hasattr(v1_mtoon, "shading_toony_factor"):
                    safe_set_vrm_prop(v1_mtoon, "shading_toony_factor", 0.98)
                if hasattr(v1_mtoon, "gi_equalization_factor"):
                    safe_set_vrm_prop(v1_mtoon, "gi_equalization_factor", 0.7)
                if hasattr(v1_mtoon, "matcap_color"):
                    # 🌟 核心：同理，如果是衣服、皮肤或头发，VRM 1.0 的 MatCap 颜色也彻底设为黑色
                    if is_skin_or_fabric:
                        safe_set_vrm_prop(v1_mtoon, "matcap_color", (0.0, 0.0, 0.0))
                    else:
                        safe_set_vrm_prop(v1_mtoon, "matcap_color", (0.3, 0.3, 0.3))
                if hasattr(v1_mtoon, "emissive_factor") and not is_eye:
                    safe_set_vrm_prop(v1_mtoon, "emissive_factor", (0.0, 0.0, 0.0))

    print("✅ [步骤 4] MToon 渲染参数配置完成！")
