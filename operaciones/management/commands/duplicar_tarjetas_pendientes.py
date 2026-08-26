"""
Management command: duplicar_tarjetas_pendientes

Recorre todas las Operaciones activas en la columna SOLICITUD_CUENTA_GASTOS
y crea (si aún no existe) la tarjeta espejo en CuentaGastos.

Reutiliza exactamente la misma función que el signal y la vista mover,
por lo que es idempotente: ejecutarlo N veces produce el mismo resultado.

Uso:
    python manage.py duplicar_tarjetas_pendientes
    python manage.py duplicar_tarjetas_pendientes --dry-run
    python manage.py duplicar_tarjetas_pendientes --creado-por <username>
"""
import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from operaciones.models import Operacion
from cuenta_gastos.services import crear_cuenta_gastos_desde_operacion_si_corresponde

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = (
        "Backfill: duplica hacia CuentaGastos todas las Operaciones "
        "que ya están en la columna 'SOLICITUD_CUENTA_GASTOS' y aún "
        "no tienen su tarjeta espejo. Es seguro ejecutarlo múltiples veces."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Muestra cuántas tarjetas se crearían sin escribir en BD.",
        )
        parser.add_argument(
            "--creado-por",
            metavar="USERNAME",
            default=None,
            help=(
                "Username del usuario que aparecerá como creador en las "
                "tarjetas nuevas de CuentaGastos. Si se omite, se usa el "
                "creado_por de cada Operacion origen."
            ),
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        username: str | None = options["creado_por"]

        # Resolver usuario override (opcional)
        usuario_override = None
        if username:
            try:
                usuario_override = User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(
                    f"No existe ningún usuario con username='{username}'."
                )

        # Obtener operaciones candidatas (activas, en la columna correcta,
        # ordenadas por posición para mantener el orden en cuenta_gastos)
        operaciones = (
            Operacion.objects
            .filter(
                estado=Operacion.Estado.SOLICITUD_CUENTA_GASTOS,
                eliminado_en__isnull=True,
            )
            .select_related("cliente", "creado_por", "columna")
            .prefetch_related("asignados")
            .order_by("posicion", "-fecha_creacion", "-id")
        )

        total = operaciones.count()
        self.stdout.write(
            self.style.NOTICE(
                f"Operaciones en SOLICITUD_CUENTA_GASTOS: {total}"
            )
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("-- DRY RUN: no se escribirá en la BD --"))

        creadas = 0
        ya_existian = 0
        errores = 0

        for op in operaciones:
            creado_por = usuario_override or op.creado_por
            if dry_run:
                from cuenta_gastos.models import CuentaGastos
                existe = CuentaGastos.objects.filter(operacion_origen=op).exists()
                if existe:
                    ya_existian += 1
                    self.stdout.write(f"  [SKIP]  Operacion id={op.pk} '{op.titulo}' ya tiene espejo.")
                else:
                    creadas += 1
                    self.stdout.write(f"  [NEW]   Operacion id={op.pk} '{op.titulo}' → se crearía.")
                continue

            try:
                _cuenta, fue_creada = crear_cuenta_gastos_desde_operacion_si_corresponde(
                    op,
                    creado_por=creado_por,
                )
                if fue_creada:
                    creadas += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [OK]    Operacion id={op.pk} '{op.titulo}' -> CuentaGastos creada."
                        )
                    )
                else:
                    ya_existian += 1
                    self.stdout.write(
                        f"  [SKIP]  Operacion id={op.pk} '{op.titulo}' ya tiene espejo."
                    )
            except Exception as exc:
                errores += 1
                logger.exception("Error al procesar Operacion id=%s.", op.pk)
                self.stderr.write(
                    self.style.ERROR(
                        f"  [ERROR] Operacion id={op.pk} '{op.titulo}': {exc}"
                    )
                )

        # Resumen final
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Creadas:      {creadas}"))
        self.stdout.write(f"Ya existían:  {ya_existian}")
        if errores:
            self.stdout.write(self.style.ERROR(f"Con errores:  {errores}"))
        if dry_run:
            self.stdout.write(self.style.WARNING("(dry-run: ningún cambio fue guardado)"))
