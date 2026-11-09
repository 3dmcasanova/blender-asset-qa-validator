# =============================================================================
#  Tests automáticos del Asset QA Validator
# =============================================================================
#
#  Crea una escena con objetos que tienen errores conocidos ("bugs plantados")
#  y comprueba que cada check los detecta, y que un objeto correcto pasa sin
#  problemas. Es la misma idea que un caso de prueba: entrada conocida ->
#  resultado esperado.
#
#  Cómo correrlo (desde una terminal, en la carpeta raíz del repositorio,
#  sin abrir la interfaz de Blender):
#
#     "G:\SteamLibrary\steamapps\common\Blender\blender.exe" --background --factory-startup --python tests/test_asset_qa.py
#
#  --background       Blender sin ventana
#  --factory-startup  ignora tus preferencias y add-ons, para un entorno limpio
#  --python           ejecuta este script
#
#  Si todo pasa, al final imprime "ALL TESTS PASSED". Si algo falla, imprime
#  qué test falló y Blender termina con código de salida 1.
# =============================================================================

import csv
import importlib.util
import os
import sys
import tempfile
import traceback

import bpy

# El código del add-on está en __init__.py, en la carpeta de arriba de tests/.
# Lo cargamos por su ruta (y no con "import nombre_de_carpeta") para que los
# tests funcionen sin importar cómo se llame la carpeta donde clonaste el repo.
ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "asset_qa_validator", os.path.join(ADDON_DIR, "__init__.py"),
)
qa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qa)


# -----------------------------------------------------------------------------
# Funciones de ayuda para crear objetos de prueba
# -----------------------------------------------------------------------------

def new_scene():
    """Escena vacía: borra el cubo, la cámara y la luz por defecto."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def good_material():
    material = bpy.data.materials.get("M_Good") or bpy.data.materials.new("M_Good")
    return material


def add_cube(name, with_material=True):
    """Cubo con UVs (primitive_cube_add crea UVs por defecto) y material."""
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    obj = bpy.context.active_object
    obj.name = name
    if with_material:
        obj.data.materials.append(good_material())
    return obj


def add_mesh_from_data(name, vertices, faces, edges=()):
    """Malla a partir de una lista de vértices y caras (útil para casos raros)."""
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, list(edges), faces)
    mesh.update()
    mesh.uv_layers.new(name="UVMap")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.data.materials.append(good_material())
    return obj


def checks_found(obj, settings):
    """Devuelve el conjunto de ids de check que encontraron algo en obj."""
    return {issue.check for issue in qa.run_checks([obj], settings)}


# -----------------------------------------------------------------------------
# Tests: cada función prueba una regla
# -----------------------------------------------------------------------------

def test_clean_asset_has_no_issues(settings):
    obj = add_cube("SM_Clean")
    found = checks_found(obj, settings)
    assert found == set(), f"Expected no issues, got {found}"


def test_naming(settings):
    obj = add_cube("Bad Name")
    issues = [i for i in qa.run_checks([obj], settings) if i.check == "naming"]
    messages = " | ".join(i.message for i in issues)
    assert "prefix" in messages, messages
    assert "spaces" in messages, messages

    duplicate = add_cube("SM_Crate")
    duplicate.name = "SM_Crate.001"
    issues = [i for i in qa.run_checks([duplicate], settings) if i.check == "naming"]
    assert any("duplicate suffix" in i.message for i in issues), issues


def test_triangle_budget(settings):
    # En Blender, subdivisions=1 es el icosaedro base (20 triángulos) y cada
    # nivel multiplica por 4: 2 -> 80, 3 -> 320, 4 -> 1280, 5 -> 5120.
    # 5120 supera el presupuesto de 2000 que usan los tests.
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5)
    obj = bpy.context.active_object
    obj.name = "SM_Heavy"
    bpy.ops.mesh.uv_texture_add()
    obj.data.materials.append(good_material())

    assert qa.count_triangles(obj.data) == 5120, qa.count_triangles(obj.data)
    assert "triangles" in checks_found(obj, settings)


def test_transforms(settings):
    scaled = add_cube("SM_Scaled")
    scaled.scale = (2.0, 2.0, 2.0)
    assert "transforms" in checks_found(scaled, settings)

    rotated = add_cube("SM_Rotated")
    rotated.rotation_euler = (0.0, 0.0, 0.5)
    assert "transforms" in checks_found(rotated, settings)


def test_uvs(settings):
    obj = add_cube("SM_NoUV")
    while obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers[0])
    assert "uvs" in checks_found(obj, settings)


def test_materials(settings):
    no_material = add_cube("SM_NoMaterial", with_material=False)
    assert "materials" in checks_found(no_material, settings)

    empty_slot = add_cube("SM_EmptySlot")
    empty_slot.data.materials.append(None)  # un slot sin material
    issues = [i for i in qa.run_checks([empty_slot], settings) if i.check == "materials"]
    assert issues and "empty material slot" in issues[0].message, issues


def test_ngons(settings):
    # Un hexágono: una sola cara de 6 vértices.
    hexagon = [(1, 0, 0), (0.5, 0.87, 0), (-0.5, 0.87, 0),
               (-1, 0, 0), (-0.5, -0.87, 0), (0.5, -0.87, 0)]
    obj = add_mesh_from_data("SM_Ngon", hexagon, [(0, 1, 2, 3, 4, 5)])
    assert "ngons" in checks_found(obj, settings)
    assert qa.count_triangles(obj.data) == 4  # 6 lados -> 4 triángulos


def test_loose_geometry(settings):
    # Un quad + un vértice suelto (índice 4) que no está en ninguna cara.
    vertices = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (5, 5, 5)]
    obj = add_mesh_from_data("SM_Loose", vertices, [(0, 1, 2, 3)])
    issues = [i for i in qa.run_checks([obj], settings) if i.check == "geometry"]
    assert any("Loose geometry: 1 vertex" in i.message for i in issues), issues


def test_non_manifold(settings):
    # Tres caras que comparten la misma arista (vértices 0-1): no manifold.
    vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1)]
    faces = [(0, 1, 2), (0, 1, 3), (0, 1, 4)]
    obj = add_mesh_from_data("SM_NonManifold", vertices, faces)
    issues = [i for i in qa.run_checks([obj], settings) if i.check == "geometry"]
    assert any("non-manifold" in i.message for i in issues), issues


def test_missing_texture(settings):
    obj = add_cube("SM_MissingTex", with_material=False)
    # En Blender 5 los materiales nuevos ya traen árbol de nodos; no hace
    # falta (y está obsoleto) activar material.use_nodes.
    material = bpy.data.materials.new("M_MissingTex")
    assert material.node_tree is not None, "Material has no node tree"
    node = material.node_tree.nodes.new("ShaderNodeTexImage")
    image = bpy.data.images.new("T_Missing", 4, 4)
    image.source = 'FILE'
    image.filepath = os.path.join(tempfile.gettempdir(), "does_not_exist_T_Missing.png")
    node.image = image
    obj.data.materials.append(material)

    issues = [i for i in qa.run_checks([obj], settings) if i.check == "textures"]
    assert any("Missing texture file" in i.message for i in issues), issues


def test_disabled_check_is_skipped(settings):
    obj = add_cube("No Prefix")
    settings.use_naming = False
    try:
        assert "naming" not in checks_found(obj, settings)
    finally:
        settings.use_naming = True


def test_operators_and_csv_export(settings):
    """Prueba el flujo completo como lo haría un usuario: correr y exportar."""
    add_cube("Bad Name")
    settings.only_selected = False  # revisar toda la escena

    result = bpy.ops.asset_qa.run_checks()
    assert result == {'FINISHED'}, result
    scene = bpy.context.scene
    assert len(scene.asset_qa_issues) > 0
    assert "error(s)" in scene.asset_qa_summary, scene.asset_qa_summary

    csv_path = os.path.join(tempfile.gettempdir(), "asset_qa_test_report.csv")
    result = bpy.ops.asset_qa.export_report(filepath=csv_path)
    assert result == {'FINISHED'}, result
    with open(csv_path, encoding="utf-8-sig") as file:
        rows = list(csv.reader(file))
    assert rows[0] == ["blend_file", "object", "check", "severity", "message"], rows[0]
    assert len(rows) - 1 == len(scene.asset_qa_issues)
    os.remove(csv_path)

    bpy.ops.asset_qa.clear_results()
    assert len(scene.asset_qa_issues) == 0


# -----------------------------------------------------------------------------
# Ejecutor de tests
# -----------------------------------------------------------------------------

TESTS = [
    test_clean_asset_has_no_issues,
    test_naming,
    test_triangle_budget,
    test_transforms,
    test_uvs,
    test_materials,
    test_ngons,
    test_loose_geometry,
    test_non_manifold,
    test_missing_texture,
    test_disabled_check_is_skipped,
    test_operators_and_csv_export,
]


def main():
    qa.register()
    failures = 0
    try:
        for test in TESTS:
            new_scene()  # cada test empieza con una escena limpia
            settings = bpy.context.scene.asset_qa_settings
            settings.name_prefix = "SM_"
            settings.max_triangles = 2000
            try:
                test(settings)
                print(f"PASS  {test.__name__}")
            except Exception:
                failures += 1
                print(f"FAIL  {test.__name__}")
                traceback.print_exc()
    finally:
        qa.unregister()

    print()
    if failures:
        print(f"{failures} TEST(S) FAILED")
        sys.exit(1)
    print(f"ALL TESTS PASSED ({len(TESTS)} tests)")


main()
