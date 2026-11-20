import json
import os
import struct

import bpy
import numpy as np

COMP_SIZE = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
TYPE_COUNT = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


def ensure_vrm_neutral_preset(vrm_path):
    """在不改动任何二进制顶点/贴图/形态键缓冲区的前提下，确保 JSON 中显式包含 neutral 预设"""
    with open(vrm_path, "rb") as f:
        data = f.read()

    magic, version, total_len = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        return

    offset = 12
    json_bytes = None
    bin_bytes = b""
    while offset < len(data):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk_data = data[offset : offset + chunk_len]
        if chunk_type == 0x4E4F534A:
            json_bytes = chunk_data
        elif chunk_type == 0x004E4942:
            bin_bytes = chunk_data
        offset += chunk_len

    if not json_bytes:
        return

    gltf = json.loads(json_bytes.decode("utf-8"))
    vrm_ext = gltf.get("extensions", {}).get("VRMC_vrm")
    if not isinstance(vrm_ext, dict):
        return

    exprs = vrm_ext.setdefault("expressions", {})
    preset = exprs.setdefault("preset", {})
    if "neutral" in preset:
        return

    preset["neutral"] = {
        "isBinary": False,
        "overrideBlink": "none",
        "overrideLookAt": "none",
        "overrideMouth": "none",
    }

    new_json = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    while len(new_json) % 4 != 0:
        new_json += b" "

    new_total = 12 + 8 + len(new_json) + (8 + len(bin_bytes) if bin_bytes else 0)
    with open(vrm_path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, version, new_total))
        f.write(struct.pack("<II", len(new_json), 0x4E4F534A))
        f.write(new_json)
        if bin_bytes:
            f.write(struct.pack("<II", len(bin_bytes), 0x004E4942))
            f.write(bin_bytes)


def compact_vrm_morphs_sparse(vrm_path):
    """可选（仅限 three-vrm 等支持稀疏访问器的前端）：将稠密 Morph 转为 glTF 2.0 Sparse"""
    with open(vrm_path, "rb") as f:
        data = f.read()

    magic, version, total_len = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        return

    offset = 12
    json_bytes = None
    bin_bytes = b""
    while offset < len(data):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk_data = data[offset : offset + chunk_len]
        if chunk_type == 0x4E4F534A:
            json_bytes = chunk_data
        elif chunk_type == 0x004E4942:
            bin_bytes = chunk_data
        offset += chunk_len

    if not json_bytes or not bin_bytes:
        return

    gltf = json.loads(json_bytes.decode("utf-8"))
    bvs = gltf.get("bufferViews", [])
    accessors = gltf.get("accessors", [])

    morph_acc_indices = set()
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            for tgt in prim.get("targets", []):
                for acc_idx in tgt.values():
                    morph_acc_indices.add(acc_idx)

    if not morph_acc_indices:
        return

    new_sparse_chunks = []
    for acc_idx in sorted(morph_acc_indices):
        acc = accessors[acc_idx]
        if "sparse" in acc or "bufferView" not in acc:
            continue
        if acc.get("componentType") != 5126 or acc.get("type") != "VEC3":
            continue

        bv = bvs[acc["bufferView"]]
        count = acc["count"]
        stride = bv.get("byteStride") or 12
        start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)

        if stride == 12:
            raw = bin_bytes[start : start + count * 12]
            arr = np.frombuffer(raw, dtype="<f4").reshape((count, 3))
        else:
            arr = np.zeros((count, 3), dtype=np.float32)
            for i in range(count):
                s = start + i * stride
                arr[i] = np.frombuffer(bin_bytes[s : s + 12], dtype="<f4")

        nz_mask = np.any(np.abs(arr) > 1e-6, axis=1)
        nz_indices = np.nonzero(nz_mask)[0]

        if len(nz_indices) == 0:
            nz_indices = np.array([0], dtype=np.uint32)
            nz_values = np.zeros((1, 3), dtype="<f4")
        else:
            nz_values = arr[nz_indices].astype("<f4")

        if count <= 65535:
            idx_comp_type = 5123
            idx_bytes = nz_indices.astype("<u2").tobytes()
        else:
            idx_comp_type = 5125
            idx_bytes = nz_indices.astype("<u4").tobytes()
        val_bytes = nz_values.tobytes()

        if "min" not in acc:
            acc["min"] = [float(x) for x in np.min(arr, axis=0)]
        if "max" not in acc:
            acc["max"] = [float(x) for x in np.max(arr, axis=0)]
        del acc["bufferView"]
        acc.pop("byteOffset", None)

        new_sparse_chunks.append(
            (acc, len(nz_indices), idx_comp_type, idx_bytes, val_bytes)
        )

    if not new_sparse_chunks:
        return

    out_bin = bytearray()
    new_bvs = []

    def append_aligned(chunk_bytes):
        while len(out_bin) % 4 != 0:
            out_bin.append(0)
        off = len(out_bin)
        out_bin.extend(chunk_bytes)
        return off, len(chunk_bytes)

    for im in gltf.get("images", []):
        if "bufferView" not in im:
            continue
        old_bv = bvs[im["bufferView"]]
        old_off = old_bv.get("byteOffset", 0)
        old_len = old_bv["byteLength"]
        new_off, new_len = append_aligned(bin_bytes[old_off : old_off + old_len])
        im["bufferView"] = len(new_bvs)
        new_bvs.append({"buffer": 0, "byteOffset": new_off, "byteLength": new_len})

    for acc in accessors:
        if "sparse" not in acc:
            continue
        sp = acc["sparse"]
        for key in ("indices", "values"):
            if key in sp and "bufferView" in sp[key]:
                old_bv = bvs[sp[key]["bufferView"]]
                old_off = old_bv.get("byteOffset", 0)
                old_len = old_bv["byteLength"]
                new_off, new_len = append_aligned(
                    bin_bytes[old_off : old_off + old_len]
                )
                sp[key]["bufferView"] = len(new_bvs)
                new_bvs.append(
                    {"buffer": 0, "byteOffset": new_off, "byteLength": new_len}
                )

    bv_to_accs = {}
    for acc in accessors:
        if "bufferView" in acc:
            bv_to_accs.setdefault(acc["bufferView"], []).append(acc)

    for old_bv_idx, acc_list in bv_to_accs.items():
        old_bv = bvs[old_bv_idx]
        old_bv_off = old_bv.get("byteOffset", 0)
        stride = old_bv.get("byteStride")
        target = old_bv.get("target")

        is_interleaved = False
        if stride:
            for acc in acc_list:
                elem_sz = COMP_SIZE[acc["componentType"]] * TYPE_COUNT[acc["type"]]
                if stride > elem_sz:
                    is_interleaved = True
                    break

        if is_interleaved:
            min_off = min(acc.get("byteOffset", 0) for acc in acc_list)
            max_end = max(
                acc.get("byteOffset", 0)
                + (acc["count"] - 1) * stride
                + COMP_SIZE[acc["componentType"]] * TYPE_COUNT[acc["type"]]
                for acc in acc_list
            )
            new_off, new_len = append_aligned(
                bin_bytes[old_bv_off + min_off : old_bv_off + max_end]
            )
            new_bv_idx = len(new_bvs)
            bv_obj = {
                "buffer": 0,
                "byteOffset": new_off,
                "byteLength": new_len,
                "byteStride": stride,
            }
            if target is not None:
                bv_obj["target"] = target
            new_bvs.append(bv_obj)
            for acc in acc_list:
                acc["bufferView"] = new_bv_idx
                new_acc_off = acc.get("byteOffset", 0) - min_off
                if new_acc_off > 0:
                    acc["byteOffset"] = new_acc_off
                else:
                    acc.pop("byteOffset", None)
        else:
            for acc in acc_list:
                elem_sz = COMP_SIZE[acc["componentType"]] * TYPE_COUNT[acc["type"]]
                acc_len = acc["count"] * elem_sz
                acc_start = old_bv_off + acc.get("byteOffset", 0)
                new_off, new_len = append_aligned(
                    bin_bytes[acc_start : acc_start + acc_len]
                )
                new_bv_idx = len(new_bvs)
                bv_obj = {"buffer": 0, "byteOffset": new_off, "byteLength": new_len}
                if target is not None:
                    bv_obj["target"] = target
                new_bvs.append(bv_obj)
                acc["bufferView"] = new_bv_idx
                acc.pop("byteOffset", None)

    for acc, sp_count, idx_comp_type, idx_bytes, val_bytes in new_sparse_chunks:
        idx_off, idx_len = append_aligned(idx_bytes)
        idx_bv = len(new_bvs)
        new_bvs.append({"buffer": 0, "byteOffset": idx_off, "byteLength": idx_len})

        val_off, val_len = append_aligned(val_bytes)
        val_bv = len(new_bvs)
        new_bvs.append({"buffer": 0, "byteOffset": val_off, "byteLength": val_len})

        acc["sparse"] = {
            "count": sp_count,
            "indices": {"bufferView": idx_bv, "componentType": idx_comp_type},
            "values": {"bufferView": val_bv},
        }

    while len(out_bin) % 4 != 0:
        out_bin.append(0)

    gltf["bufferViews"] = new_bvs
    if gltf.get("buffers"):
        gltf["buffers"][0]["byteLength"] = len(out_bin)

    new_json = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    while len(new_json) % 4 != 0:
        new_json += b" "

    new_total = 12 + 8 + len(new_json) + 8 + len(out_bin)
    with open(vrm_path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, version, new_total))
        f.write(struct.pack("<II", len(new_json), 0x4E4F534A))
        f.write(new_json)
        f.write(struct.pack("<II", len(out_bin), 0x004E4942))
        f.write(out_bin)


def inspect_exported_vrm(vrm_path):
    with open(vrm_path, "rb") as f:
        data = f.read()
    magic, version, total_len = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        return
    offset = 12
    json_bytes = None
    while offset < len(data):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        if chunk_type == 0x4E4F534A:
            json_bytes = data[offset : offset + chunk_len]
            break
        offset += chunk_len

    if not json_bytes:
        return
    gltf = json.loads(json_bytes.decode("utf-8"))
    bvs = gltf.get("bufferViews", [])
    accessors = gltf.get("accessors", [])

    img_bytes = 0
    img_details = []
    for im in gltf.get("images", []):
        bv_idx = im.get("bufferView")
        sz = (
            bvs[bv_idx]["byteLength"] if bv_idx is not None and bv_idx < len(bvs) else 0
        )
        img_bytes += sz
        img_details.append((sz, im.get("name", "img"), im.get("mimeType", "")))

    morph_bv_indices = set()
    morph_count = 0
    joint_types = set()
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            j_acc = prim.get("attributes", {}).get("JOINTS_0")
            if j_acc is not None and j_acc < len(accessors):
                joint_types.add(accessors[j_acc].get("componentType"))
            targets = prim.get("targets", [])
            morph_count = max(morph_count, len(targets))
            for tgt in targets:
                for acc_idx in tgt.values():
                    acc = accessors[acc_idx]
                    if "bufferView" in acc:
                        morph_bv_indices.add(acc["bufferView"])
                    if "sparse" in acc:
                        sp = acc["sparse"]
                        if "indices" in sp and "bufferView" in sp["indices"]:
                            morph_bv_indices.add(sp["indices"]["bufferView"])
                        if "values" in sp and "bufferView" in sp["values"]:
                            morph_bv_indices.add(sp["values"]["bufferView"])

    skins_joints = [len(s.get("joints", [])) for s in gltf.get("skins", [])]
    j_type_str = ",".join(
        "u8(5121)" if t == 5121 else f"u16({t})" for t in sorted(joint_types)
    )
    morph_bytes = sum(bvs[i]["byteLength"] for i in morph_bv_indices if i < len(bvs))
    total_bv_bytes = sum(bv["byteLength"] for bv in bvs)
    geom_bytes = max(0, total_bv_bytes - img_bytes - morph_bytes)

    print(
        f"   📦 [VRM 体积解剖] 总={total_len / 1048576:.2f} MB | "
        f"基础几何/蒙皮={geom_bytes / 1048576:.2f} MB | "
        f"形态键({morph_count}个)={morph_bytes / 1048576:.2f} MB | "
        f"贴图({len(img_details)}张)={img_bytes / 1048576:.2f} MB | "
        f"蒙皮关节={skins_joints} ({j_type_str})"
    )

    vrm_ext = gltf.get("extensions", {}).get("VRMC_vrm", {})
    preset_exprs = vrm_ext.get("expressions", {}).get("preset", {})
    bound_summary = {
        k: len(v.get("morphTargetBinds", [])) for k, v in preset_exprs.items()
    }
    print(
        f"   😊 [VRM 导出表情验证] 全部已注册预设({len(bound_summary)}个): {bound_summary}"
    )
    anim_cnt = len(gltf.get("animations", []))
    sb_ext = gltf.get("extensions", {}).get("VRMC_springBone", {})
    sb_springs = sb_ext.get("springs", [])
    sb_joints = sum(len(s.get("joints", [])) for s in sb_springs)
    sample_j = next((s["joints"][0] for s in sb_springs if s.get("joints")), {})
    print(
        f"   🔍 [VRM 导出动作与弹簧骨验证] animations={anim_cnt} | "
        f"springs={len(sb_springs)}, joints={sb_joints}, "
        f"colliders={len(sb_ext.get('colliders', []))}, colliderGroups={len(sb_ext.get('colliderGroups', []))} | "
        f"示例={{stiffness={sample_j.get('stiffness')}, dragForce={sample_j.get('dragForce')}, "
        f"gravityPower={sample_j.get('gravityPower')}, gravityDir={sample_j.get('gravityDir')}, hitRadius={sample_j.get('hitRadius')}}}"
    )


def run(config):
    print(">>> [步骤 6] 写入 VRM 1.0 元数据并导出 VRM...")

    armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if not armature:
        return

    armature.data.vrm_addon_extension.spec_version = "1.0"
    meta = armature.data.vrm_addon_extension.vrm1.meta

    d = config.get("metadata", {})

    meta.vrm_name = d.get("vrm_name", config["en_name"])
    meta.version = d.get("version", "1.0.0")
    meta.copyright_information = d.get("copyright_information", "")
    meta.contact_information = d.get("contact_information", "")
    meta.third_party_licenses = d.get("third_party_licenses", "")
    meta.other_license_url = d.get("other_license_url", "")

    meta.authors.clear()
    meta.authors.add().value = d.get("author", "Unknown")

    meta.references.clear()
    ref_val = d.get("reference", "")
    if ref_val:
        meta.references.add().value = ref_val

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

    tp = d.get("thumbnail_path", "")
    if tp and os.path.exists(tp):
        img = bpy.data.images.get(os.path.basename(tp)) or bpy.data.images.load(tp)
        meta.thumbnail_image = img

    print("✅ [步骤 6] 元数据写入完成。")

    models_dir = config.get("models_dir") or bpy.path.abspath("//")
    os.makedirs(models_dir, exist_ok=True)
    out_vrm = os.path.join(models_dir, f"{config['en_name']}.vrm")
    has_vrma = bool(
        config.get("vrma_path")
        or (
            isinstance(config.get("vrma_paths"), list) and any(config.get("vrma_paths"))
        )
    )

    export_kwargs = {
        "filepath": out_vrm,
        "armature_object_name": armature.name,
    }
    if has_vrma:
        export_kwargs["enable_advanced_preferences"] = True
        export_kwargs["export_gltf_animations"] = True

    res = bpy.ops.export_scene.vrm(**export_kwargs)
    if res == {"FINISHED"} and os.path.exists(out_vrm):
        ensure_vrm_neutral_preset(out_vrm)
        if config.get("sparse_morphs", False):
            compact_vrm_morphs_sparse(out_vrm)
        size_mb = os.path.getsize(out_vrm) / (1024 * 1024)
        total_verts = sum(
            len(o.data.vertices)
            for o in bpy.data.objects
            if o.type == "MESH" and o.data
        )
        print(
            f"✅ [步骤 6] VRM 已导出至: {out_vrm} "
            f"(体积: {size_mb:.2f} MB | 骨骼: {len(armature.data.bones)} | 顶点: {total_verts} | 内嵌动画: {has_vrma})"
        )
        inspect_exported_vrm(out_vrm)
    else:
        print(f"⚠️ [步骤 6] VRM 导出失败: {res}")
