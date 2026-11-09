**English** | [Español](README.es.md)

# Asset QA Validator · Blender extension

A Blender add-on that checks 3D assets against technical specs **before** they are exported to the game engine, the way an Art QA tester would. Issues show up in a panel inside Blender and can be exported to CSV to attach to a bug report.

Built by a Game QA tester with 7 years of experience as a 3D artist, to automate the asset checks that usually happen by eye.

- **Blender:** 4.2 or newer. Tested on Blender 5.2.3 LTS.
- **Tests:** 12 automated tests, run headless in Blender. All pass.

## What it checks

| Check | Severity | Finds | Why it matters |
|---|---|---|---|
| **Naming** | Error / Warning | Missing prefix (e.g. `SM_`), spaces, duplicate suffixes like `.001` | Pipelines and engines find assets by name |
| **Triangle Budget** | Error | More triangles than the per-object budget | Performance on the target platform |
| **Applied Transforms** | Warning | Scale ≠ 1 or rotation ≠ 0 | Wrong size or collisions in the engine |
| **UV Map** | Error | Mesh with no UVs | Can't be textured or baked |
| **Materials** | Error / Warning | No material, or empty material slots | Pink or grey asset in the engine |
| **N-gons** | Warning | Faces with more than 4 sides | Bad shading or deformation after triangulation |
| **Loose / Non-manifold** | Warning / Error | Loose vertices and edges; edges shared by 3+ faces | Bloated assets; broken normals, bakes and physics |
| **Missing Textures** | Error / Warning | Texture files that don't exist; empty image nodes | Asset arrives untextured |

## Install

1. Download [`dist/asset_qa_validator-1.0.0.zip`](dist/asset_qa_validator-1.0.0.zip).
2. In Blender: **Edit → Preferences → Get Extensions → ⌄ → Install from Disk…** and pick the .zip. You can also drag the .zip into the Blender window.

## Use

1. In the 3D Viewport, press **N** and open the **Asset QA** tab.
2. Set the name prefix and triangle budget, and choose which checks to run.
3. Click **Run Checks**.
4. Pick an issue and use **Select Object** to find it in the viewport, or **Export CSV** to save the report.

## Run the tests

From the repository root:

```bash
blender --background --factory-startup --python tests/test_asset_qa.py
```

Each test builds an asset with a known, planted defect and checks that the validator reports it. A clean asset must report nothing, which guards against false positives.

## Project structure

```
__init__.py              the add-on (checks, operators, panel)
blender_manifest.toml    extension metadata and permissions
tests/test_asset_qa.py   automated tests
dist/                    packaged extension (.zip) ready to install
README.es.md             full study guide in Spanish
```

The checks don't depend on the UI: each one takes an object and returns a list of issues. That's what makes them testable headless and easy to extend. Code comments are in Spanish; [README.es.md](README.es.md) walks through the code, the Blender Python API concepts it uses, and how to add a new check.

## Author

David Morales · Game QA Tester, 3D artist background (games, AR, VR).
[LinkedIn](https://www.linkedin.com/in/3dmcasanova/) · [QA portfolio](https://github.com/3dmcasanova/QA-Engineer-DMC) · david.morales.dmqa@gmail.com

## License

GPL-3.0-or-later, as required for Blender extensions.
