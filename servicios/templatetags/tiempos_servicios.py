from django import template

register = template.Library()


@register.filter
def horas_corridas(duracion):
    minutos = int(duracion.total_seconds()) // 60
    horas, resto = divmod(minutos, 60)
    return f"{horas} h {resto} min" if horas else f"{resto} min"
