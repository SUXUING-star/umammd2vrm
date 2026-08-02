# Uma MMD to VRM 1.0 Pipeline (Experimental)

An experimental Blender Python pipeline designed to convert MMD models exported from [UmaViewer](https://github.com/katboi01/UmaViewer) into web-standard VRM 1.0 format. Running entirely within Blender's built-in Python environment, this pipeline automates bone renaming, humanoid mapping, facial expression binding, texture processing, and MToon shader configuration without requiring an external Python installation.

---

## Prerequisites

Before executing the pipeline, ensure the following tools are ready in Blender:

*   **Blender:** Compatible with versions containing modern Python APIs (such as Blender 5.x).
*   **mmd_tools Add-on:** Needed to import `.pmx` models and perform the initial material setup.
*   **VRM Add-on for Blender:** Required for humanoid bone configurations, expressions, and exporting to VRM 1.0 format.

### Recommended Folder Layout
To keep your workspace organized, place the repository files in a subfolder adjacent to your `.blend` file:

```text
your_project_folder/
│
├── your_model_project.blend
│
└── vrm_scripts/          <-- Put the pipeline scripts here
    ├── main.py
    ├── step0_clean.py
    ├── step1_skeleton.py
    ├── ...
    └── utils.py
```

---

## Setup and Configuration

Open `blender.py` and modify the configuration variables at the top of the file to match your directory paths and character details:

```python
ENGLISH_MODEL_NAME = "Mejiro Bright"
JP_NAME = "メジロブライト"
TEXTURE_DIR = r"E:\3dmodels\mejiro bright mizugi\Texture2D"
SCRIPTS_DIR = "vrm_scripts"
```

*   **ENGLISH_MODEL_NAME:** The target English name applied to renamed meshes, armatures, and objects.
*   **JP_NAME:** The Japanese name keyword used in the imported assets, which the script targets for replacement.
*   **TEXTURE_DIR:** The file path to the folder containing raw textures exported from UmaViewer.
*   **SCRIPTS_DIR:** The folder name where the pipeline scripts are stored relative to the `.blend` file.

---

## Workflow

### Import and Initial Material Setup
First, import your `.pmx` model into Blender using the **mmd_tools** panel. Select the model's mesh objects and use the **mmd_tools** interface to convert the materials to Blender's standard **Principled BSDF** shader nodes. This step is necessary to allow the script to properly read the material properties.

### Running the Script
Open Blender's **Text Editor** workspace, create a new text block, and paste the contents of `blender.py` into it. Ensure your configurations are correct, then run the script. The system console will display the status of each pipeline step as it processes.

### Verification and Export
Once the script completes, use the **VRM Add-on** panel to inspect the generated humanoid bone mappings and expressions. Confirm that the materials successfully converted to VRM-compliant **MToon** shaders, then export the project as a `.vrm` file using the VRM Add-on's export function.

---

## Pipeline Breakdown

The conversion process runs through the following modular scripts:

*   **Mesh and Normal Cleanup (`step0_clean.py`):** Clears custom split normals to resolve potential shading issues and applies smooth shading across all meshes.
*   **Rig Renaming and Humanoid Mapping (`step1_skeleton.py`):** Renames bones from MMD conventions to English and maps them to standard VRM Humanoid slots.
*   **Shape Key Processing and Expression Binding (`step2_expressions.py` & `step3_bind_vrm.py`):** Strips numeric prefixes from shape keys, maps face and ear keys to VRM 1.0 expressions, and purges unused keyframes and redundant shape keys to reduce file size.
*   **Eye and Texture Channel Processing (`step4_eye_bake.py`):** Blends eye highlight layers and extracts control maps (such as Shading Grade from the Red channel and Emissive data from the Blue channel) into a temporary directory.
*   **MToon Shader Construction (`step5_new_texture_nodes.py`):** Converts materials into VRM-compliant MToon shaders with custom-tailored parameters for skin, clothes, and hair to prevent visual issues in web players.
