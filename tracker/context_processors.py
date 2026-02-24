from .models import Player


def current_player(request):
    player_id = request.session.get("player_id")
    if player_id:
        try:
            player = Player.objects.get(pk=player_id, is_active=True)
            return {"current_player": player}
        except Player.DoesNotExist:
            pass
    return {"current_player": None}
