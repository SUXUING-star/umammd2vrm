# UmaViewer MMD to VRM 1.0 Converter(Experimental)

This Blender Python script converts MMD models exported from [UmaViewer](https://github.com/katboi01/UmaViewer) into the VRM 1.0 format. 

The script runs entirely inside Blender using Blender's built-in Python. You do not need to install a separate Python environment. It automates bone renaming, humanoid mapping, expression binding, texture processing, and MToon shader setup.

---

## Requirements

You need Blender with the following add-ons installed and enabled:

*   **mmd_tools:** To import and process the MMD model.
*   **VRM Add-on for Blender:** To map bones, set up expressions, and export the VRM 1.0 file.

### Folder Setup
Place the script files in a folder named `vrm_scripts` next to your `.blend` file:

```text
your_project_folder/
│
├── your_model_project.blend
│
└── vrm_scripts/          <-- Put the script files here
    ├── main.py
    ├── step0_clean.py
    ├── step1_skeleton.py
    ├── ...
    └── utils.py
```

---

## Configuration

Open `blender.py` and update the settings at the top to match your model and paths:

```python
ENGLISH_MODEL_NAME = "Mejiro Bright"
JP_NAME = "メジロブライト"
TEXTURE_DIR = r"E:\3dmodels\mejiro bright mizugi\Texture2D"
SCRIPTS_DIR = "vrm_scripts"
```

*   **ENGLISH_MODEL_NAME:** The new English name for your character.
*   **JP_NAME:** The Japanese name used in the original model files (the script will find and replace this).
*   **TEXTURE_DIR:** The path to the folder containing your exported textures.
*   **SCRIPTS_DIR:** The name of the folder where you placed the scripts.

---

## How to Use

### Prepare the Model
Import your `.pmx` model using **mmd_tools**. Select the model meshes, then use **mmd_tools** to convert the materials to Blender's standard **Principled BSDF** nodes.

### Run the Script
Open Blender's **Text Editor**, paste the code from `blender.py` into a new text block, and run it. The console will show the progress of each step.

### Export the VRM
Check the bone mappings and expressions in the **VRM Add-on** tab. Make sure the materials look correct, then export your model as a `.vrm` file.

---

## What the Scripts Do

Each script handles a specific part of the conversion:

*   **`step0_clean.py` (Mesh Cleanup):** Clears custom split normals to fix lighting bugs and sets the mesh shading to smooth.
*   **`step1_skeleton.py` (Bone Mapping):** Renames Japanese bone names to English and assigns them to the standard VRM humanoid slots.
*   **`step2_expressions.py` & `step3_bind_vrm.py` (Expressions):** Cleans up shape key names, links facial shapes to VRM expression presets, and deletes unused morphs to keep the file size small.
*   **`step4_eye_bake.py` (Textures):** Blends eye highlight textures and extracts shading control maps and emissive textures into a temporary folder.
*   **`step5_new_texture_nodes.py` (MToon Materials):** Replaces the standard materials with VRM MToon shaders and applies optimal lighting settings for skin, hair, and clothing.
