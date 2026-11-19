# UmaViewer Waves MMD to VRM 1.0 Converter

A Blender Python pipeline for converting MMD models exported from into VRM 1.0 avatars.

The repository is target to UmaViewer MMD Models Structure.It's for personal, educational, and non-commercial purposes
---

---

## Requirements

1. **Blender** (4 ~ 5.2)
2. **Required Add-ons:**
   * **[mmd_tools](https://github.com/powup333/blender_mmd_tools)**
   * **[VRM Add-on for Blender](https://vrm-addon-for-blender.info/en/)**

---

## Model Configuration (`config.json`)

Each character directory in `public/` requires a `config.json` next to the `.blend` file.

```json
{
    "jp_name": "メジロブライト",
    "en_name": "Mejiro Bright",
    "texture_dir": "Texture2D",
    "vrma_path": ["./motion.vrma"],
    "scripts_dir": "src",
    "metadata": {
        "vrm_name": "Mejiro Bright",
        "version": "1.0.0",
        "author": "suxing-star",
        "copyright": "",
        "contact": "",
        "reference": "",
        "third_party_licenses": "None",
        "other_license_url": "",
        "thumbnail_path": "",
        "avatar_permission": "everyone",
        "allow_excessively_violent_usage": false,
        "allow_excessively_sexual_usage": false,
        "commercial_usage": "personalNonProfit",
        "allow_political_or_religious_usage": false,
        "allow_antisocial_or_hate_usage": false,
        "credit_notation": "required",
        "allow_redistribution": false,
        "modification": "prohibited"
  }
}
```

---

## Usage

1. **Import PMX:** Import the `.pmx` model into Blender using `mmd_tools` and convert materials to Principled BSDF. Save the `.blend` file.
2. **Verify Setup:** Ensure `config.json` and `Texture2D/`(or other name) are in the same folder as the `.blend` file.
3. **Run Pipeline:** Open `blender.py` in Text Editor and edit the code path(the repsitory clone path),then you just copy the `blender.py` into the Blender's Text Editor,and click **Run Script** (`Alt + P`).
4. **Export VRM:** Check mappings in the VRM tab on the Blender sidebar (`N`), then click **Export VRM 1.0**.

---

## Pipeline Overview

* **`step0_clean.py`**: Clears split normals on body/clothes, preserves custom smooth face normals, and removes vertex color artifacts around the mouth.
* **`step1_skeleton.py`**: Strips unused MMD dummy bones and maps bones to VRM Humanoid definitions.
* **`step2_expressions.py`**: Removes numeric prefixes from shape key names.
* **`step3_bind_vrm.py`**: Maps shape keys to VRM expression presets (`aa`, `blink`, `happy`, etc.) and deletes unused morphs/NLA tracks.
* **`step4_bake_texture.py`**: Bakes stacked eye highlights and packs texture channels into `vrm_temp_baked/`.
* **`step5_mtoon_materials.py`**: Converts materials to MToon shaders and adjusts face shading offsets and GI strength.
* **`step6_metadata.py`**: Writes license, author, and permission fields into the VRM 1.0 metadata.
* **`step_vrma.py`**: (Optional) Add VRMA motion into model.
