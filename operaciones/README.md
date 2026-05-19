# Módulo Operaciones

## ✅ Creado sin romper el sistema existente

El módulo **Operaciones** ha sido creado como una extensión completamente independiente del sistema actual. No modifica ni toca ningún código existente de:

- ✅ Garantías
- ✅ Panel Cotizaciones
- ✅ Cotizaciones existentes
- ✅ Dashboard
- ✅ Incidencias
- ✅ Usuarios
- ✅ Sidebar actual
- ✅ Autenticación
- ✅ CSS global
- ✅ JS global

---

## 📁 Estructura del Módulo

```
operaciones/
├── __init__.py
├── admin.py                 # Admin de Django
├── apps.py                  # Configuración de la app
├── forms.py                 # Formularios Django
├── models.py                # Modelos (Operacion, OperacionEtiqueta, etc)
├── urls.py                  # URLs de la app
├── views.py                 # Vistas (panel, crear, editar, etc)
├── migrations/
│   ├── __init__.py
│   └── 0001_initial.py      # Migración inicial (ya aplicada)
├── templatetags/
│   ├── __init__.py
│   └── operaciones_extras.py # Filtros personalizados
└── templates/operaciones/
    ├── panel_operaciones.html          # Kanban principal
    ├── crear_operacion.html            # Formulario crear
    ├── _operacion_card.html            # Tarjeta Kanban
    └── _detalle_modal_content.html     # Modal de detalles
```

---

## 🎯 Características

### Panel Kanban
- **9 columnas** con estados específicos:
  1. Pendientes
  2. Seguros
  3. Prueba de valor
  4. En aduana
  5. Tránsito nacional
  6. Por coordinar pickup
  7. Tránsito internacional
  8. Expediente CG
  9. Solicitud de cuenta gastos

### Tarjetas
Cada tarjeta muestra:
- Título
- Cliente
- Etiquetas (chips coloreados)
- Contador de comentarios
- Prioridad
- Vencimiento
- Asignados (avatares)
- Botón "Ver"

### Funcionalidades
- **Drag & Drop**: Mover tarjetas entre columnas (SortableJS)
- **Filtros**: Por usuarios asignados
- **Modal de detalles**: Ver/editar operación
- **Comentarios**: Sistema de comentarios como Garantías
- **Archivos**: Subir múltiples archivos
- **Enlaces**: Agregar URLs
- **Etiquetas**: 10 etiquetas predefinidas
- **Asignados**: Usuarios con ManyToMany

---

## 🏗️ Modelos

### Operacion
```python
- titulo (CharField)
- descripcion (TextField)
- cliente (ForeignKey → Cliente)
- prioridad (BAJA, MEDIA, ALTA)
- estado (PENDIENTE, SEGUROS, PRUEBA_VALOR, ...)
- asignados (ManyToMany → User)
- creado_por (ForeignKey → User)
- fecha_vencimiento (DateField)
- fecha_creacion (DateTimeField)
- etiquetas (ManyToMany → OperacionEtiqueta)
```

### OperacionEtiqueta
```python
- nombre (CharField, unique)
- color (CharField: primary, success, warning, danger, info, secondary, dark, light)
- fecha_creacion (DateTimeField)
```

### OperacionComentario
```python
- operacion (ForeignKey)
- usuario (ForeignKey → User)
- comentario (TextField)
- fecha (DateTimeField)
```

### OperacionArchivo
```python
- operacion (ForeignKey)
- archivo (FileField)
- subido_por (ForeignKey → User)
- fecha (DateTimeField)
```

### OperacionEnlace
```python
- operacion (ForeignKey)
- titulo (CharField)
- url (URLField)
- creado_por (ForeignKey → User)
- fecha (DateTimeField)
```

---

## 🔌 Integración en el Sistema

### 1. Settings
Agregado a `INSTALLED_APPS`:
```python
INSTALLED_APPS = [
    ...
    "operaciones",
]
```

### 2. URLs
Agregado en `solicitudes_app/urls.py`:
```python
path("operaciones/", include("operaciones.urls")),
```

### 3. Sidebar
Agregado en `templates/base.html`:
```html
<a href="{% url 'operaciones:panel_operaciones' %}"
   class="sidebar-link">Operaciones</a>
```

---

## 🚀 Uso

### Acceso
- URL: `/operaciones/`
- Sidebar: Botón "Operaciones"
- Permisos: Usuarios autenticados

### Panel Principal
- Visualizar Kanban con 9 columnas
- Filtrar por usuarios asignados
- Crear nueva operación (+)
- Mover tarjetas entre columnas (drag & drop)
- Hacer clic en "Ver" para detalles

### Crear Operación
- URL: `/operaciones/crear/`
- Campos: titulo, descripción, cliente, prioridad, vencimiento, asignados, etiquetas
- Al guardar aparece en "Pendientes"

### Modal de Detalles
- Editar información
- Agregar comentarios
- Subir archivos
- Agregar enlaces
- Ver asignados
- Eliminar operación

---

## 🎨 Estilos

El módulo reutiliza:
- **Variables CSS** existentes: `--color-card`, `--color-border`, `--shadow-md`, etc.
- **Bootstrap 5.3.2**: Clases existentes del sistema
- **Colores del sistema**: Tema light/dark sincronizado

---

## 📊 Etiquetas Predefinidas

Creadas automáticamente:
1. Seguro de Contenedor (blue)
2. Seguro de carga (cyan)
3. Monitoreo Activo (green)
4. Mercancía asegurada (yellow)
5. FCL (gray)
6. LCL (gray)
7. BL Original (blue)
8. Pendiente Telex (red)
9. No aplica seguro (light)
10. Telex OK (green)

---

## 🔐 Seguridad

- ✅ Autenticación requerida para todas las vistas
- ✅ CSRF tokens en formularios
- ✅ Validación de datos en Django
- ✅ Sin acceso directo a otros módulos

---

## 📱 Responsive

El diseño se adapta a:
- Desktop (9 columnas)
- Tablet (reducido)
- Mobile (1 columna)

---

## 🛠️ Mantenimiento

### Agregar nueva etiqueta
```python
from operaciones.models import OperacionEtiqueta
OperacionEtiqueta.objects.create(nombre="Nueva", color="primary")
```

### Admin de Django
Acceder a: `/admin/operaciones/`
- Gestionar operaciones
- Gestionar etiquetas
- Ver comentarios, archivos, enlaces

---

## ⚡ Rendimiento

- Prefetch_related para comentarios, archivos, enlaces
- Select_related para cliente y creado_por
- Indices en campos frecuentes
- Paginación en listas (si se implementa)

---

## 🔄 Compatibilidad Railway

✅ Compatible con Railway (sin cambios en settings)
✅ Usa SQLite (compatible con db.sqlite3)
✅ Sin dependencias externas adicionales
✅ Storage de archivos en `/uploads/`

---

## 📝 Notas

- El módulo es completamente independiente
- Puede ser desactivado sin afectar otros módulos
- Las migraciones se aplicaron correctamente
- No modifica tablas existentes
- Compatible con tema light/dark

---

Creado: 2026-05-16
Versión: 1.0
Estado: ✅ Funcional
