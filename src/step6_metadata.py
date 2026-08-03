import os

import bpy


def run(config):
    print(">>> [步骤 6] 写入 VRM 1.0 元数据...")

    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if not armature:
        return

    # 强制 1.0 规范
    armature.data.vrm_addon_extension.spec_version = "1.0"
    meta = armature.data.vrm_addon_extension.vrm1.meta

    # 从 JSON 的 metadata 块读取
    d = config["metadata"]

    # --- 基础字段 ---
    meta.vrm_name = d.get("vrm_name", config["en_name"])
    meta.version = d.get("version", "1.0.0")
    meta.copyright_information = d.get("copyright_information", "")
    meta.contact_information = d.get("contact_information", "")  # 补上了！
    meta.third_party_licenses = d.get("third_party_licenses", "")
    meta.other_license_url = d.get("other_license_url", "")

    # --- 作者 (Collection) ---
    meta.authors.clear()
    meta.authors.add().value = d.get("author", "Unknown")

    # --- 参考 (Collection) ---
    meta.references.clear()
    meta.references.add().value = d.get("reference", "")

    # --- 权限 (完全对应文档 Enum) ---
    meta.avatar_permission = d.get("avatar_permission", "everyone")
    meta.allow_excessively_violent_usage = d.get(
        "allow_excessively_violent_usage", False
    )
    meta.allow_excessively_sexual_usage = d.get("allow_excessively_sexual_usage", False)
    meta.commercial_usage = d.get("commercial_usage", "personalNonProfit")
    meta.allow_political_or_religious_usage = d.get(
        "allow_political_or_religious_usage", False
    )
    meta.allow_antisocial_or_hate_usage = d.get("allow_antisocial_or_hate_usage", False)
    meta.credit_notation = d.get("credit_notation", "required")
    meta.allow_redistribution = d.get("allow_redistribution", False)
    meta.modification = d.get("modification", "allowModification")

    # --- 缩略图 ---
    tp = d.get("thumbnail_path", "")
    if tp and os.path.exists(tp):
        img = bpy.data.images.get(os.path.basename(tp)) or bpy.data.images.load(tp)
        meta.thumbnail_image = img

    print("✅ [步骤 6] 元数据写入完成。")
