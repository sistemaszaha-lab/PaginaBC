from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from clientes.models import Cliente, normalizar_texto_cliente
from panel_cotizaciones.models import PanelCotizacion
from solicitudes.models import Cotizacion, Referencia, Solicitud


class Command(BaseCommand):
    help = (
        "Normaliza el campo cliente en Solicitud, Cotizacion, Referencia y "
        "PanelCotizacion sin tocar relaciones ni crear clientes."
    )

    MODELOS = {
        "solicitud": ("Solicitud", Solicitud),
        "cotizacion": ("Cotizacion", Cotizacion),
        "referencia": ("Referencia", Referencia),
        "panel_cotizacion": ("PanelCotizacion", PanelCotizacion),
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra los cambios que se realizarian sin guardar nada.",
        )
        parser.add_argument(
            "--modelo",
            choices=["solicitud", "cotizacion", "referencia", "panel_cotizacion", "todos"],
            default="todos",
            help="Limita la normalizacion a un modelo especifico.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        modelo = options["modelo"]
        modelos = self._resolver_modelos(modelo)
        resumen = self._analizar_modelos(modelos)

        if dry_run:
            self._mostrar_cambios(resumen["cambios"])
            self._mostrar_resumen_por_modelo(resumen["por_modelo"])
            self._mostrar_variantes(resumen["variantes"])
            self._mostrar_resumen_general(resumen, dry_run=True)
            return

        errores = resumen["errores"]
        modificados = 0

        try:
            with transaction.atomic():
                for cambio in resumen["cambios"]:
                    modelo_cls = cambio["model_class"]
                    # En este comando historico usamos update() a proposito para evitar
                    # ejecutar save(), señales o logica secundaria. Esto es
                    # especialmente importante en Cotizacion, cuyo save() puede
                    # disparar logica de alta que aqui no debe correr.
                    modificados += modelo_cls.objects.filter(pk=cambio["id"]).update(
                        cliente=cambio["nuevo_valor"]
                    )
        except Exception as exc:
            errores += 1
            self.stdout.write(self.style.ERROR(f"ERROR: {exc}"))

        resumen["errores"] = errores
        resumen["cambios_realizados"] = modificados
        self._mostrar_resumen_por_modelo(resumen["por_modelo"])
        self._mostrar_variantes(resumen["variantes"])
        self._mostrar_resumen_general(resumen, dry_run=False)

    def _resolver_modelos(self, modelo):
        if modelo == "todos":
            return list(self.MODELOS.items())
        return [(modelo, self.MODELOS[modelo])]

    def _analizar_modelos(self, modelos):
        cambios = []
        variantes = {}
        por_modelo = {}
        total_revisados = 0
        total_cambios = 0
        total_sin_cambios = 0
        errores = 0

        for clave, (nombre_modelo, model_class) in modelos:
            revisados = 0
            cambiaria = 0
            sin_cambios = 0
            variantes_modelo = defaultdict(set)

            for registro in model_class.objects.order_by("pk").iterator():
                revisados += 1
                total_revisados += 1
                try:
                    valor_actual = registro.cliente
                    valor_normalizado = self._normalizar_respetando_null(valor_actual)

                    if valor_actual != valor_normalizado:
                        cambios.append(
                            {
                                "modelo": nombre_modelo,
                                "model_class": model_class,
                                "id": registro.pk,
                                "valor_anterior": valor_actual,
                                "nuevo_valor": valor_normalizado,
                            }
                        )
                        cambiaria += 1
                        total_cambios += 1
                    else:
                        sin_cambios += 1
                        total_sin_cambios += 1

                    clave_variante = valor_normalizado
                    if clave_variante not in (None, "") and valor_actual not in (None, ""):
                        variantes_modelo[clave_variante].add(valor_actual)
                except Exception as exc:
                    errores += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"ERROR analizando {nombre_modelo} ID {registro.pk}: {exc}"
                        )
                    )

            por_modelo[nombre_modelo] = {
                "revisados": revisados,
                "cambiaria": cambiaria,
                "sin_cambios": sin_cambios,
            }
            variantes[nombre_modelo] = {
                normalizado: sorted(valores)
                for normalizado, valores in variantes_modelo.items()
                if len(valores) > 1
            }

        return {
            "cambios": cambios,
            "por_modelo": por_modelo,
            "variantes": variantes,
            "total_revisados": total_revisados,
            "total_cambios": total_cambios,
            "total_sin_cambios": total_sin_cambios,
            "errores": errores,
            "clientes_catalogo": Cliente.objects.count(),
        }

    def _normalizar_respetando_null(self, valor):
        if valor is None:
            return None
        return normalizar_texto_cliente(valor)

    def _mostrar_cambios(self, cambios):
        if not cambios:
            self.stdout.write("No hay registros historicos que requieran normalizacion.")
            return

        self.stdout.write("Registros que cambiarian:")
        for cambio in cambios:
            self.stdout.write(
                f"{cambio['modelo']} ID {cambio['id']} | "
                f"Anterior: {repr(cambio['valor_anterior'])} | "
                f"Normalizado: {repr(cambio['nuevo_valor'])}"
            )

    def _mostrar_resumen_por_modelo(self, por_modelo):
        self.stdout.write("")
        self.stdout.write("Resumen por modelo:")
        for nombre_modelo, resumen in por_modelo.items():
            self.stdout.write(f"- {nombre_modelo}:")
            self.stdout.write(f"  Revisados: {resumen['revisados']}")
            self.stdout.write(f"  Cambiaria/modificados: {resumen['cambiaria']}")
            self.stdout.write(f"  Sin cambios: {resumen['sin_cambios']}")

    def _mostrar_variantes(self, variantes):
        self.stdout.write("")
        self.stdout.write("Variantes historicas encontradas:")
        hubo_variantes = False
        for nombre_modelo, grupos in variantes.items():
            if not grupos:
                continue
            hubo_variantes = True
            self.stdout.write(f"- {nombre_modelo}:")
            for normalizado, valores in grupos.items():
                self.stdout.write(f"  Valor normalizado: {normalizado}")
                self.stdout.write("  Variantes encontradas:")
                for valor in valores:
                    self.stdout.write(f"  - {valor}")

        if not hubo_variantes:
            self.stdout.write("No se encontraron variantes historicas.")

    def _mostrar_resumen_general(self, resumen, dry_run):
        self.stdout.write("")
        self.stdout.write(
            f"Modo: {'SIMULACION (--dry-run)' if dry_run else 'EJECUCION REAL'}"
        )
        self.stdout.write(f"Total general de registros revisados: {resumen['total_revisados']}")
        if dry_run:
            self.stdout.write(
                f"Total general de registros que cambiarian: {resumen['total_cambios']}"
            )
        else:
            self.stdout.write(
                f"Total general de registros modificados: {resumen['cambios_realizados']}"
            )
        self.stdout.write(
            f"Total general de registros sin cambios: {resumen['total_sin_cambios']}"
        )
        self.stdout.write(f"Errores: {resumen['errores']}")
        self.stdout.write(
            f"Clientes en catalogo (sin cambios): {resumen['clientes_catalogo']}"
        )
