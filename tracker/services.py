"""
All business logic for SportTracker.
"""
from datetime import timedelta

from django.db import models as db_models
from django.utils import timezone

from .models import (
    Activity, PointAdjustment, Season, Tag, TeamMembership,
    WeeklyGoal, Player, BASE_POINTS, MIN_DURATION,
)


# ---------------------------------------------------------------------------
# Points calculation
# ---------------------------------------------------------------------------

def calculate_points(activity_type: str, duration_minutes: int | None = None) -> dict:
    """
    Returns a dict with keys: valid (bool), total (int), error (str).

    For hf_disk: points = duration_minutes // 20  (duration-based).
    For all others: points = fixed BASE_POINTS value (no duration bonus).
    Non-HF activities may omit duration; in that case the minimum duration is
    assumed automatically.
    """
    if activity_type == "hf_disk":
        if duration_minutes is None:
            return {"valid": False, "total": 0, "error": "HF Disk için süre girmen gerekli."}
        min_dur = MIN_DURATION.get(activity_type, 20)
        if duration_minutes < min_dur:
            return {"valid": False, "total": 0, "error": f"Minimum süre {min_dur} dakikadır."}
        total = duration_minutes // 20
        return {"valid": True, "total": total, "error": ""}

    min_dur = MIN_DURATION.get(activity_type, 45)
    if duration_minutes is not None and duration_minutes < min_dur:
        return {"valid": False, "total": 0, "error": f"Minimum süre {min_dur} dakikadır."}

    total = BASE_POINTS.get(activity_type, 0)
    return {"valid": True, "total": total, "error": ""}


# ---------------------------------------------------------------------------
# Season week helpers
# ---------------------------------------------------------------------------

def get_current_week_number(season: Season) -> int:
    """Returns 1 or 2 depending on how far we are into the season."""
    from datetime import date
    today = date.today()
    delta = (today - season.start_date).days
    return 1 if delta < 7 else 2


# ---------------------------------------------------------------------------
# Point sync helpers
# ---------------------------------------------------------------------------

def _update_season_points(player: Player, season: Season, delta: int):
    """Atomically update TeamMembership.season_points and Player.total_points."""
    TeamMembership.objects.filter(player=player, season=season).update(
        season_points=db_models.F("season_points") + delta
    )
    Player.objects.filter(pk=player.pk).update(
        total_points=db_models.F("total_points") + delta
    )


# ---------------------------------------------------------------------------
# Tag resolution
# ---------------------------------------------------------------------------

def resolve_tag_on_activity(activity: Activity):
    """
    After an activity is saved, check if the player has a pending tag.
    If the activity earns >= 2 points, mark the tag as responded and award +1.
    """
    now = timezone.now()
    pending_tag = (
        Tag.objects.filter(
            tagged=activity.player,
            status="pending",
            expires_at__gt=now,
        )
        .order_by("created_at")
        .first()
    )

    if pending_tag and activity.total_points >= 2:
        pending_tag.status = "responded"
        pending_tag.responding_activity = activity
        pending_tag.bonus_awarded = True
        pending_tag.save()

        PointAdjustment.objects.create(
            player=activity.player,
            season=activity.season,
            reason="tag_bonus",
            points=+1,
            description=f"{pending_tag.tagger.name} meydan okumasına yanıt bonusu",
            related_tag=pending_tag,
        )
        _update_season_points(activity.player, activity.season, +1)


def expire_overdue_tags() -> int:
    """
    Find all pending tags past expires_at and apply -3 penalty to the tagged player.
    Returns the count of tags expired.
    """
    now = timezone.now()
    overdue = Tag.objects.filter(status="pending", expires_at__lte=now)
    count = 0
    for tag in overdue:
        tag.status = "expired"
        tag.penalty_applied = True
        tag.save()

        week_number = get_current_week_number(tag.season)
        PointAdjustment.objects.create(
            player=tag.tagged,
            season=tag.season,
            reason="tag_penalty",
            points=-3,
            description=f"{tag.tagger.name} meydan okuma cezası",
            related_tag=tag,
            week_number=week_number,
        )
        _update_season_points(tag.tagged, tag.season, -3)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Challenge eligibility
# ---------------------------------------------------------------------------

def can_player_challenge(player: Player, season: Season) -> tuple:
    """
    Returns (can_challenge: bool, reason: str).

    A player earns a 30-minute challenge window the moment they log an
    approved activity (or respond to an incoming challenge, which also
    requires logging an activity).  The window is consumed as soon as they
    send a challenge, so the same activity cannot be used twice.

    Conditions:
    1. No pending outgoing tag.
    2. No pending incoming tag (must respond first).
    3. An approved activity exists within the last 30 minutes, and no
       challenge has been sent after that activity.
    """
    if Tag.objects.filter(tagger=player, season=season, status="pending").exists():
        return False, "Bekleyen bir meydan okuman var."

    if Tag.objects.filter(tagged=player, season=season, status="pending").exists():
        return False, "Önce gelen meydan okumayı yanıtlamalısın."

    window_start = timezone.now() - timedelta(minutes=30)
    recent_activity = (
        Activity.objects.filter(
            player=player, season=season, is_approved=True,
            created_at__gte=window_start,
        )
        .order_by("-created_at")
        .first()
    )

    if not recent_activity:
        return False, "Meydan okuma hakkın yok – aktivite kaydettikten sonra 30 dakikan olur."

    # Right is consumed the moment a challenge is sent after this activity.
    already_used = Tag.objects.filter(
        tagger=player, season=season,
        created_at__gt=recent_activity.created_at,
    ).exists()
    if already_used:
        return False, "Bu aktivite için meydan okuma hakkını zaten kullandın."

    return True, ""


# ---------------------------------------------------------------------------
# Weekly goals
# ---------------------------------------------------------------------------

def check_weekly_goals(player: Player, season: Season, week_number: int):
    """
    After any activity: if ALL weekly goals are met and the bonus hasn't been
    awarded yet, create a +3 PointAdjustment.
    """
    goals = WeeklyGoal.objects.filter(season=season, week_number=week_number)
    if not goals.exists():
        return

    week_start = season.start_date + timedelta(weeks=week_number - 1)
    week_end = week_start + timedelta(days=6)

    for goal in goals:
        if goal.activity_type:
            count = Activity.objects.filter(
                player=player,
                season=season,
                is_approved=True,
                activity_type=goal.activity_type,
                date__gte=week_start,
                date__lte=week_end,
            ).count()
            if count < goal.required_count:
                return
        elif goal.min_points:
            pts = (
                Activity.objects.filter(
                    player=player,
                    season=season,
                    is_approved=True,
                    date__gte=week_start,
                    date__lte=week_end,
                ).aggregate(t=db_models.Sum("total_points"))["t"]
                or 0
            )
            if pts < goal.min_points:
                return

    # All goals met
    already = PointAdjustment.objects.filter(
        player=player,
        season=season,
        reason="weekly_goal_bonus",
        week_number=week_number,
    ).exists()
    if not already:
        PointAdjustment.objects.create(
            player=player,
            season=season,
            reason="weekly_goal_bonus",
            points=+3,
            description=f"Hafta {week_number} tüm hedefler tamamlandı",
            week_number=week_number,
        )
        _update_season_points(player, season, +3)


# ---------------------------------------------------------------------------
# Weekly penalties
# ---------------------------------------------------------------------------

def apply_weekly_penalties(season: Season, week_number: int):
    """
    For every player in the season, check if their total week points < 10.
    If so, apply a -3 penalty (only once per week per player).
    """
    week_start = season.start_date + timedelta(weeks=week_number - 1)
    week_end = week_start + timedelta(days=6)

    memberships = TeamMembership.objects.filter(season=season).select_related("player")

    for membership in memberships:
        player = membership.player

        already = PointAdjustment.objects.filter(
            player=player,
            season=season,
            reason="weekly_penalty",
            week_number=week_number,
        ).exists()
        if already:
            continue

        activity_pts = (
            Activity.objects.filter(
                player=player,
                season=season,
                is_approved=True,
                date__gte=week_start,
                date__lte=week_end,
            ).aggregate(total=db_models.Sum("total_points"))["total"]
            or 0
        )

        adjustment_pts = (
            PointAdjustment.objects.filter(
                player=player,
                season=season,
                week_number=week_number,
            )
            .exclude(reason="weekly_penalty")
            .aggregate(total=db_models.Sum("points"))["total"]
            or 0
        )

        week_total = activity_pts + adjustment_pts

        if week_total < 10:
            PointAdjustment.objects.create(
                player=player,
                season=season,
                reason="weekly_penalty",
                points=-3,
                description=f"Hafta {week_number}: {week_total} puan (10 puan altı cezası)",
                week_number=week_number,
            )
            _update_season_points(player, season, -3)


# ---------------------------------------------------------------------------
# Season close
# ---------------------------------------------------------------------------

def close_season(season: Season):
    """
    Closes the season: determines winning team, marks season inactive,
    returns top-2 players as suggested captains for next season.
    """
    from django.db.models import Sum

    team_totals = (
        TeamMembership.objects.filter(season=season)
        .values("team")
        .annotate(pts=Sum("season_points"))
        .order_by("-pts")
    )

    if team_totals:
        season.winner_team_id = team_totals[0]["team"]
    season.is_active = False
    season.save()

    top_two = TeamMembership.objects.filter(season=season).order_by("-season_points")[:2]
    return [m.player for m in top_two]
