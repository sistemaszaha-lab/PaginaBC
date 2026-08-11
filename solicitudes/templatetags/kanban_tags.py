from django import template

register = template.Library()

@register.filter
def get_estado_choices(obj):
    """
    Devuelve las opciones (choices) del campo 'estado' de un modelo.
    Útil para iterar sobre los estados de Garantía o PanelCotizacion en la vista.
    """
    try:
        return obj._meta.get_field('estado').choices
    except Exception:
        return []

@register.filter
def contrast_color(hex_color):
    """
    Calculates the relative luminance of a hex color and returns '#000000'
    or '#ffffff' to ensure high contrast text.
    Handles invalid or empty values defensively.
    """
    if not hex_color or not isinstance(hex_color, str):
        return "#000000"

    hex_color = hex_color.strip().lstrip('#')
    
    if len(hex_color) == 3:
        hex_color = ''.join(c + c for c in hex_color)
    
    if len(hex_color) != 6:
        return "#000000"
        
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
    except ValueError:
        return "#000000"
        
    # Relative luminance formula
    r_lum = r / 255.0
    g_lum = g / 255.0
    b_lum = b / 255.0

    r_lum = r_lum / 12.92 if r_lum <= 0.03928 else ((r_lum + 0.055) / 1.055) ** 2.4
    g_lum = g_lum / 12.92 if g_lum <= 0.03928 else ((g_lum + 0.055) / 1.055) ** 2.4
    b_lum = b_lum / 12.92 if b_lum <= 0.03928 else ((b_lum + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * r_lum + 0.7152 * g_lum + 0.0722 * b_lum
    
    # 0.179 is a typical threshold, equivalent to ~128 in sRGB
    if luminance > 0.179:
        return "#000000"
    return "#ffffff"
