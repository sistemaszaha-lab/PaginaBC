import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Operacion
from cuenta_gastos.models import CuentaGastos, CuentaGastosColumna

@receiver(post_save, sender=Operacion)
def clonar_operacion_a_cuenta_gastos(sender, instance, created, **kwargs):
    try:
        if not instance.columna:
            return

        # 1. Buscar la columna por su nombre exacto de texto
        if instance.columna.nombre.lower() == "solicitud a cuenta de gastos":
            
            columna_destino = CuentaGastosColumna.objects.filter(nombre__iexact="Solicitud de pago").first()
            
            if columna_destino:
                # 2. Anti-duplicados: Usar get_or_create filtrando por título
                CuentaGastos.objects.get_or_create(
                    titulo=instance.titulo,
                    defaults={
                        'operacion_origen': instance,
                        'descripcion': instance.descripcion,
                        'cliente': instance.cliente,
                        'columna': columna_destino,
                        'estado': columna_destino.codigo,
                        'prioridad': instance.prioridad,
                        'creado_por': instance.creado_por,
                        'fecha_vencimiento': instance.fecha_vencimiento
                    }
                )
            else:
                print("[ADVERTENCIA] No se pudo clonar porque no existe la columna 'Solicitud de pago'.")
                
    except Exception as e:
        # 3. Chaleco antibalas: Tragarse la excepción y solo imprimir el error
        print(f"[CRÍTICO] Fallo silencioso al clonar Operacion ID {instance.id}. Error: {str(e)}")
