[English](README.md) | **Español**

# Asset QA Validator · add-on de Blender

Un add-on que revisa tus assets 3D contra reglas técnicas **antes** de exportarlos al motor, como haría un Art QA: nombres, presupuesto de triángulos, transformaciones, UVs, materiales, geometría y texturas. Los problemas aparecen en un panel de Blender y se pueden exportar a CSV para adjuntarlos a un bug report.

Es una **extensión de Blender 5** (el sistema de add-ons que existe desde Blender 4.2).

| Archivo | Qué es |
|---|---|
| `__init__.py` | El código del add-on: un solo archivo con comentarios en español que explican cada parte. |
| `blender_manifest.toml` | La ficha de la extensión: nombre, versión, autor, versión mínima de Blender y permisos. Reemplaza al antiguo `bl_info`. |
| `tests/test_asset_qa.py` | Tests automáticos. No van dentro del paquete que se instala. |
| `dist/asset_qa_validator-1.0.0.zip` | El paquete listo para instalar. |

**Probado en:** Blender 5.2.3 LTS, con 12 de 12 tests pasando. Funciona desde Blender 4.2. En Blender 3.6 o anteriores no se puede instalar como extensión.

---

## 1. Instalación en Blender 5

### Opción A: instalar el .zip (uso normal)
1. Abre **Edit → Preferences → Get Extensions**.
2. Arriba a la derecha, abre el menú **⌄** y elige **Install from Disk…**.
3. Elige `dist/asset_qa_validator-1.0.0.zip`.
4. Queda activado. Lo verás en **Add-ons** como **Asset QA Validator**.

También puedes **arrastrar el .zip** a la ventana de Blender.

**Para quitarlo:** en **Edit → Preferences → Add-ons**, busca **Asset QA Validator**, abre su menú y elige **Uninstall**.

### Opción B: probarlo sin instalar (útil mientras estudias el código)
1. Abre el **Text Editor** de Blender.
2. **Open** → `__init__.py`.
3. Pulsa **Run Script** (▶).

Cada vez que cambies el código, vuelve a pulsar Run Script para cargar la versión nueva. Si Blender dice que una clase ya está registrada, reinicia Blender. Si además tienes la extensión instalada, desactívala antes para que no choquen.

### Volver a empaquetar después de cambiar el código
Si modificas el add-on, sube `version` en `blender_manifest.toml` (por ejemplo a `1.0.1`) y genera un .zip nuevo. Desde la carpeta raíz del repositorio (cambia la ruta de `blender.exe` por la de tu instalación):

```bash
"G:\SteamLibrary\steamapps\common\Blender\blender.exe" --command extension build --source-dir . --output-dir dist
```

Para revisar solo que el manifiesto esté bien escrito, sin crear el .zip:

```bash
"G:\SteamLibrary\steamapps\common\Blender\blender.exe" --command extension validate .
```

---

## 2. Cómo usarlo

1. En el **Viewport 3D**, pulsa **N** para abrir la barra lateral.
2. Abre la pestaña **Asset QA**.
3. Ajusta las reglas en **Settings**:
   - **Only Selected:** revisa solo los objetos seleccionados. Si lo desmarcas, revisa toda la escena.
   - **Name Prefix:** el prefijo obligatorio, por ejemplo `SM_` para static mesh. Déjalo vacío para no exigir prefijo.
   - **Max Triangles:** el presupuesto de triángulos por objeto.
4. En **Checks**, marca las reglas que quieres aplicar.
5. Pulsa **Run Checks**.
6. Revisa la lista de resultados:
   - ❌ **Error:** no debería pasar así a producción.
   - ⚠️ **Warning:** conviene revisarlo, pero puede ser intencional.
7. Con un resultado resaltado:
   - **Select Object:** selecciona el objeto afectado en el viewport.
   - **Export CSV:** guarda todos los resultados en un archivo que puedes abrir en Excel o Google Sheets.
   - **Clear:** limpia la lista.

---

## 3. Qué revisa cada check (y por qué importa en QA)

| Check | Severidad | Qué detecta | Por qué importa |
|---|---|---|---|
| **Naming** | Error / Warning | Falta el prefijo, hay espacios, o el nombre termina en `.001` | Los pipelines y los motores buscan assets por nombre. Un nombre mal puesto rompe la importación o crea duplicados. |
| **Triangle Budget** | Error | Más triángulos que el presupuesto | El rendimiento: cada plataforma tiene un límite por asset. |
| **Applied Transforms** | Warning | Escala ≠ 1 o rotación ≠ 0 | En el motor el asset llega con tamaño o colisiones incorrectas. Se arregla con Ctrl+A → All Transforms. |
| **UV Map** | Error | La malla no tiene UVs | Sin UVs no se puede texturizar ni hacer bake. |
| **Materials** | Error / Warning | No hay material o hay slots vacíos | El asset se ve rosa o gris en el motor. |
| **N-gons** | Warning | Caras de más de 4 lados | La triangulación automática puede dar sombreado raro o deformar mal al animar. |
| **Loose / Non-manifold** | Warning / Error | Vértices o aristas sueltas; aristas compartidas por 3 o más caras | La geometría basura infla el asset; lo no manifold rompe normales, bakes y físicas. |
| **Missing Textures** | Error / Warning | Archivos de textura que no existen, o nodos de imagen vacíos | El asset llega sin texturas al motor. |

**Limitación conocida:** el conteo de triángulos usa la malla **sin modificadores**. Si el objeto tiene Subdivision o Mirror, el número real en el motor será mayor. Mejorar esto es uno de los ejercicios del final.

---

## 4. Cómo está organizado el código

El archivo se lee de arriba hacia abajo en 8 secciones numeradas. El flujo cuando pulsas **Run Checks** es:

```
Botón "Run Checks" (panel)
        │
        ▼
ASSETQA_OT_run_checks.execute()        ← el operador
        │  1. elige los objetos (seleccionados o toda la escena)
        │  2. llama a run_checks(objetos, ajustes)
        ▼
run_checks()                           ← recorre objetos × checks activados
        │
        ├─► check_naming(obj, settings)          → [Issue, ...]
        ├─► check_triangle_budget(obj, settings) → [Issue, ...]
        └─► ... (un check por regla, todos con la misma forma)
        │
        ▼
lista de Issue (clases normales de Python)
        │  3. el operador las copia a scene.asset_qa_issues
        ▼
ASSETQA_PT_main.draw()                 ← el panel dibuja la lista (UIList)
```

**La idea clave de diseño:** los checks **no saben nada de la interfaz**. Reciben un objeto y devuelven problemas. Por eso se pueden probar con tests automáticos sin abrir Blender, y por eso agregar una regla nueva es fácil.

---

## 5. Conceptos de la API de Blender (bpy) que aparecen

| Concepto | Qué es | Dónde aparece |
|---|---|---|
| `bpy.data` | Todos los datos del archivo .blend: objetos, mallas, materiales, imágenes | Tests: `bpy.data.materials.new(...)` |
| `bpy.context` | "Lo que está pasando ahora": escena activa, selección, modo | Operadores: `context.selected_objects` |
| `bpy.ops` | Operadores: las mismas acciones que haces con botones y atajos | Tests: `bpy.ops.mesh.primitive_cube_add()` |
| **Objeto vs. malla** | `obj` tiene la transformación (posición, rotación, escala). `obj.data` es la malla (vértices, caras, UVs). Varios objetos pueden compartir la misma malla. | `check_transforms` usa `obj`; `check_uvs` usa `obj.data` |
| `bmesh` | API para leer y editar geometría con sus conexiones (qué caras tiene una arista, etc.). Hay que liberarla con `bm.free()`. | `check_geometry` |
| `PropertyGroup` | Contenedor de propiedades que se **guarda en el .blend** y se puede mostrar en la UI | `AssetQASettings`, `AssetQAIssue` |
| `Operator` | Una acción con `bl_idname`, `execute()` y opcionalmente `poll()` | Las 4 clases `ASSETQA_OT_*` |
| `poll()` | Decide si el botón está activo (gris o no) | `select_issue_object`, `export_report` |
| `Panel` | Un bloque de interfaz. `draw()` solo dibuja; nunca modifica datos. | `ASSETQA_PT_main` |
| `UIList` | Una lista con filas seleccionables | `ASSETQA_UL_issues` |
| `register()` / `unregister()` | Lo que corre al activar o desactivar el add-on | Final del archivo |
| `blender_manifest.toml` | La ficha de una extensión (Blender 4.2+). Declara también los **permisos**: este add-on pide `files` porque escribe el CSV. | Archivo aparte |
| `material.node_tree` | El árbol de nodos del material. En Blender 5 todos los materiales usan nodos, y la opción `use_nodes` está obsoleta (se eliminará en Blender 6). | `check_textures` |

**Convención de nombres de clases:** `PREFIJO_TIPO_nombre`, donde el tipo es `OT` (operador), `PT` (panel) o `UL` (lista). Blender exige este formato.

---

## 6. Cómo agregar tu propio check (paso a paso)

Ejemplo: exigir que el **origen** del objeto esté en la base del modelo, algo común en props que se colocan sobre el suelo.

**Paso 1.** Escribe la función en la sección 3, con la misma forma que las demás:

```python
def check_origin_at_base(obj, settings):
    """El origen debe estar a la altura del punto más bajo de la malla."""
    if len(obj.data.vertices) == 0:
        return []
    # Las coordenadas de los vértices son locales: el origen es (0, 0, 0).
    lowest_z = min(vertex.co.z for vertex in obj.data.vertices)
    if abs(lowest_z) > TOLERANCE:
        return [Issue(
            "origin", SEVERITY_WARNING, obj.name,
            f"Origin is not at the base (lowest point at z={lowest_z:.3f})",
        )]
    return []
```

**Paso 2.** Agrega un interruptor en `AssetQASettings`:

```python
    use_origin: BoolProperty(name="Origin at Base", default=False)
```

**Paso 3.** Regístralo en la lista `CHECKS`:

```python
    ("origin", "use_origin", check_origin_at_base),
```

Con eso aparece solo en el panel y en **Run Checks**. No hace falta tocar la interfaz.

**Paso 4.** Agrega un test en `tests/test_asset_qa.py`: un cubo con el origen en el centro debería dar el warning.

---

## 7. Correr los tests

Desde una terminal, en la carpeta raíz del repositorio:

```bash
"G:\SteamLibrary\steamapps\common\Blender\blender.exe" --background --factory-startup --python tests/test_asset_qa.py
```

- `--background`: Blender sin ventana.
- `--factory-startup`: ignora tus preferencias, para un entorno limpio.

Los tests importan el código directamente de la carpeta, así que no necesitas tener la extensión instalada para correrlos.

Cada test crea objetos con un problema **plantado a propósito** y comprueba que el check lo detecta, igual que un caso de prueba con resultado esperado. También hay un test con un asset correcto que no debe dar ningún problema; eso evita los falsos positivos. Si todo pasa, al final verás `ALL TESTS PASSED (12 tests)`.

> Con `--command extension build` o `validate` (que no usan `--factory-startup`), Blender carga tus otras extensiones instaladas, y puede que veas errores de algunas (por ejemplo `GPUShader` o "gpu module to be initialized"). Son add-ons que esperan una ventana abierta. No tienen que ver con este proyecto, y el .zip se genera igual.

---

## 8. Ejercicios para estudiarlo (de fácil a difícil)

1. **Cambia un mensaje.** Traduce al español el mensaje de prefijo de `check_naming` (`"Name must start with prefix..."`), corre los tests y mira cuál falla y por qué. Pista: `test_naming` busca la palabra `"prefix"`.
2. **Nuevo prefijo.** Permite varios prefijos válidos separados por comas (`SM_,SK_`). Pista: `prefix.split(",")`.
3. **Check de origen.** Implementa el ejemplo de la sección 6, con su test.
4. **Contar con modificadores.** Cuenta los triángulos de la malla evaluada. Pista: `obj.evaluated_get(context.evaluated_depsgraph_get())` y luego `to_mesh()`. Libérala con `to_mesh_clear()`.
5. **LODs.** Si existe `SM_Rock_LOD0`, exige que exista `SM_Rock_LOD1` con menos triángulos.
6. **Densidad de texel.** Calcula el área en UV contra el área en 3D de cada cara y avisa si un objeto se sale del rango. Es un check que pocos testers saben hacer y encaja con tu perfil de Art QA.
7. **Reporte en Markdown.** Agrega un botón que exporte el reporte con formato de bug report: título, pasos, resultado esperado y resultado actual.

---

## Autor

David Morales · Game QA Tester con 7 años de experiencia como artista 3D en juegos, AR y VR.
[LinkedIn](https://www.linkedin.com/in/3dmcasanova/) · [Portafolio de QA](https://github.com/3dmcasanova/QA-Engineer-DMC) · david.morales.dmqa@gmail.com
