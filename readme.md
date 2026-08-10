# UmaViewer MMD to VRM 1.0 Converter

An automated Blender Python pipeline that converts MMD models exported from [UmaViewer](https://github.com/katboi01/UmaViewer) into fully configured, production-ready **VRM 1.0** avatars.

Running entirely inside Blender's built-in Python environment, the toolkit handles bone renaming, humanoid rigging, shape key cleanup, expression mapping, multi-channel texture/highlight baking, MToon material conversion (with anti-side lighting patches), and metadata embedding.

---

## Workspace Directory Structure

Each model project lives inside its own folder under `public/`, complete with its own `.blend` file, texture directory, and character-specific `config.json`. The pipeline scripts reside in the central `src/` folder.

```text
vrm_scripts/
├── blender.py                       # Runner script loaded in Blender Text Editor
├── readme.md
├── src/                             # Core execution scripts
│   ├── main.py                      # Pipeline orchestrator & path resolver
│   ├── step0_clean.py               # Face normal protection & mesh cleanup
│   ├── step1_skeleton.py            # Bone renaming & Humanoid auto-mapping
│   ├── step2_expressions.py         # Shape key prefix cleaning
│   ├── step3_bind_vrm.py            # VRM expression mapping & morph purging
│   ├── step4_eye_bake.py            # Non-destructive eye highlight & channel baking
│   ├── step5_new_texture_nodes.py   # MToon shader construction & lighting tuning
│   └── step6_metadata.py            # VRM 1.0 metadata writer
│
└── public/                          # Model project workspace
    ├── Agnes digital/
    │   ├── Agnes Digital.blend
    │   ├── config.json              # Model-specific config
    │   └── Texture2D/
    │
    ├── mejiro bright mizugi/
    │   ├── Mejiro Bright mizugi.blend
    │   ├── config.json              # Model-specific config
    │   └── Texture2D/
    │
    └── <Your Model Folder>/
        ├── <Your Model>.blend
        ├── config.json
        └── Texture2D/
```

---

## Requirements

1. **Blender** (3.6+ or 4.x recommended).
2. **Add-ons required and enabled:**
   * **[mmd_tools](https://github.com/powup333/blender_mmd_tools):** For importing and processing `.pmx` models.
   * **[VRM Add-on for Blender](https://vrm-addon-for-blender.info/en/):** For VRM humanoid mapping, MToon shaders, and exporting `.vrm`.

---

## Per-Model Configuration (`config.json`)

Each character directory inside `public/` requires its own `config.json` placed alongside the `.blend` file.

### Example `config.json`

```json
{
    "jp_name": "メジロブライト",
    "en_name": "Mejiro Bright",
    "texture_dir": "Texture2D",
    "scripts_dir": "src",
    "metadata": {
        "vrm_name": "Mejiro Bright lolita",
        "version": "1.0.0",
        "author": "suxing-star",
        "copyright": "",
        "contact": "",
        "reference": "https://hub.vroid.com/en/users/128137342",
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

### Key Config Fields

* **`jp_name`**: The original Japanese character name used in PMX meshes/bones (e.g., `メジロブライト`).
* **`en_name`**: English replacement name used for objects, meshes, and armatures.
* **`texture_dir`**: Relative path to the raw exported texture folder (usually `"Texture2D"`).
* **`metadata`**: VRM 1.0 license, permission settings, author details, and thumbnail relative path.

---

## Workflow / How to Run

1. **Import PMX into Blender:**
   * Open Blender and import your model `.pmx` using `mmd_tools`.
   * Convert materials to standard Principled BSDF via `mmd_tools`.
   * Save the file as a `.blend` file inside its respective directory under `public/` (e.g., `public/mejiro bright mizugi/Mejiro Bright mizugi.blend`).

2. **Verify Folder Setup:**
   * Ensure `config.json` and `Texture2D/` exist in the same directory as your `.blend` file.

3. **Run the Script in Blender:**
   * Switch to Blender's **Text Editor** tab.
   * Open `blender.py` (or paste its entry snippet).
   * Click **Run Script** (`Alt + P`).

4. **Export VRM:**
   * Open the **VRM** tab in the Blender sidebar (`N`).
   * Verify the humanoid bone mappings, expressions, and metadata.
   * Click **Export VRM 1.0**.

---

## Pipeline Execution Details

The process is divided into modular steps managed by `src/main.py`:

* **`step0_clean.py` (Mesh & Normal Protection):**
  Clears custom split normals on body/clothing while protecting original smooth sphere face normals. Removes leftover vertex color masks that cause dark artifacts around mouth corners.

* **`step1_skeleton.py` (Bone & Rig Standardisation):**
  Removes dummy/MMD garbage bones (`mmd_shadow`, `Pole`, `IK_parent`). Renames Japanese bones to VRM standard names and maps them to VRM 0.x / 1.0 Humanoid bone definitions.

* **`step2_expressions.py` (Shape Key Cleaning):**
  Strips numeric prefixes (e.g., `001.CloseA` -> `CloseA`) from mesh shape keys.

* **`step3_bind_vrm.py` (Expression Mapping & Unused Morph Purge):**
  Binds facial shape keys and ear morphs to standard VRM 0.x and 1.0 expression presets (`aa`, `ih`, `ou`, `ee`, `oh`, `blink`, `happy`, `angry`, `sad`, `relaxed`, `surprised`). Deletes redundant shape keys and unused NLA tracks to reduce file size.

* **`step4_eye_bake.py` (Multi-Channel Texture Processing):**
  Composites eye base textures with up to 3 stacked eye highlight textures (`eyehi00`, `eyehi01`, `eyehi02`). Resolves shading grade maps, extracts emissive channels, and outputs processed textures to `vrm_temp_baked/`.

* **`step5_new_texture_nodes.py` (MToon Shader Setup):**
  Converts materials to VRM MToon shaders. Configures base color, shade multiply textures, emissive maps, and matcaps. Applies facial shading shift (`-0.25`) and GI equalization (`1.0`) to prevent harsh black rim shadows on VRoid Hub/WebGL renderers.

* **`step6_metadata.py` (VRM 1.0 Metadata Injection):**
  Injects author info, license rights, usage permissions, and thumbnail images from `config.json` into the VRM 1.0 data structure.
