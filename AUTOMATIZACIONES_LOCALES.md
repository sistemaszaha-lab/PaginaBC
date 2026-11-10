# Automatizaciones locales de ZAHA OPS

Entrega del 10 de noviembre de 2026. Sin commit, push ni despliegue. No se accedió a producción.

## Resultado

- Operaciones `FACTURA_FLETES_1` → Cuenta de Gastos `FACTURA_FLETES_1`.
- Cuenta de Gastos `VOBO_ANGIE` → Cuenta de Gastos `SOLICITUDES_GEO_1`.
- Los servicios resuelven exclusivamente por código. Renombrar las cuatro columnas involucradas no cambia los flujos.
- Se conserva `VOBO_ANGIE`, asignado históricamente por la migración 0006 y confirmado en la base local; no se reasigna ningún código del cliente.
- Se mantienen las relaciones OneToOne `operacion_flete_origen` y `vobo_angie_origen`, las transacciones y la copia actual de campos, responsables, etiquetas y opciones. Las originales permanecen en su tablero y las copias no se sincronizan posteriormente.
- Se comprueban creación, movimiento, copiar/pegar, entradas desde otros servicios, admin y reasignación por eliminación de columnas. La copia se ejecuta después de guardar las relaciones M2M.
- Se protegen los códigos reservados en Django admin; el panel no admite editar códigos. Los nombres siguen siendo editables. En admin, el estado de la tarjeta se deriva de la columna seleccionada.
- Se conserva la restricción existente de alta inline de Operaciones únicamente desde la primera columna activa. No se añaden señales: código futuro que guarde directamente por ORM debe invocar el servicio después de guardar las relaciones, dentro de la misma transacción.

## Migraciones y datos

Secuencia revisada: `cuenta_gastos.0012_cuentagastos_operacion_flete_origen` → `0013_cuentagastos_vobo_angie_origen` → **nueva** `0014_columnas_automatizaciones`. La nueva migración depende también de `operaciones.0014_operacioncolumna_usuarios_visibles_and_more`.

0012 y 0013 ya estaban implementadas localmente; se conservaron sin cambios. 0014 valida todo el catálogo antes de escribir, reutiliza las filas por código y añade solo las columnas ausentes al final del orden. Respeta los valores predeterminados de visibilidad, color, creador opcional y fechas. No renombra, reordena, reactiva ni elimina filas existentes. Su reversión no elimina las columnas.

Se detiene si falta o está inactivo VOBO_ANGIE, si un código reservado está inactivo, o si el nombre esperado identifica otra columna con código distinto. No adopta columnas del cliente ni reemplaza sus códigos. Una columna identificada por el código estable puede conservar un nombre visible diferente.

Primero se ejecutó el ensayo sobre `/tmp/zaha-migration-rehearsal.sqlite3`. Después se aplicaron 0012, 0013 y 0014 **exclusivamente al db.sqlite3 local**, con DATABASE_URL explícita. Se compararon todos los campos preexistentes de todas las tablas con el respaldo: ningún dato previo cambió.

Resultado local:

| Tablero | Nombre | Código | Orden |
|---|---|---|---|
| Operaciones | Factura de Fletes 1 | FACTURA_FLETES_1 | 12 |
| Cuenta de Gastos | Factura de Fletes 1 | FACTURA_FLETES_1 | 17 |
| Cuenta de Gastos | Solicitudes a Geo 1 | SOLICITUDES_GEO_1 | 18 |
| Cuenta de Gastos, existente | VoBo Angie | VOBO_ANGIE | 7, conservado |

Respaldo local: `/tmp/zaha-antes-0014-20261110-110454.sqlite3`.

## Archivos

Modificados durante esta tarea:

- `cuenta_gastos/admin.py`
- `cuenta_gastos/services.py`
- `cuenta_gastos/views.py`
- `cuenta_gastos/tests.py`
- `cuenta_gastos/test_automatizaciones.py` (ya existía sin seguimiento)
- `cuenta_gastos/test_columnas_automatizaciones.py`
- `operaciones/admin.py`
- `operaciones/management/commands/duplicar_tarjetas_pendientes.py`
- `operaciones/services.py`
- `operaciones/tests.py`
- `operaciones/views.py`
- `garantias/services.py`
- `solicitudes_app/trash.py`

Creados:

- `cuenta_gastos/migrations/0014_columnas_automatizaciones.py`
- `cuenta_gastos/test_compatibilidad_flujos.py`
- `operaciones/tests_flete.py`
- `solicitudes/tests_purga_segura.py`
- `AUTOMATIZACIONES_LOCALES.md`

Cambios locales previos preservados: `cuenta_gastos/models.py`, migraciones 0012/0013, `operaciones/services.py` y `operaciones/views.py`. La base local SQLite también recibió las migraciones; no está versionada.

## Compatibilidad y resolución de conflictos

1. **Reutilización de espejos antiguos**: `crear_cuenta_gastos_desde_operacion_si_corresponde` y `crear_copia_flete_desde_operacion` reutilizan el espejo existente sin activar transferencias colaterales a Geo ni alterar el estado.
2. **Transferencias anteriores sin errores 500**: La ausencia o inactividad de columnas nuevas (p. ej. `SOLICITUDES_GEO_1`) no interfiere en flujos históricos de Operaciones ni de Garantías.
3. **Purga definitiva segura**: `solicitudes_app/trash.py` defiere la eliminación de archivos físicos en almacenamiento a `transaction.on_commit(..., robust=True)` tras confirmar el borrado en base de datos. Si una tarjeta está protegida por relaciones `PROTECT` (como `operacion_flete_origen` o `vobo_angie_origen`) o ocurre un rollback, no se pierden los archivos físicos.
4. **Comando `duplicar_tarjetas_pendientes`**: La simulación (`--dry-run`) y la ejecución regularizan exclusivamente las operaciones en `SOLICITUD_CUENTA_GASTOS` sin duplicar hacia Geo ni modificar espejos existentes, incluso si fueron movidos o enviados a la papelera.
5. **Renombrado de columnas**: `_obtener_columna_devolucion_garantias` en `garantias/services.py` excluye las columnas dedicadas a flujos nuevos (`FACTURA_FLETES_1`, `SOLICITUDES_GEO_1`), impidiendo que un renombrado desvíe o bloquee la resolución de columnas históricas.
6. **Restauración desde papelera**: `restaurar_desde_papelera` recupera el objeto sin disparar nuevas transferencias ni automatizaciones, conservando las copias y relaciones preexistentes.
7. **Migración 0014**: Valida el catálogo atómicamente, rechaza la migración si los códigos reservados nuevos ya están ocupados o inactivos, y aborta sin modificar ni escribir en columnas existentes.

## Verificación

- **51 pruebas enfocadas: todas pasan** (`cuenta_gastos.test_compatibilidad_flujos`, `cuenta_gastos.test_columnas_automatizaciones`, `cuenta_gastos.test_automatizaciones`, `operaciones.tests_flete`, `solicitudes.tests_purga_segura`).
- **Suite completa: 687 pruebas**, exactamente los mismos 11 fallos y 1 error preexistentes, 2 omitidas; **0 nuevos fallos ni regresiones**.
- Las pruebas se ejecutaron con configuración de prueba aislada.
- `manage.py makemigrations --check --dry-run`: sin cambios pendientes de modelo.
- `manage.py check`: 0 incidencias.
- `git diff --check`: 0 errores.
- `manage.py migrate --plan`: sin operaciones pendientes.

Los flujos anteriores conservaron sus reglas; la selección de regresión pasa y la suite completa no incorpora fallos nuevos. La suite general ya tenía los siguientes problemas, que no se corrigieron por quedar fuera del alcance:

- `solicitudes_app.test_performance (unittest.loader._FailedTest.solicitudes_app.test_performance)`
- `test_listado_muestra_cuentas_por_cobrar_entre_correo_y_telefono (clientes.tests.ClientePaginationTests.test_listado_muestra_cuentas_por_cobrar_entre_correo_y_telefono)`
- `test_drawer_y_modal_comparten_el_mismo_contenido_interno (operaciones.tests.OperacionesDetalleModalTests.test_drawer_y_modal_comparten_el_mismo_contenido_interno)`
- `test_editar_operacion_guarda_descripcion_y_conserva_relaciones (operaciones.tests.OperacionesDetalleModalTests.test_editar_operacion_guarda_descripcion_y_conserva_relaciones)`
- `test_detalle_renderiza_seccion_estado_vacio_descripcion_y_etiquetas (operaciones.tests.OperacionesElementosAccionAjaxTests.test_detalle_renderiza_seccion_estado_vacio_descripcion_y_etiquetas)`
- `test_guardar_operacion_no_elimina_elementos (operaciones.tests.OperacionesElementosAccionAjaxTests.test_guardar_operacion_no_elimina_elementos)`
- `test_crea_operacion_con_descripcion_archivos_y_enlaces (operaciones.tests.OperacionesInlineCreateTests.test_crea_operacion_con_descripcion_archivos_y_enlaces)`
- `test_endpoint_get_devuelve_formulario_completo_sin_crear_operaciones (operaciones.tests.OperacionesInlineCreateTests.test_endpoint_get_devuelve_formulario_completo_sin_crear_operaciones)`
- `test_javascript_evitar_insertar_tarjeta_ajena_al_filtro_activo (operaciones.tests.OperacionesInlineCreateTests.test_javascript_evitar_insertar_tarjeta_ajena_al_filtro_activo)`
- `test_javascript_tom_select_se_inicializa_y_destruye_una_sola_vez (operaciones.tests.OperacionesInlineCreateTests.test_javascript_tom_select_se_inicializa_y_destruye_una_sola_vez)`
- `test_movimientos_validan_moneda_y_no_mezclan_totales (solicitudes.tests.ReferenciaFacturaYMonedaTests.test_movimientos_validan_moneda_y_no_mezclan_totales)`
- `test_consultas_son_constantes_y_sin_n_mas_uno (solicitudes.tests.UsuariosPaginationFase9BTests.test_consultas_son_constantes_y_sin_n_mas_uno)`

## Riesgos y límites de despliegue

- No se inspeccionó la base de producción. Su catálogo debe satisfacer la validación de 0014; ante un conflicto, se detiene sin modificar las columnas existentes. No se debe reasignar un código para forzarla.
- Aplicar el esquema 0012/0013 y los datos 0014 antes de habilitar el código nuevo. Cada migración tiene su propia transacción: si 0014 se detiene, las migraciones de esquema anteriores pueden haber quedado aplicadas.
- Las pruebas y el ensayo se ejecutaron en SQLite; no se ejecutaron pruebas en PostgreSQL ni producción. Se conserva la protección de unicidad OneToOne y se limita el bloqueo de la consulta de VoBo a la propia tarjeta para evitar bloquear el lado nullable del JOIN en PostgreSQL.
- La migración crea columnas, no copias retroactivas de tarjetas históricas. Las automatizaciones se ejecutan al entrar por las rutas controladas.
- Desactivar un origen o destino reservado impide operar el flujo y produce un error de configuración; la migración no reactiva datos del cliente.
- Revertir solo 0014 conserva las columnas y sus tarjetas deliberadamente. No se probó ni ejecutó una reversión destructiva de las relaciones 0012/0013.
