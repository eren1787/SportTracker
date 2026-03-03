from django.contrib import admin
from django import forms
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


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    # Only expose the player; season is auto-filled from the team on save
    fields = ["player", "season_points"]
    autocomplete_fields = ["player"]
    extra = 8  # empty rows ready to fill in one go

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("player")


class TeamAdminForm(forms.ModelForm):
    color_code = forms.ChoiceField(
        choices=Team.COLOR_CHOICES,
        widget=forms.RadioSelect,
        label="Renk",
    )

    class Meta:
        model = Team
        fields = "__all__"


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    form = TeamAdminForm
    list_display = ["name", "season", "captain", "color_code"]
    list_filter = ["season"]
    inlines = [TeamMembershipInline]

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, TeamMembership) and not instance.season_id:
                # Auto-populate season from the parent team
                instance.season = instance.team.season
            instance.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ["player", "team", "season", "season_points"]
    list_filter = ["season", "team"]
    search_fields = ["player__name"]


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

    def delete_model(self, request, obj):
        from .services import _update_season_points
        _update_season_points(obj.player, obj.season, -obj.total_points)
        obj.delete()

    def delete_queryset(self, request, queryset):
        from .services import _update_season_points
        for activity in queryset.select_related("player", "season"):
            _update_season_points(activity.player, activity.season, -activity.total_points)
        queryset.delete()


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
