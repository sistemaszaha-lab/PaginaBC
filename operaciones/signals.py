"""Compatibilidad histórica: la transferencia ya no usa ``post_save``."""


def duplicar_a_cuenta_gastos_si_corresponde(*args, **kwargs):
    """Nombre legado conservado para imports; no registra ni ejecuta señales."""
    return None
