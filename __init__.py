# =============================================================================
#  Asset QA Validator - add-on de Blender
# =============================================================================
#
#  Revisa los objetos 3D de una escena contra una lista de reglas técnicas
#  (nombres, presupuesto de triángulos, transformaciones, UVs, materiales,
#  geometría y texturas) y muestra los problemas encontrados en un panel.
#  Los resultados se pueden exportar a CSV para adjuntarlos a un bug report.
#
#  Cómo leer este archivo (de arriba hacia abajo):
#
#    1. Imports ............ los módulos de Python y de Blender que usamos
#    2. Issue .............. la estructura de un problema encontrado
#    3. Checks ............. una función por regla; cada una devuelve problemas
#    4. CHECKS / run_checks  el registro de reglas y la función que las corre
#    5. Propiedades ........ los ajustes y resultados guardados en la escena
#    6. Operadores ......... las acciones (botones): correr, seleccionar, exportar
#    7. Interfaz (UI) ...... la lista de resultados y el panel en la barra lateral
#    8. register() ......... lo que Blender ejecuta al activar/desactivar el add-on
#
#  Convención: el código (nombres de variables y funciones) y los textos que
#  se ven en Blender están en inglés, como es habitual en la industria. Los
#  comentarios están en español para que puedas estudiarlo.
#
#  Hecho para Blender 5 (probado en 5.2.3 LTS) y compatible desde 4.2.
#
#  Es una "extensión" de Blender: el nombre, la versión y el autor ya no van
#  en un diccionario bl_info dentro del código (el sistema antiguo de
#  add-ons), sino en el archivo blender_manifest.toml de esta misma carpeta.
#  Por eso este archivo se llama __init__.py: Blender carga la carpeta como
#  un paquete de Python y ejecuta este archivo.
# =============================================================================

# -----------------------------------------------------------------------------
# 1. Imports
# -----------------------------------------------------------------------------
import csv
import os
import re
from dataclasses import dataclass

import bmesh  # API de Blender para leer y editar geometría (vértices, aristas, caras)
import bpy  # API principal de Blender: datos (bpy.data), contexto (bpy.context), etc.
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy_extras.io_utils import ExportHelper  # da el diálogo "Guardar como..."


# -----------------------------------------------------------------------------
# 2. Issue: un problema encontrado
# -----------------------------------------------------------------------------
# Niveles de severidad, igual que en un bug report:
#   ERROR   = el asset no debería pasar así a producción
#   WARNING = conviene revisarlo, pero puede ser intencional
SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"

# Tolerancia para comparar números decimales. Nunca compares floats con ==
# (por ejemplo, una escala puede valer 1.0000001 por redondeo).
TOLERANCE = 1e-4


@dataclass
class Issue:
    """Un problema encontrado por un check.

    Es una clase de Python "normal" (no de Blender). Los checks devuelven
    listas de Issue, y luego el operador las copia a la escena para
    mostrarlas en el panel. Separarlo así permite probar los checks sin
    interfaz (ver tests/test_asset_qa.py).
    """

    check: str  # id del check que lo encontró, p. ej. "naming"
    severity: str  # SEVERITY_ERROR o SEVERITY_WARNING
    object_name: str  # objeto afectado
    message: str  # descripción legible del problema


# -----------------------------------------------------------------------------
# 3. Checks: una función por regla
# -----------------------------------------------------------------------------
# Todas las funciones tienen la misma "firma":
#
#     check_algo(obj, settings) -> list[Issue]
#
#   obj      = el objeto de Blender que se revisa (siempre de tipo MESH)
#   settings = los ajustes del panel (prefijo, presupuesto de triángulos...)
#
# Que todas se parezcan es lo que permite correrlas en un bucle (ver CHECKS).
# Para añadir una regla nueva basta con escribir otra función igual y
# agregarla a CHECKS.


def check_naming(obj, settings):
    """Convención de nombres: prefijo obligatorio, sin espacios, sin '.001'."""
    issues = []
    name = obj.name
    prefix = settings.name_prefix

    if prefix and not name.startswith(prefix):
        issues.append(Issue(
            "naming", SEVERITY_ERROR, name,
            f"Name must start with prefix '{prefix}'",
        ))

    if " " in name:
        issues.append(Issue(
            "naming", SEVERITY_ERROR, name,
            "Name contains spaces",
        ))

    # Blender agrega ".001", ".002"... cuando duplicas un objeto. Suele ser
    # señal de un duplicado olvidado o de un nombre sin limpiar.
    # La expresión regular r"\.\d{3}$" significa: un punto, tres dígitos y fin
    # del texto.
    if re.search(r"\.\d{3}$", name):
        issues.append(Issue(
            "naming", SEVERITY_WARNING, name,
            "Name ends with a duplicate suffix like '.001'",
        ))

    return issues


def count_triangles(mesh):
    """Cuenta triángulos sin modificar la malla.

    Una cara de n vértices se divide en (n - 2) triángulos al exportarse al
    motor: un quad (4) da 2, un triángulo (3) da 1, un n-gon de 6 da 4.
    """
    return sum(len(polygon.vertices) - 2 for polygon in mesh.polygons)


def check_triangle_budget(obj, settings):
    """Presupuesto de polígonos: el objeto no supera el máximo de triángulos.

    Ojo: cuenta la malla base, sin aplicar modificadores (Subdivision,
    Mirror...). Si el asset usa modificadores, aplícalos antes o ten en
    cuenta que el número real en el motor será mayor.
    """
    triangles = count_triangles(obj.data)
    if triangles > settings.max_triangles:
        return [Issue(
            "triangles", SEVERITY_ERROR, obj.name,
            f"{triangles} triangles, budget is {settings.max_triangles}",
        )]
    return []


def check_transforms(obj, settings):
    """Transformaciones aplicadas: escala 1 y rotación 0.

    Un asset con escala o rotación sin aplicar se ve bien en Blender, pero
    en el motor puede llegar con tamaño equivocado, colisiones mal escaladas
    o normales invertidas. La solución en Blender es Ctrl+A > All Transforms.
    """
    issues = []

    # matrix_basis es la transformación local del objeto. decompose() la
    # separa en posición, rotación (cuaternión) y escala. Así funciona sin
    # importar el modo de rotación del objeto (Euler XYZ, cuaternión, etc.).
    _location, rotation, scale = obj.matrix_basis.decompose()

    if any(abs(axis - 1.0) > TOLERANCE for axis in scale):
        issues.append(Issue(
            "transforms", SEVERITY_WARNING, obj.name,
            "Scale is not applied ({:.3f}, {:.3f}, {:.3f})".format(*scale),
        ))

    # rotation.angle es el ángulo total de giro en radianes; 0 = sin rotación.
    if rotation.angle > TOLERANCE:
        issues.append(Issue(
            "transforms", SEVERITY_WARNING, obj.name,
            "Rotation is not applied",
        ))

    return issues


def check_uvs(obj, settings):
    """El objeto tiene al menos un mapa UV (sin UVs no se puede texturizar)."""
    if len(obj.data.uv_layers) == 0:
        return [Issue("uvs", SEVERITY_ERROR, obj.name, "Mesh has no UV map")]
    return []


def check_materials(obj, settings):
    """Tiene material asignado y ningún slot de material vacío."""
    slots = obj.material_slots
    if len(slots) == 0:
        return [Issue(
            "materials", SEVERITY_ERROR, obj.name,
            "Object has no material",
        )]

    empty_slots = [index for index, slot in enumerate(slots) if slot.material is None]
    if empty_slots:
        return [Issue(
            "materials", SEVERITY_WARNING, obj.name,
            f"{len(empty_slots)} empty material slot(s)",
        )]
    return []


def check_ngons(obj, settings):
    """Caras de más de 4 lados (n-gons).

    Los motores triangulan los n-gons de forma automática y a veces el
    resultado se ve mal (sombreado raro, deformación en animación).
    """
    ngon_count = sum(1 for polygon in obj.data.polygons if polygon.loop_total > 4)
    if ngon_count:
        return [Issue(
            "ngons", SEVERITY_WARNING, obj.name,
            f"{ngon_count} n-gon face(s) with more than 4 sides",
        )]
    return []


def check_geometry(obj, settings):
    """Geometría suelta y aristas no manifold.

    Aquí usamos bmesh porque permite preguntar por las conexiones: qué
    aristas tiene un vértice (link_edges) y qué caras tiene una arista
    (link_faces). La malla "normal" (obj.data) no trae esa información.
    """
    issues = []

    bm = bmesh.new()  # una malla bmesh vacía, independiente de la escena
    try:
        bm.from_mesh(obj.data)  # copia la geometría del objeto a bmesh

        # Vértice suelto: no está unido a ninguna arista.
        loose_verts = sum(1 for vert in bm.verts if not vert.link_edges)
        # Arista suelta: no forma parte de ninguna cara.
        loose_edges = sum(1 for edge in bm.edges if not edge.link_faces)
        # Arista compartida por más de 2 caras: geometría imposible en el
        # mundo real ("no manifold"); rompe normales, bakes y físicas.
        bad_edges = sum(1 for edge in bm.edges if len(edge.link_faces) > 2)
    finally:
        # bmesh no se libera solo: si no llamas free() se queda en memoria.
        # "finally" garantiza que se libere aunque ocurra un error arriba.
        bm.free()

    if loose_verts or loose_edges:
        issues.append(Issue(
            "geometry", SEVERITY_WARNING, obj.name,
            f"Loose geometry: {loose_verts} vertex(es), {loose_edges} edge(s)",
        ))
    if bad_edges:
        issues.append(Issue(
            "geometry", SEVERITY_ERROR, obj.name,
            f"{bad_edges} non-manifold edge(s) shared by more than 2 faces",
        ))
    return issues


def check_textures(obj, settings):
    """Texturas de los materiales: que existan en disco y no estén vacías."""
    issues = []
    for slot in obj.material_slots:
        material = slot.material
        # En Blender 5 todos los materiales usan nodos (la opción "use_nodes"
        # está obsoleta y se eliminará en Blender 6), así que basta con
        # revisar que el material tenga su árbol de nodos.
        if material is None or material.node_tree is None:
            continue

        for node in material.node_tree.nodes:
            if node.type != 'TEX_IMAGE':
                continue

            image = node.image
            if image is None:
                issues.append(Issue(
                    "textures", SEVERITY_WARNING, obj.name,
                    f"Material '{material.name}' has an image node with no image",
                ))
                continue

            # Solo revisamos imágenes que vienen de un archivo y que no están
            # empaquetadas dentro del .blend (las empaquetadas no necesitan disco).
            if image.source == 'FILE' and image.packed_file is None:
                # bpy.path.abspath convierte rutas relativas de Blender
                # (que empiezan con "//") a rutas completas del sistema.
                path = bpy.path.abspath(image.filepath)
                if not os.path.exists(path):
                    issues.append(Issue(
                        "textures", SEVERITY_ERROR, obj.name,
                        f"Missing texture file: {image.filepath}",
                    ))
    return issues


# -----------------------------------------------------------------------------
# 4. Registro de checks y función que los corre
# -----------------------------------------------------------------------------
# Cada entrada: (id, nombre del interruptor en los ajustes, función).
# El "nombre del interruptor" es una propiedad BoolProperty de AssetQASettings
# (ver más abajo) que permite activar o desactivar el check desde el panel.
CHECKS = [
    ("naming", "use_naming", check_naming),
    ("triangles", "use_triangles", check_triangle_budget),
    ("transforms", "use_transforms", check_transforms),
    ("uvs", "use_uvs", check_uvs),
    ("materials", "use_materials", check_materials),
    ("ngons", "use_ngons", check_ngons),
    ("geometry", "use_geometry", check_geometry),
    ("textures", "use_textures", check_textures),
]


def run_checks(objects, settings):
    """Corre los checks activados sobre los objetos de tipo malla.

    No depende de la interfaz: recibe objetos y ajustes y devuelve una lista
    de Issue. Por eso se puede llamar desde el operador, desde la consola de
    Python de Blender o desde un test automático.
    """
    issues = []
    for obj in objects:
        if obj.type != 'MESH':
            continue  # cámaras, luces, empties... no se revisan

        # Si el objeto está en Edit Mode, sus últimos cambios todavía no
        # están en obj.data. Esto los "sincroniza" antes de revisar.
        if obj.mode == 'EDIT':
            obj.update_from_editmode()

        for _check_id, toggle_name, check_function in CHECKS:
            # getattr(settings, "use_naming") equivale a settings.use_naming
            if getattr(settings, toggle_name):
                issues.extend(check_function(obj, settings))
    return issues


# -----------------------------------------------------------------------------
# 5. Propiedades: ajustes y resultados guardados en la escena
# -----------------------------------------------------------------------------
# Un PropertyGroup es un "contenedor" de propiedades de Blender. A diferencia
# de las variables normales de Python, estas se guardan dentro del archivo
# .blend y se pueden mostrar en la interfaz.


class AssetQASettings(bpy.types.PropertyGroup):
    """Ajustes del validador (se ven en la sección Settings del panel)."""

    only_selected: BoolProperty(
        name="Only Selected",
        description="Check only the selected objects instead of the whole scene",
        default=True,
    )
    name_prefix: StringProperty(
        name="Name Prefix",
        description="Required prefix for object names (empty = no prefix rule)",
        default="SM_",
    )
    max_triangles: IntProperty(
        name="Max Triangles",
        description="Triangle budget per object",
        default=10000,
        min=1,
    )

    # Un interruptor por check. Sus nombres coinciden con la lista CHECKS.
    use_naming: BoolProperty(name="Naming", default=True)
    use_triangles: BoolProperty(name="Triangle Budget", default=True)
    use_transforms: BoolProperty(name="Applied Transforms", default=True)
    use_uvs: BoolProperty(name="UV Map", default=True)
    use_materials: BoolProperty(name="Materials", default=True)
    use_ngons: BoolProperty(name="N-gons", default=True)
    use_geometry: BoolProperty(name="Loose / Non-manifold", default=True)
    use_textures: BoolProperty(name="Missing Textures", default=True)


class AssetQAIssue(bpy.types.PropertyGroup):
    """Un resultado guardado en la escena.

    Es la versión "de Blender" de la clase Issue: la necesitamos porque la
    interfaz (UIList) solo sabe mostrar propiedades de Blender, no objetos
    normales de Python.
    """

    check: StringProperty()
    severity: EnumProperty(
        items=[
            (SEVERITY_ERROR, "Error", "Must be fixed"),
            (SEVERITY_WARNING, "Warning", "Should be reviewed"),
        ],
    )
    object_name: StringProperty()
    message: StringProperty()


# -----------------------------------------------------------------------------
# 6. Operadores: las acciones que ejecutan los botones
# -----------------------------------------------------------------------------
# Un operador es una clase con:
#   bl_idname -> el identificador: "asset_qa.run_checks" se puede llamar
#                desde Python como bpy.ops.asset_qa.run_checks()
#   bl_label  -> el texto del botón
#   execute() -> lo que hace; devuelve {'FINISHED'} o {'CANCELLED'}
# Los nombres de clase siguen la convención de Blender: PREFIJO_OT_nombre
# (OT = Operator Type).


class ASSETQA_OT_run_checks(bpy.types.Operator):
    """Run the enabled checks and list the issues found"""

    bl_idname = "asset_qa.run_checks"
    bl_label = "Run Checks"
    # UNDO: el resultado se puede deshacer con Ctrl+Z.
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        settings = scene.asset_qa_settings

        if settings.only_selected:
            objects = list(context.selected_objects)
        else:
            objects = list(scene.objects)

        meshes = [obj for obj in objects if obj.type == 'MESH']
        if not meshes:
            # self.report muestra un mensaje en la barra de estado de Blender.
            self.report({'WARNING'}, "No mesh objects to check")
            return {'CANCELLED'}

        issues = run_checks(meshes, settings)

        # Copiamos los Issue a la colección de la escena para el panel.
        scene.asset_qa_issues.clear()
        for issue in issues:
            item = scene.asset_qa_issues.add()
            item.check = issue.check
            item.severity = issue.severity
            item.object_name = issue.object_name
            item.message = issue.message
        scene.asset_qa_index = 0

        errors = sum(1 for issue in issues if issue.severity == SEVERITY_ERROR)
        warnings = len(issues) - errors
        scene.asset_qa_summary = (
            f"{len(meshes)} object(s) checked: {errors} error(s), {warnings} warning(s)"
        )
        self.report({'INFO'}, scene.asset_qa_summary)
        return {'FINISHED'}


class ASSETQA_OT_select_issue_object(bpy.types.Operator):
    """Select the object of the highlighted issue in the viewport"""

    bl_idname = "asset_qa.select_issue_object"
    bl_label = "Select Object"
    bl_options = {'REGISTER', 'UNDO'}

    # poll() decide si el botón está activo. Si devuelve False, el botón se
    # ve gris y no se puede pulsar. Aquí: solo si hay resultados.
    @classmethod
    def poll(cls, context):
        return len(context.scene.asset_qa_issues) > 0

    def execute(self, context):
        scene = context.scene
        index = scene.asset_qa_index
        if not 0 <= index < len(scene.asset_qa_issues):
            return {'CANCELLED'}

        name = scene.asset_qa_issues[index].object_name
        obj = scene.objects.get(name)  # get() devuelve None si no existe
        if obj is None:
            self.report({'WARNING'}, f"Object '{name}' no longer exists")
            return {'CANCELLED'}

        # Seleccionar solo ese objeto y hacerlo el objeto activo.
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class ASSETQA_OT_export_report(bpy.types.Operator, ExportHelper):
    """Export the issues to a CSV file (for a bug report or a spreadsheet)"""

    bl_idname = "asset_qa.export_report"
    bl_label = "Export CSV"

    # ExportHelper usa esto para el diálogo "Guardar como" y para el filtro.
    filename_ext = ".csv"
    filter_glob: StringProperty(default="*.csv", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return len(context.scene.asset_qa_issues) > 0

    def execute(self, context):
        # self.filepath lo llena ExportHelper con la ruta que elige el usuario.
        blend_file = bpy.path.basename(bpy.data.filepath) or "(unsaved file)"
        try:
            # newline="" evita líneas en blanco extra en Windows;
            # utf-8-sig hace que Excel abra bien las tildes.
            with open(self.filepath, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(["blend_file", "object", "check", "severity", "message"])
                for item in context.scene.asset_qa_issues:
                    writer.writerow([
                        blend_file, item.object_name, item.check,
                        item.severity, item.message,
                    ])
        except OSError as error:
            self.report({'ERROR'}, f"Could not write file: {error}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Report saved to {self.filepath}")
        return {'FINISHED'}


class ASSETQA_OT_clear_results(bpy.types.Operator):
    """Clear the list of issues"""

    bl_idname = "asset_qa.clear_results"
    bl_label = "Clear"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.asset_qa_issues.clear()
        context.scene.asset_qa_summary = ""
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# 7. Interfaz: lista de resultados y panel
# -----------------------------------------------------------------------------

# Icono que se muestra según la severidad (iconos internos de Blender).
SEVERITY_ICONS = {
    SEVERITY_ERROR: 'CANCEL',
    SEVERITY_WARNING: 'ERROR',  # en Blender, el icono 'ERROR' es un triángulo de alerta
}


class ASSETQA_UL_issues(bpy.types.UIList):
    """Dibuja cada fila de la lista de resultados (UL = UI List)."""

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_propname, index):
        # "item" es un AssetQAIssue. Cada fila: icono + objeto + mensaje.
        layout.label(
            text=f"{item.object_name}: {item.message}",
            icon=SEVERITY_ICONS.get(item.severity, 'INFO'),
        )


class ASSETQA_PT_main(bpy.types.Panel):
    """Panel en la barra lateral del Viewport 3D (tecla N), pestaña 'Asset QA'.

    PT = Panel Type. bl_space_type y bl_region_type dicen DÓNDE aparece;
    bl_category es el nombre de la pestaña.
    """

    bl_label = "Asset QA Validator"
    bl_idname = "ASSETQA_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Asset QA"

    def draw(self, context):
        # draw() se llama cada vez que Blender redibuja el panel. Solo debe
        # DIBUJAR; nunca modificar datos aquí.
        layout = self.layout
        scene = context.scene
        settings = scene.asset_qa_settings

        # --- Ajustes ---
        box = layout.box()
        box.label(text="Settings", icon='PREFERENCES')
        box.prop(settings, "only_selected")
        box.prop(settings, "name_prefix")
        box.prop(settings, "max_triangles")

        # --- Checks activados ---
        box = layout.box()
        box.label(text="Checks", icon='CHECKBOX_HLT')
        column = box.column(align=True)
        for _check_id, toggle_name, _function in CHECKS:
            column.prop(settings, toggle_name)

        # --- Botón principal ---
        row = layout.row()
        row.scale_y = 1.5  # botón más alto para que destaque
        row.operator(ASSETQA_OT_run_checks.bl_idname, icon='VIEWZOOM')

        # --- Resultados ---
        if scene.asset_qa_summary:
            layout.label(text=scene.asset_qa_summary, icon='INFO')

        if len(scene.asset_qa_issues) > 0:
            # template_list(clase_UIList, id, datos, colección, datos, índice_activo)
            layout.template_list(
                "ASSETQA_UL_issues", "",
                scene, "asset_qa_issues",
                scene, "asset_qa_index",
                rows=6,
            )
            row = layout.row(align=True)
            row.operator(ASSETQA_OT_select_issue_object.bl_idname, icon='RESTRICT_SELECT_OFF')
            row.operator(ASSETQA_OT_export_report.bl_idname, icon='EXPORT')
            row.operator(ASSETQA_OT_clear_results.bl_idname, icon='X')
        elif scene.asset_qa_summary:
            layout.label(text="No issues found", icon='CHECKMARK')


# -----------------------------------------------------------------------------
# 8. Registro: lo que pasa al activar y desactivar el add-on
# -----------------------------------------------------------------------------
# El orden importa: los PropertyGroup se registran antes que las clases que
# los usan.
CLASSES = (
    AssetQASettings,
    AssetQAIssue,
    ASSETQA_OT_run_checks,
    ASSETQA_OT_select_issue_object,
    ASSETQA_OT_export_report,
    ASSETQA_OT_clear_results,
    ASSETQA_UL_issues,
    ASSETQA_PT_main,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    # Agregamos propiedades nuevas a TODAS las escenas (bpy.types.Scene).
    # Desde aquí se accede como context.scene.asset_qa_settings, etc.
    bpy.types.Scene.asset_qa_settings = PointerProperty(type=AssetQASettings)
    bpy.types.Scene.asset_qa_issues = CollectionProperty(type=AssetQAIssue)
    bpy.types.Scene.asset_qa_index = IntProperty(default=0)
    bpy.types.Scene.asset_qa_summary = StringProperty(default="")


def unregister():
    # Al desactivar, se deshace todo en orden inverso.
    del bpy.types.Scene.asset_qa_summary
    del bpy.types.Scene.asset_qa_index
    del bpy.types.Scene.asset_qa_issues
    del bpy.types.Scene.asset_qa_settings

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


# Permite probarlo pegando el archivo en el Text Editor de Blender y
# pulsando "Run Script", sin instalarlo como add-on.
if __name__ == "__main__":
    register()
