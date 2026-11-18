# Purga diaria de la papelera en Railway

Estado al 18 de noviembre de 2026: **validada localmente; pendiente de prueba y activación en Actions**. No se ha ejecutado ninguna purga real en producción.

Auditoría de reanudación: main remoto y local partían de `0b0b765`. Se conservaron los cambios pendientes de retención, bloqueo concurrente, protección de vínculos activos y cola durable de archivos. No se modificaron las vistas ni los filtros ni el botón de anticipo. Pasaron 40 pruebas de purga/anticipo, 27 con PostgreSQL y 6 de shell del workflow. La suite general anterior ejecutó 750 pruebas y tuvo 3 fallos y 1 error, reproducidos también en la versión base (clientes, moneda, consultas y dependencia de performance).

Un dry-run ejecutado por SSH directo dentro de `web` sobre el despliegue actualizado el 17 de noviembre terminó con código 0 en **95.85 segundos** y **472 vencidos potencialmente eliminables**, sin protegidos ni errores: 3 etiquetas, 201 operaciones, 12 garantías, 82 cotizaciones del panel, 163 cuentas de gastos, 1 solicitud, 1 cotización de referencia, 1 referencia y 8 documentos. La salida confirmó: `Simulación de solo lectura completada; no se eliminó ningún elemento.` Todavía falta la prueba completa desde GitHub Actions.

## Comportamiento

El workflow `.github/workflows/purga-papelera.yml` ejecuta `python manage.py purgar_papelera` por SSH dentro del servicio `web`, que tiene montado `/app/uploads`. La agenda es `0 9 * * *` UTC, equivalente a las 03:00 de Ciudad de México. No cambia el proceso Gunicorn ni el volumen.

El comando conserva cada registro hasta cumplir al menos 30 días desde `eliminado_en`, comprueba de nuevo el vencimiento bajo bloqueo de fila antes del borrado, y omite los restaurados. El colector de Django respeta `PROTECT` y `RESTRICT`; los registros protegidos quedan en papelera y se registran. Los archivos asociados se borran después del commit de la transacción. Una cola durable (`ArchivoPurgaPendiente`, migración 0018) conserva los borrados de archivos pendientes para reintentarlos en la siguiente ejecución. Los archivos todavía referenciados se conservan. El fallo de almacenamiento hace fallar el job; el registro ya confirmado en BD no se revierte.

El comando usa un bloqueo asesor de sesión de PostgreSQL para impedir que dos invocaciones, también manuales o externas, purguen a la vez. El workflow añade `concurrency` sin cancelar la ejecución en curso. La salida del comando y el resumen de Actions muestran modo, estado, errores y duración. El job tiene un límite de 60 minutos y el SSH de 50 minutos. Si se interrumpe, cada registro ya confirmado permanece eliminado y los siguientes quedan para otra ejecución; una nueva invocación obtiene el bloqueo cuando la conexión anterior termina.

## Preparación de GitHub Actions

Railway SSH usa una llave registrada en Railway. El token de proyecto `RAILWAY_TOKEN` no sirve para abrir SSH; no se incluye ningún token de Railway en el workflow. Para limitar el alcance, registrar una llave exclusiva del workflow en una identidad de Railway que sólo tenga acceso al proyecto necesario. Las llaves de un workspace dan acceso a todos sus servicios. Proteger la rama por defecto y restringir quién puede editar workflows y Secrets.

Configurar estos valores en el repositorio GitHub:

| Tipo | Nombre | Valor |
| --- | --- | --- |
| Secret | `RAILWAY_SSH_PRIVATE_KEY` | Llave privada exclusiva del workflow, con su pública registrada en Railway. |
| Secret | `RAILWAY_SSH_KNOWN_HOSTS` | Entrada verificada para `ssh.railway.com`, obtenida fuera del runner. |
| Variable | `RAILWAY_WEB_SSH_USER` | Usuario SSH estable obtenido con `railway ssh config --service web --dry-run`: `cc5260a5-1f84-4f76-8378-1a545b2e1a0a`. |
| Variable | `PURGA_PAPELERA_ACTIVA` | Ausente o `false` durante la preparación; `true` sólo después de autorizar la primera purga real. |

El workflow no requiere permisos de `GITHUB_TOKEN`. `workflow_dispatch` permite `dry-run` con la variable desactivada; tanto la agenda como una invocación manual `real` requieren `PURGA_PAPELERA_ACTIVA=true`.

## Prueba y activación

1. Publicar el workflow en la rama por defecto con `PURGA_PAPELERA_ACTIVA` ausente o `false`.
2. Ejecutar manualmente `Purga de papelera Railway` con `modo=dry-run`. Verificar en el log que SSH llega a `web`, encuentra `/app/manage.py`, termina con código cero y muestra la simulación de solo lectura. Revisar los totales y los protegidos.
3. Confirmar respaldos recientes de **PostgreSQL y del volumen `web-volume`**, su fecha, alcance y una restauración de prueba en un destino aislado. Volver a ejecutar el dry-run inmediatamente antes de la primera purga.
4. La instrucción del usuario autoriza completar la automatización y condiciona la primera purga al respaldo restaurable. Una vez verificados respaldo, despliegue y dry-run, poner `PURGA_PAPELERA_ACTIVA=true`, ejecutar `modo=real` una vez y comprobar los resultados. Desde entonces, las ejecuciones diarias no requieren aprobaciones.

Para desactivar la automatización, cambiar `PURGA_PAPELERA_ACTIVA` a `false` o quitarla. Esto bloquea nuevas ejecuciones reales programadas o manuales; no cancela un proceso en curso. Para detener uno en curso, cancelar el job y comprobar el estado de la sesión remota y su bloqueo antes de reintentar.

## Monitoreo

Revisar cada día la ejecución de `Purga de papelera Railway` en **GitHub Actions**. El log remoto contiene los totales por modelo y cada elemento protegido o fallido. Un job rojo o ausente, `errores>0`, o protegidos persistentes requieren investigación. No forzar eliminaciones para despejar un bloqueo. El éxito del job no garantiza que se hayan borrado todos los archivos después del commit; revisar errores de storage y conciliar archivos huérfanos si aparecen.

## Estado de respaldos comprobado

El 17 de noviembre de 2026, `railway postgres pitr status --service Postgres --json` indicó `enabled=false`. `railway postgres pitr backup list --service Postgres --json` y `schedule list` devolvieron listas vacías. La lista de respaldos de `web` también devolvió `[]`. Railway rechazó crear un snapshot manual: `Manual backups and backup schedules are only available for Pro workspaces`. **No hay respaldo reciente ni restauración verificable confirmados de PostgreSQL o `web-volume`; la purga real sigue bloqueada.**

PITR está disponible como función de Railway, pero no está habilitado en este proyecto. Según Railway, usa almacenamiento de bucket y egreso facturados; habilitarlo no crea cobertura retroactiva. Consultar el plan y el costo real antes de decidir. Referencias: [SSH](https://docs.railway.com/cli/ssh), [respaldos de volúmenes](https://docs.railway.com/volumes/backups), [PITR](https://docs.railway.com/volumes/point-in-time-recovery), [agenda de Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule).

## Respaldo externo verificado el 18 de noviembre de 2026

El estado histórico de snapshots de Railway arriba no describe el respaldo externo posterior. A las 00:02 de Ciudad de México se exportó PostgreSQL y `/app/uploads` en `backups/purga-20261118/` (excluido de Git). PostgreSQL fue restaurado con `pg_restore --exit-on-error` en `zaha_restore_20261118`, PostgreSQL 18 local, puerto 55439: 59 tablas, código 0. Los 15 archivos fueron extraídos y sus SHA256 verificados; el inventario del volumen no cambió durante la captura. Se aplicó la migración nueva y se ensayaron dos purgas sobre la copia aislada, con los registros activos intactos.

- PostgreSQL SHA256: `c4bf1ad8d42a40da225ae70accb6456cba5de481abd5d057064650ec5820e419`.
- Volumen SHA256: `a152689ce7a985ef3a1b488f336fee3b3be3017dd926ac222b2a11cc57020a9b`.
- Evidencia local: `verification.json`, `migrate.log`, `rehearsal.log`. El respaldo vive en este equipo; no equivale a un plan de respaldos automáticos externo.

Se autorizó explícitamente registrar la llave dedicada `zaha-purga-actions` y almacenar su privada en GitHub Secrets. Fingerprint: `SHA256:6FshuVDqSmVJc4TD93IMRRWdldjPKZRKz8An4r40vkU`. La llave es personal y hereda el acceso de la cuenta Railway; el workflow valida proyecto, entorno, servicio y volumen antes de ejecutar.
