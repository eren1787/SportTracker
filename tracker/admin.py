from django.contrib import admin
from django.template.response import TemplateResponse
from .models import (
    Season, Player, Team, TeamMembership,
    WeeklyGoal, Activity, Tag, PointAdjustment,
)


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin):
    list_display = ["number", "start_date", "end_date", "is_active", "winner_team"]
    list_editable = ["is_active"]
    actions = ["close_season_action"]

    def close_season_action(self, request, queryset):
        from .services import close_season
        for season in queryset:
            captains = close_season(season)
            names = ", ".join(c.name for c in captains) if captains else "—"
            self.message_user(
                request,
                f"Sezon {season.number} kapatıldı. Önerilen yeni kaptanlar: {names}",
            )
    close_season_action.short_description = "Sezonları Kapat ve Kazananı Belirle"


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "total_points", "joined_date"]
    list_editable = ["is_active"]
    search_fields = ["name"]
    actions = ["assign_to_team"]

    def assign_to_team(self, request, queryset):
        # Second step: form submitted with 'apply' button
        if "apply" in request.POST:
            team_id = request.POST.get("team")
            season_id = request.POST.get("season")
            player_ids = request.POST.getlist("player_ids")

            try:
                team = Team.objects.get(pk=team_id)
                season = Season.objects.get(pk=season_id)
            except (Team.DoesNotExist, Season.DoesNotExist):
                self.message_user(request, "Geçersiz takım veya sezon seçimi.", level="error")
                return

            players = Player.objects.filter(pk__in=player_ids)
            created = updated = 0
            for player in players:
                obj, was_created = TeamMembership.objects.get_or_create(
                    player=player,
                    season=season,
                    defaults={"team": team},
                )
                if was_created:
                    created += 1
                else:
                    obj.team = team
                    obj.save()
                    updated += 1

            self.message_user(
                request,
                f"{created} yeni üyelik oluşturuldu, {updated} üyelik güncellendi → {team.name}.",
            )
            return

        # First step: render intermediate selection page
        return TemplateResponse(
            request,
            "admin/tracker/player/assign_team.html",
            {
                "players": queryset,
                "seasons": Season.objects.all(),
                "teams": Team.objects.select_related("season").order_by("season", "name"),
                "opts": self.model._meta,
                "title": "Takıma Ata",
            },
        )

    assign_to_team.short_description = "Seçili oyuncuları takıma ata"


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "season", "captain", "color_code"]
    list_filter = ["season"]


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ["player", "team", "season", "season_points"]
    list_filter = ["season", "team"]


@admin.register(WeeklyGoal)
class WeeklyGoalAdmin(admin.ModelAdmin):
    list_display = ["season", "week_number", "description", "activity_type", "required_count", "min_points"]
    list_filter = ["season", "week_number"]


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ["player", "activity_type", "date", "duration_minutes", "total_points", "is_approved", "season"]
    list_filter = ["season", "activity_type", "is_approved"]
    list_editable = ["is_approved"]
    search_fields = ["player__name"]
    date_hierarchy = "date"


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["tagger", "tagged", "season", "status", "created_at", "expires_at", "bonus_awarded", "penalty_applied"]
    list_filter = ["season", "status"]
    readonly_fields = ["created_at"]


@admin.register(PointAdjustment)
class PointAdjustmentAdmin(admin.ModelAdmin):
    list_display = ["player", "season", "reason", "points", "week_number", "created_at"]
    list_filter = ["season", "reason"]
    search_fields = ["player__name"]
