# Preparación de la purga diaria de la papelera

Estado: **propuesta local; no configurada ni activada en Railway**.

## Política y diagnóstico previo

`purgar_papelera` usa `eliminado_en <= timezone.now() - timedelta(days=30)`.
El umbral exige 30 días completos desde la eliminación. La opción `--days`
admite plazos mayores, pero rechaza valores inferiores a 30. `--dry-run`
revisa candidatos y relaciones con el colector de Django, e informa por modelo
vencidos, potencialmente eliminables, protegidos, errores y motivos. No llama a
`delete()` ni borra archivos. La clasificación es una fotografía: entre la
simulación y una ejecución real las relaciones pueden cambiar.
El comando recorre los candidatos en lotes de hasta 200 registros por modelo
para limitar la memoria ocupada durante una ejecución larga.
Los errores individuales se escriben en stderr y provocan una salida distinta
de cero después del resumen; los bloqueos `PROTECT` se informan por separado.
La ejecución real vuelve a comprobar `eliminado_en` bajo bloqueo antes de cada
borrado para conservar los registros restaurados o aún no vencidos.

```sh
python manage.py purgar_papelera --dry-run
```

Este comando es apto para una revisión previa en un entorno con acceso de solo
lectura a la base de datos. No usar la ejecución sin `--dry-run` hasta completar
las condiciones de almacenamiento y despliegue indicadas abajo.

## Relaciones de los flujos

| Origen a purgar | Relación dependiente | Regla | Consecuencia |
| --- | --- | --- | --- |
| Operación | Cuenta de Gastos ordinaria (`operacion_origen`) | `SET_NULL` | La copia permanece sin vínculo. |
| Operación | Garantía (`operacion_origen`) | `SET_NULL` | La garantía permanece sin vínculo. |
| Operación | Cuenta de Gastos de flete (`operacion_flete_origen`) | `PROTECT` | Se bloquea la purga del origen. |
| Operación | Cuenta de Gastos de anticipo (`operacion_anticipo_origen`) | `PROTECT` | Se bloquea la purga del origen cuando esta migración local esté aplicada. |
| Garantía | Cuenta de Gastos (`garantia_origen`) | `SET_NULL` | La copia permanece sin vínculo. |
| Cuenta de Gastos | Copia de Solicitudes a Geo (`vobo_angie_origen`) | `PROTECT` | Se bloquea la purga del origen. |
| Solicitud | Referencia / cotización del panel | `SET_NULL` | Los registros derivados permanecen. |
| Cotización del panel | Referencia | `SET_NULL` | La referencia permanece. |
| Referencia | Operación / garantía | `SET_NULL` | Permanecen sin vínculo a la referencia. |
| Referencia | Facturas / movimientos | `CASCADE` | Se eliminan junto con la referencia. |
| Operación, garantía, cuenta o cotización del panel | Comentarios, archivos y enlaces dependientes | `CASCADE` | Se eliminan los registros dependientes. Los archivos físicos configurados se borran tras el commit. |

No se encontraron relaciones `RESTRICT` en estos flujos; si se agregan más
adelante, el colector también las evaluará y reportará. El comando no desvincula
ni elimina copias activas para despejar un bloqueo. Los bloqueados permanecen
en papelera y deben revisarse como excepción a la meta de retención.

## Propuesta de ejecución diaria

Crear **un servicio Cron separado del servicio web** con el mismo código,
`DATABASE_URL` y `DJANGO_SECRET_KEY`, cuyo proceso de inicio sea
`python manage.py purgar_papelera` y termine al acabar. Configurar la agenda
`0 9 * * *` (09:00 UTC todos los días). La primera revisión debe hacerse con
`python manage.py purgar_papelera --dry-run` en un entorno controlado. Registrar
por ejecución el resumen, errores individuales, duración y estado final.

**Bloqueo de activación: archivos.** El proyecto guarda subidas mediante
`FileSystemStorage` en `uploads`. Un Cron separado no comparte automáticamente
el disco local del servicio web; Railway permite adjuntar un volumen a un solo
servicio. Antes de una purga real desde un servicio separado, confirmar y
preparar un almacenamiento accesible desde ambos procesos, con pruebas de
borrado físico tras commit. Sin ello, se podrían borrar registros de la base de
datos y dejar archivos en el almacenamiento del servicio web.
Si un borrado físico falla después del commit, el registro ya no puede servir
para reintentar automáticamente; revisar los errores de almacenamiento y definir
una conciliación de archivos antes de activar la tarea.

El `railway.toml` actual define Gunicorn como `startCommand` y la configuración
en código puede prevalecer sobre ajustes del servicio. Verificar el comando de
inicio **efectivo** del Cron antes de activarlo. Railway recomienda ahora su
Infrastructure as Code para servicios nuevos; no reutilizar ni cambiar el
`railway.toml` del servicio web para programar la purga.

Railway documenta que los Cron usan UTC, ejecutan el comando de inicio y omiten
una ejecución si la anterior sigue activa. Revisar los estados `EXITED`,
`CRASHED` y `SKIPPED`, y alertar si no hay una ejecución terminada en el día o
quedan errores/protegidos pendientes. Una ejecución diaria puede eliminar un
registro después de cumplir 30 días, con un retraso de hasta aproximadamente
un día según la hora en que fue enviado a la papelera.

Referencias: https://docs.railway.com/cron-jobs ;
https://docs.railway.com/infrastructure-as-code/reference ;
https://docs.railway.com/config-as-code .
