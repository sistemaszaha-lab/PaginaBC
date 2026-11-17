# Purga diaria de la papelera en Railway

Estado al 17 de noviembre de 2026: **preparada localmente; desactivada**. No se ha ejecutado ninguna purga real.

Un dry-run ejecutado por Railway SSH dentro de `web` el 17 de noviembre terminó con código 0 y **472 vencidos potencialmente eliminables**, sin protegidos ni errores: 3 etiquetas, 201 operaciones, 12 garantías, 82 cotizaciones del panel, 163 cuentas de gastos, 1 solicitud, 1 cotización de referencia, 1 referencia y 8 documentos. La salida confirmó: `Simulación de solo lectura completada; no se eliminó ningún elemento.` Esta prueba fue desde la CLI local; todavía falta la prueba completa desde GitHub Actions.

## Comportamiento

El workflow `.github/workflows/purga-papelera.yml` ejecuta `python manage.py purgar_papelera` por SSH dentro del servicio `web`, que tiene montado `/app/uploads`. La agenda es `0 3 * * *` en `America/Mexico_City`. No cambia el proceso Gunicorn ni el volumen.

El comando conserva cada registro hasta cumplir al menos 30 días desde `eliminado_en`, comprueba de nuevo el vencimiento bajo bloqueo de fila antes del borrado, y omite los restaurados. El colector de Django respeta `PROTECT` y `RESTRICT`; los registros protegidos quedan en papelera y se registran. Los archivos asociados se borran después del commit de la transacción. Un error al borrar un archivo después del commit puede dejar un archivo huérfano: el error se registra, pero el registro de BD ya no se puede recuperar mediante rollback.

El comando usa un bloqueo asesor de sesión de PostgreSQL para impedir que dos invocaciones, también manuales o externas, purguen a la vez. El workflow añade `concurrency` sin cancelar la ejecución en curso. La salida del comando y el resumen de Actions muestran modo, estado, errores y duración. El job tiene un límite de 60 minutos y el SSH de 50 minutos. Si se interrumpe, cada registro ya confirmado permanece eliminado y los siguientes quedan para otra ejecución; una nueva invocación obtiene el bloqueo cuando la conexión anterior termina.

## Preparación de GitHub Actions

Railway SSH usa una llave registrada en Railway. El token de proyecto `RAILWAY_TOKEN` no sirve para abrir SSH; no se incluye ningún token de Railway en el workflow. Para limitar el alcance, registrar una llave exclusiva del workflow en una identidad de Railway que sólo tenga acceso al proyecto necesario. Las llaves de un workspace dan acceso a todos sus servicios. Proteger la rama por defecto y restringir quién puede editar workflows y Secrets.

Configurar estos valores en el repositorio GitHub:

| Tipo | Nombre | Valor |
| --- | --- | --- |
| Secret | `RAILWAY_SSH_PRIVATE_KEY` | Llave privada exclusiva del workflow, con su pública registrada en Railway. |
| Secret | `RAILWAY_SSH_KNOWN_HOSTS` | Entrada verificada para `ssh.railway.com`, obtenida fuera del runner. |
| Variable | `RAILWAY_WEB_SSH_USER` | Dominio SSH del servicio `web`, sin `@ssh.railway.com` (actualmente `web-production-535f2.up.railway.app`). |
| Variable | `PURGA_PAPELERA_ACTIVA` | Ausente o `false` durante la preparación; `true` sólo después de autorizar la primera purga real. |

El workflow no requiere permisos de `GITHUB_TOKEN`. `workflow_dispatch` permite `dry-run` con la variable desactivada; tanto la agenda como una invocación manual `real` requieren `PURGA_PAPELERA_ACTIVA=true`.

## Prueba y activación

1. Publicar el workflow en la rama por defecto con `PURGA_PAPELERA_ACTIVA` ausente o `false`.
2. Ejecutar manualmente `Purga de papelera Railway` con `modo=dry-run`. Verificar en el log que SSH llega a `web`, encuentra `/app/manage.py`, termina con código cero y muestra la simulación de solo lectura. Revisar los totales y los protegidos.
3. Confirmar respaldos recientes de **PostgreSQL y del volumen `web-volume`**, su fecha, alcance y una restauración de prueba en un destino aislado. Volver a ejecutar el dry-run inmediatamente antes de la primera purga.
4. Solicitar autorización explícita para la primera purga real y el inicio de la agenda. Una vez concedida, poner `PURGA_PAPELERA_ACTIVA=true`, ejecutar `modo=real` una vez y comprobar los resultados. Desde entonces, las ejecuciones diarias no requieren aprobaciones.

Para desactivar la automatización, cambiar `PURGA_PAPELERA_ACTIVA` a `false` o quitarla. Esto bloquea nuevas ejecuciones reales programadas o manuales; no cancela un proceso en curso. Para detener uno en curso, cancelar el job y comprobar el estado de la sesión remota y su bloqueo antes de reintentar.

## Monitoreo

Revisar cada día la ejecución de `Purga de papelera Railway` en **GitHub Actions**. El log remoto contiene los totales por modelo y cada elemento protegido o fallido. Un job rojo o ausente, `errores>0`, o protegidos persistentes requieren investigación. No forzar eliminaciones para despejar un bloqueo. El éxito del job no garantiza que se hayan borrado todos los archivos después del commit; revisar errores de storage y conciliar archivos huérfanos si aparecen.

## Estado de respaldos comprobado

El 17 de noviembre de 2026, `railway postgres pitr status --service Postgres --json` indicó `enabled=false`. `railway postgres pitr backup list --service Postgres --json` y `schedule list` devolvieron listas vacías. La lista de respaldos de `web` también devolvió `[]`. Railway rechazó crear un snapshot manual: `Manual backups and backup schedules are only available for Pro workspaces`. **No hay respaldo reciente ni restauración verificable confirmados de PostgreSQL o `web-volume`; la purga real sigue bloqueada.**

PITR está disponible como función de Railway, pero no está habilitado en este proyecto. Según Railway, usa almacenamiento de bucket y egreso facturados; habilitarlo no crea cobertura retroactiva. Consultar el plan y el costo real antes de decidir. Referencias: [SSH](https://docs.railway.com/cli/ssh), [respaldos de volúmenes](https://docs.railway.com/volumes/backups), [PITR](https://docs.railway.com/volumes/point-in-time-recovery), [agenda de Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule).
