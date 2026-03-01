from datetime import timedelta, date

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Sum, Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ActivityForm, PlayerSignupForm
from .models import (
    Activity, Player, PointAdjustment, Season, Tag,
    Team, TeamMembership, WeeklyGoal, ACTIVITY_CHOICES, MIN_DURATION,
)
from .services import (
    calculate_points, can_player_challenge, check_weekly_goals,
    expire_overdue_tags, get_current_week_number, resolve_tag_on_activity,
    _update_season_points,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_player(request):
    """Return the logged-in Player or None."""
    player_id = request.session.get("player_id")
    if not player_id:
        return None
    try:
        return Player.objects.get(pk=player_id, is_active=True)
    except Player.DoesNotExist:
        return None


def _require_login(request):
    """Return a redirect response if not logged in, else None."""
    if not request.session.get("player_id"):
        return redirect("login")
    return None


def _get_active_season():
    return Season.objects.filter(is_active=True).first()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def login_view(request):
    if request.method == "POST":
        player_id = request.POST.get("player_id")
        try:
            player = Player.objects.get(pk=player_id, is_active=True)
            request.session["player_id"] = player.pk
            return redirect("dashboard")
        except Player.DoesNotExist:
            messages.error(request, "Geçersiz oyuncu seçimi.")

    players = Player.objects.filter(is_active=True).order_by("name")
    return render(request, "tracker/login.html", {"players": players})



def signup_view(request):
    form = PlayerSignupForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        player = Player.objects.create(name=form.cleaned_data["name"], is_active=True)
        request.session["player_id"] = player.pk
        messages.success(request, "Kayıt oluşturuldu. Hoş geldin!")
        return redirect("dashboard")

    return render(request, "tracker/signup.html", {"form": form})


def logout_view(request):
    request.session.flush()
    return redirect("login")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def dashboard(request):
    redir = _require_login(request)
    if redir:
        return redir

    player = _get_player(request)
    season = _get_active_season()

    membership = None
    week_points = 0
    recent_feed = []
    pending_tags_in = []
    pending_tags_out = []
    weekly_goals = []
    goals_status = {}
    team_standings = []
    current_week = 1

    if season:
        expire_overdue_tags()  # auto-expire on every dashboard load

        membership = TeamMembership.objects.filter(player=player, season=season).first()
        current_week = get_current_week_number(season)
        week_start = season.start_date + timedelta(weeks=current_week - 1)
        week_end = week_start + timedelta(days=6)

        activity_pts = (
            Activity.objects.filter(
                player=player, season=season, is_approved=True,
                date__gte=week_start, date__lte=week_end,
            ).aggregate(t=Sum("total_points"))["t"] or 0
        )
        adjustment_pts = (
            PointAdjustment.objects.filter(
                player=player, season=season, week_number=current_week,
            ).aggregate(t=Sum("points"))["t"] or 0
        )
        week_points = activity_pts + adjustment_pts

        # Build combined recent feed: own activities + adjustments + tags + opponent activities
        _STATUS_TR = {"pending": "Bekliyor", "responded": "Yanıtlandı", "expired": "Süresi Doldu"}

        raw_activities = list(
            Activity.objects.filter(player=player, season=season)
            .order_by("-created_at")[:12]
        )
        raw_adjustments = list(
            PointAdjustment.objects.filter(player=player, season=season)
            .order_by("-created_at")[:10]
        )
        raw_tags_sent = list(
            Tag.objects.filter(tagger=player, season=season)
            .select_related("tagged")
            .order_by("-created_at")[:8]
        )
        raw_tags_received = list(
            Tag.objects.filter(tagged=player, season=season)
            .select_related("tagger")
            .order_by("-created_at")[:8]
        )

        feed = []
        for a in raw_activities:
            feed.append({
                "kind": "activity",
                "timestamp": a.created_at,
                "date": a.date,
                "label": a.get_activity_type_display(),
                "points": a.total_points,
                "activity_type": a.activity_type,
                "player_name": None,
                "player_id": None,
            })
        for adj in raw_adjustments:
            feed.append({
                "kind": "adjustment",
                "timestamp": adj.created_at,
                "date": adj.created_at.date(),
                "label": adj.get_reason_display(),
                "points": adj.points,
                "activity_type": None,
                "player_name": None,
                "player_id": None,
            })
        for tag in raw_tags_sent:
            feed.append({
                "kind": "tag_sent",
                "timestamp": tag.created_at,
                "date": tag.created_at.date(),
                "label": f"{tag.tagged.name}'e meydan okudun",
                "status_label": _STATUS_TR.get(tag.status, tag.status),
                "points": None,
                "activity_type": None,
                "player_name": tag.tagged.name,
                "player_id": tag.tagged.pk,
            })
        for tag in raw_tags_received:
            feed.append({
                "kind": "tag_received",
                "timestamp": tag.created_at,
                "date": tag.created_at.date(),
                "label": f"{tag.tagger.name} sana meydan okudu",
                "status_label": _STATUS_TR.get(tag.status, tag.status),
                "points": None,
                "activity_type": None,
                "player_name": tag.tagger.name,
                "player_id": tag.tagger.pk,
            })

        # Opponent activities
        if membership:
            opp_player_ids = list(
                TeamMembership.objects.filter(season=season)
                .exclude(team=membership.team)
                .values_list("player_id", flat=True)
            )
            for a in Activity.objects.filter(
                player_id__in=opp_player_ids, season=season, is_approved=True
            ).select_related("player").order_by("-created_at")[:12]:
                feed.append({
                    "kind": "opponent_activity",
                    "timestamp": a.created_at,
                    "date": a.date,
                    "label": a.get_activity_type_display(),
                    "points": a.total_points,
                    "activity_type": a.activity_type,
                    "player_name": a.player.name,
                    "player_id": a.player.pk,
                })

        feed.sort(key=lambda x: x["timestamp"], reverse=True)
        recent_feed = feed[:12]

        now = timezone.now()
        pending_tags_in = Tag.objects.filter(
            tagged=player, season=season, status="pending"
        ).select_related("tagger")
        pending_tags_out = Tag.objects.filter(
            tagger=player, season=season, status="pending"
        ).select_related("tagged")

        # Challenge right indicator for the dashboard button
        can_tag, _ = can_player_challenge(player, season)
        challenge_expires_at = None
        if can_tag:
            window_start = now - timedelta(minutes=30)
            last_sent = (
                Tag.objects.filter(tagger=player, season=season)
                .order_by("-created_at").first()
            )
            qs = Activity.objects.filter(
                player=player, season=season, is_approved=True,
                created_at__gte=window_start,
            )
            if last_sent:
                qs = qs.filter(created_at__gt=last_sent.created_at)
            qualifying = qs.order_by("-created_at").first()
            if qualifying:
                challenge_expires_at = qualifying.created_at + timedelta(minutes=30)

        weekly_goals = WeeklyGoal.objects.filter(season=season, week_number=current_week)
        for goal in weekly_goals:
            if goal.activity_type:
                count = Activity.objects.filter(
                    player=player, season=season, is_approved=True,
                    activity_type=goal.activity_type,
                    date__gte=week_start, date__lte=week_end,
                ).count()
                goals_status[goal.pk] = count >= goal.required_count
            elif goal.min_points:
                pts = (
                    Activity.objects.filter(
                        player=player, season=season, is_approved=True,
                        date__gte=week_start, date__lte=week_end,
                    ).aggregate(t=Sum("total_points"))["t"] or 0
                )
                goals_status[goal.pk] = pts >= goal.min_points

        # Team standings
        teams = Team.objects.filter(season=season).prefetch_related(
            Prefetch(
                "memberships",
                queryset=TeamMembership.objects.select_related("player").order_by("-season_points"),
            )
        )
        team_standings = []
        for team in teams:
            total = team.memberships.aggregate(s=Sum("season_points"))["s"] or 0
            team_standings.append({"team": team, "total": total, "members": list(team.memberships.all())})

    return render(request, "tracker/dashboard.html", {
        "player": player,
        "season": season,
        "membership": membership,
        "week_points": week_points,
        "current_week": current_week,
        "recent_feed": recent_feed,
        "pending_tags_in": pending_tags_in,
        "pending_tags_out": pending_tags_out,
        "weekly_goals": weekly_goals,
        "goals_status": goals_status,
        "team_standings": team_standings,
        "can_tag": can_tag,
        "challenge_expires_at": challenge_expires_at,
    })


# ---------------------------------------------------------------------------
# Log Activity
# ---------------------------------------------------------------------------

def log_activity(request):
    redir = _require_login(request)
    if redir:
        return redir

    player = _get_player(request)
    season = _get_active_season()

    if not season:
        messages.error(request, "Şu an aktif bir sezon bulunmuyor.")
        return redirect("dashboard")

    form = ActivityForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        activity_type = form.cleaned_data["activity_type"]
        raw_duration = form.cleaned_data.get("duration_minutes")
        duration = raw_duration if activity_type == "hf_disk" else MIN_DURATION.get(activity_type, 45)
        result = calculate_points(activity_type, duration)

        if not result["valid"]:
            form.add_error("duration_minutes", result["error"])
        else:
            activity = Activity.objects.create(
                player=player,
                season=season,
                activity_type=activity_type,
                date=date.today(),
                duration_minutes=duration,
                notes=form.cleaned_data.get("notes", ""),
                total_points=result["total"],
            )
            _update_season_points(player, season, result["total"])
            resolve_tag_on_activity(activity)
            week_number = get_current_week_number(season)
            check_weekly_goals(player, season, week_number)
            messages.success(request, f"Aktivite kaydedildi! +{result['total']} puan kazandın.")
            # Give the player their 30-minute challenge window immediately.
            can_tag, _ = can_player_challenge(player, season)
            if can_tag:
                return redirect("tag_player")
            return redirect("dashboard")

    return render(request, "tracker/activity_log.html", {"form": form, "season": season})


# ---------------------------------------------------------------------------
# Activity List
# ---------------------------------------------------------------------------

def activity_list(request):
    redir = _require_login(request)
    if redir:
        return redir

    player = _get_player(request)
    qs = Activity.objects.filter(player=player).select_related("season").order_by("-date", "-created_at")

    # Optional filters
    season_filter = request.GET.get("season")
    type_filter = request.GET.get("type")
    if season_filter:
        qs = qs.filter(season__number=season_filter)
    if type_filter:
        qs = qs.filter(activity_type=type_filter)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    seasons = Season.objects.all().order_by("-number")
    return render(request, "tracker/activity_list.html", {
        "page_obj": page_obj,
        "seasons": seasons,
        "activity_choices": ACTIVITY_CHOICES,
        "season_filter": season_filter,
        "type_filter": type_filter,
    })


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def leaderboard(request):
    redir = _require_login(request)
    if redir:
        return redir

    season = _get_active_season()
    team_standings = []

    if season:
        teams = Team.objects.filter(season=season).prefetch_related(
            Prefetch(
                "memberships",
                queryset=TeamMembership.objects.select_related("player").order_by("-season_points"),
            )
        )
        for team in teams:
            total = team.memberships.aggregate(s=Sum("season_points"))["s"] or 0
            team_standings.append({"team": team, "total": total, "members": list(team.memberships.all())})

    past_seasons = Season.objects.filter(is_active=False).order_by("-number")[:5]
    return render(request, "tracker/leaderboard.html", {
        "season": season,
        "team_standings": team_standings,
        "past_seasons": past_seasons,
    })


# ---------------------------------------------------------------------------
# Tag Player
# ---------------------------------------------------------------------------

def tag_player(request):
    redir = _require_login(request)
    if redir:
        return redir

    player = _get_player(request)
    season = _get_active_season()

    if not season:
        messages.error(request, "Şu an aktif bir sezon bulunmuyor.")
        return redirect("dashboard")

    membership = TeamMembership.objects.filter(player=player, season=season).first()
    if not membership:
        messages.error(request, "Bu sezonda bir takımda değilsin.")
        return redirect("dashboard")

    other_team = Team.objects.filter(season=season).exclude(pk=membership.team.pk).first()
    if not other_team:
        messages.error(request, "Rakip takım bulunamadı.")
        return redirect("dashboard")

    can_tag, no_tag_reason = can_player_challenge(player, season)

    now = timezone.now()

    # Compute when the 30-minute challenge window expires (for the countdown).
    challenge_expires_at = None
    if can_tag:
        window_start = now - timedelta(minutes=30)
        last_sent = (
            Tag.objects.filter(tagger=player, season=season)
            .order_by("-created_at")
            .first()
        )
        qs = Activity.objects.filter(
            player=player, season=season, is_approved=True, created_at__gte=window_start,
        )
        if last_sent:
            qs = qs.filter(created_at__gt=last_sent.created_at)
        qualifying = qs.order_by("-created_at").first()
        if qualifying:
            challenge_expires_at = qualifying.created_at + timedelta(minutes=30)

    # Opponents who already have a pending tag in the last 48h (can't be targeted again)
    recently_tagged_ids = Tag.objects.filter(
        season=season,
        status__in=["pending", "responded"],
        created_at__gte=now - timedelta(hours=48),
    ).values_list("tagged_id", flat=True)

    opponents = TeamMembership.objects.filter(
        team=other_team, season=season
    ).select_related("player")

    taggable = opponents.exclude(player_id__in=recently_tagged_ids)
    not_taggable = opponents.filter(player_id__in=recently_tagged_ids)

    if request.method == "POST":
        # Re-check eligibility server-side
        if not can_tag:
            messages.error(request, no_tag_reason)
            return redirect("tag_player")

        tagged_player_id = request.POST.get("tagged_player_id")
        try:
            tagged_player = Player.objects.get(pk=tagged_player_id)
        except Player.DoesNotExist:
            messages.error(request, "Oyuncu bulunamadı.")
            return redirect("tag_player")

        if int(tagged_player_id) in list(recently_tagged_ids):
            messages.error(request, "Bu oyuncu zaten meydan okunmuş durumda (48 saat beklenmeli).")
            return redirect("tag_player")

        Tag.objects.create(
            tagger=player,
            tagged=tagged_player,
            season=season,
            expires_at=now + timedelta(hours=48),
        )
        messages.success(request, f"{tagged_player.name} meydan okundu! 48 saat içinde yanıt vermeli.")
        return redirect("tag_list")

    return render(request, "tracker/tag_player.html", {
        "can_tag": can_tag,
        "no_tag_reason": no_tag_reason,
        "challenge_expires_at": challenge_expires_at,
        "taggable": taggable,
        "not_taggable": not_taggable,
        "other_team": other_team,
    })


# ---------------------------------------------------------------------------
# Tag List
# ---------------------------------------------------------------------------

def tag_list(request):
    redir = _require_login(request)
    if redir:
        return redir

    player = _get_player(request)
    expire_overdue_tags()  # auto-expire on every tag list load
    now = timezone.now()

    incoming = Tag.objects.filter(tagged=player).select_related("tagger", "season").order_by("-created_at")
    outgoing = Tag.objects.filter(tagger=player).select_related("tagged", "season").order_by("-created_at")

    return render(request, "tracker/tag_list.html", {
        "incoming": incoming,
        "outgoing": outgoing,
        "now": now,
    })


# ---------------------------------------------------------------------------
# Season Detail
# ---------------------------------------------------------------------------

def season_detail(request, pk):
    redir = _require_login(request)
    if redir:
        return redir

    season = get_object_or_404(Season, pk=pk)
    teams = Team.objects.filter(season=season).prefetch_related(
        Prefetch(
            "memberships",
            queryset=TeamMembership.objects.select_related("player").order_by("-season_points"),
        )
    )
    team_data = []
    for team in teams:
        total = team.memberships.aggregate(s=Sum("season_points"))["s"] or 0
        team_data.append({"team": team, "total": total, "members": list(team.memberships.all())})

    tags = Tag.objects.filter(season=season).select_related("tagger", "tagged").order_by("-created_at")

    return render(request, "tracker/season_detail.html", {
        "season": season,
        "team_data": team_data,
        "tags": tags,
    })


# ---------------------------------------------------------------------------
# Weekly Goals
# ---------------------------------------------------------------------------

def weekly_goals(request):
    redir = _require_login(request)
    if redir:
        return redir

    player = _get_player(request)
    season = _get_active_season()

    if not season:
        return render(request, "tracker/weekly_goals.html", {"season": None})

    current_week = get_current_week_number(season)
    week_start = season.start_date + timedelta(weeks=current_week - 1)
    week_end = week_start + timedelta(days=6)

    goals = WeeklyGoal.objects.filter(season=season, week_number=current_week)
    goals_status = {}
    goals_progress = {}

    for goal in goals:
        if goal.activity_type:
            count = Activity.objects.filter(
                player=player, season=season, is_approved=True,
                activity_type=goal.activity_type,
                date__gte=week_start, date__lte=week_end,
            ).count()
            goals_progress[goal.pk] = {"current": count, "required": goal.required_count}
            goals_status[goal.pk] = count >= goal.required_count
        elif goal.min_points:
            pts = (
                Activity.objects.filter(
                    player=player, season=season, is_approved=True,
                    date__gte=week_start, date__lte=week_end,
                ).aggregate(t=Sum("total_points"))["t"] or 0
            )
            goals_progress[goal.pk] = {"current": pts, "required": goal.min_points}
            goals_status[goal.pk] = pts >= goal.min_points

    week_pts = (
        Activity.objects.filter(
            player=player, season=season, is_approved=True,
            date__gte=week_start, date__lte=week_end,
        ).aggregate(t=Sum("total_points"))["t"] or 0
    )

    return render(request, "tracker/weekly_goals.html", {
        "season": season,
        "current_week": current_week,
        "goals": goals,
        "goals_status": goals_status,
        "goals_progress": goals_progress,
        "week_pts": week_pts,
        "week_start": week_start,
        "week_end": week_end,
    })


# ---------------------------------------------------------------------------
# Player Profile
# ---------------------------------------------------------------------------

def player_profile(request, pk):
    redir = _require_login(request)
    if redir:
        return redir

    target = get_object_or_404(Player, pk=pk, is_active=True)
    memberships = TeamMembership.objects.filter(player=target).select_related("season", "team").order_by("-season__number")
    recent_activities = Activity.objects.filter(player=target).order_by("-date", "-created_at")[:20]
    tags_sent = Tag.objects.filter(tagger=target).select_related("tagged", "season").order_by("-created_at")[:10]
    tags_received = Tag.objects.filter(tagged=target).select_related("tagger", "season").order_by("-created_at")[:10]

    return render(request, "tracker/profile.html", {
        "target": target,
        "memberships": memberships,
        "recent_activities": recent_activities,
        "tags_sent": tags_sent,
        "tags_received": tags_received,
    })
