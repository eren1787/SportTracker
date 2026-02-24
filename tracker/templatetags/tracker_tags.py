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
    }
    return colors.get(activity_type, "secondary")
