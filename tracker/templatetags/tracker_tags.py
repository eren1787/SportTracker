from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def time_remaining(expires_at):
    """Returns a human-readable string like '31s 14d kaldı' or 'Süresi Doldu'."""
    delta = expires_at - timezone.now()
    if delta.total_seconds() <= 0:
        return "Süresi Doldu"
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    return f"{hours}s {minutes}d kaldı"


@register.filter
def get_item(dictionary, key):
    """Allows dict lookup in templates: {{ my_dict|get_item:key }}"""
    if isinstance(dictionary, dict):
        return dictionary.get(key)
    return None


@register.filter
def text_color(color_code):
    """Return '#fff' or '#111' based on the luminance of the given hex color."""
    try:
        c = color_code.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return "#111" if luminance > 0.55 else "#fff"
    except Exception:
        return "#fff"


@register.filter
def activity_color(activity_type):
    """Returns a Bootstrap badge color class for the given activity type."""
    colors = {
        "training": "primary",
        "analysis": "info",
        "match_watching": "warning",
        "endurance": "success",
        "flexibility": "secondary",
        "other_sport": "light",
        "upper_body": "danger",
        "lower_body_core_hiit": "dark",
        "other_team_frisbee": "primary",
        "hf_disk": "success",
        "tournament": "warning",
    }
    return colors.get(activity_type, "secondary")
