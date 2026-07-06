from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from .models import (
    Activity, Player, PointAdjustment, Season, Tag,
    Team, TeamMembership, WeeklyGoal,
)
from .services import (
    apply_weekly_penalties,
    calculate_points,
    can_player_challenge,
    check_weekly_goals,
    expire_overdue_tags,
    get_current_week_number,
    resolve_tag_on_activity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_season(number=1, days_ago=0, is_active=True):
    start = date.today() - timedelta(days=days_ago)
    return Season.objects.create(
        number=number,
        start_date=start,
        end_date=start + timedelta(days=13),
        is_active=is_active,
    )


def make_player(name="Alice"):
    return Player.objects.create(name=name, is_active=True)


def make_team(season, name="Team A"):
    return Team.objects.create(name=name, season=season)


def make_membership(player, team, season, points=0):
    return TeamMembership.objects.create(
        player=player, team=team, season=season, season_points=points
    )


def make_activity(player, season, activity_type="training", duration=60, points=4,
                  approved=True, created_at=None):
    activity = Activity.objects.create(
        player=player,
        season=season,
        activity_type=activity_type,
        date=date.today(),
        duration_minutes=duration,
        total_points=points,
        is_approved=approved,
    )
    if created_at is not None:
        Activity.objects.filter(pk=activity.pk).update(created_at=created_at)
        activity.refresh_from_db()
    return activity


# ---------------------------------------------------------------------------
# calculate_points
# ---------------------------------------------------------------------------

class CalculatePointsTest(TestCase):

    def test_training_returns_4(self):
        result = calculate_points("training")
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 4)

    def test_analysis_returns_4(self):
        result = calculate_points("analysis")
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 4)

    def test_match_watching_returns_3(self):
        result = calculate_points("match_watching")
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 3)

    def test_other_team_frisbee_returns_2(self):
        result = calculate_points("other_team_frisbee")
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 2)

    def test_lower_body_core_hiit_returns_3(self):
        result = calculate_points("lower_body_core_hiit")
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 3)

    def test_endurance_returns_3(self):
        result = calculate_points("endurance")
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 3)

    def test_upper_body_returns_2(self):
        result = calculate_points("upper_body")
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 2)

    def test_other_sport_returns_1(self):
        result = calculate_points("other_sport")
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 1)

    def test_flexibility_returns_1(self):
        result = calculate_points("flexibility")
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 1)

    # hf_disk: 1 point per 20 minutes
    def test_hf_disk_20_min_returns_1(self):
        result = calculate_points("hf_disk", 20)
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 1)

    def test_hf_disk_60_min_returns_3(self):
        result = calculate_points("hf_disk", 60)
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 3)

    def test_hf_disk_no_duration_invalid(self):
        result = calculate_points("hf_disk", None)
        self.assertFalse(result["valid"])
        self.assertEqual(result["total"], 0)
        self.assertIn("süre", result["error"])

    def test_hf_disk_below_minimum_invalid(self):
        result = calculate_points("hf_disk", 10)
        self.assertFalse(result["valid"])
        self.assertEqual(result["total"], 0)

    def test_match_watching_below_30_min_invalid(self):
        result = calculate_points("match_watching", 20)
        self.assertFalse(result["valid"])
        self.assertEqual(result["total"], 0)

    def test_training_below_45_min_invalid(self):
        result = calculate_points("training", 30)
        self.assertFalse(result["valid"])
        self.assertEqual(result["total"], 0)

    def test_non_hf_disk_without_duration_valid(self):
        # Duration may be omitted for non-hf_disk activities
        result = calculate_points("training", None)
        self.assertTrue(result["valid"])
        self.assertEqual(result["total"], 4)


# ---------------------------------------------------------------------------
# get_current_week_number
# ---------------------------------------------------------------------------

class GetCurrentWeekNumberTest(TestCase):

    def test_first_day_is_week_1(self):
        season = make_season(days_ago=0)
        self.assertEqual(get_current_week_number(season), 1)

    def test_day_6_is_week_1(self):
        season = make_season(days_ago=6)
        self.assertEqual(get_current_week_number(season), 1)

    def test_day_7_is_week_2(self):
        season = make_season(days_ago=7)
        self.assertEqual(get_current_week_number(season), 2)

    def test_day_13_is_week_2(self):
        season = make_season(days_ago=13)
        self.assertEqual(get_current_week_number(season), 2)


# ---------------------------------------------------------------------------
# resolve_tag_on_activity
# ---------------------------------------------------------------------------

class ResolveTagOnActivityTest(TestCase):

    def setUp(self):
        self.season = make_season()
        self.tagger = make_player("Tagger")
        self.tagged = make_player("Tagged")
        team = make_team(self.season)
        make_membership(self.tagger, team, self.season)
        make_membership(self.tagged, team, self.season)

    def _make_pending_tag(self, expires_in_hours=24):
        return Tag.objects.create(
            tagger=self.tagger,
            tagged=self.tagged,
            season=self.season,
            expires_at=timezone.now() + timedelta(hours=expires_in_hours),
            status="pending",
        )

    def test_resolves_pending_tag_with_sufficient_points(self):
        tag = self._make_pending_tag()
        activity = make_activity(self.tagged, self.season, points=4)
        resolve_tag_on_activity(activity)
        tag.refresh_from_db()
        self.assertEqual(tag.status, "responded")
        self.assertTrue(tag.bonus_awarded)

    def test_bonus_point_adjustment_created(self):
        self._make_pending_tag()
        activity = make_activity(self.tagged, self.season, points=4)
        resolve_tag_on_activity(activity)
        adj = PointAdjustment.objects.get(player=self.tagged, reason="tag_bonus")
        self.assertEqual(adj.points, 1)

    def test_does_not_resolve_with_insufficient_points(self):
        tag = self._make_pending_tag()
        activity = make_activity(self.tagged, self.season, points=1)
        resolve_tag_on_activity(activity)
        tag.refresh_from_db()
        self.assertEqual(tag.status, "pending")
        self.assertFalse(tag.bonus_awarded)

    def test_does_not_resolve_expired_tag(self):
        tag = self._make_pending_tag(expires_in_hours=-1)
        activity = make_activity(self.tagged, self.season, points=4)
        resolve_tag_on_activity(activity)
        tag.refresh_from_db()
        self.assertEqual(tag.status, "pending")

    def test_no_pending_tag_does_nothing(self):
        activity = make_activity(self.tagged, self.season, points=4)
        resolve_tag_on_activity(activity)
        self.assertEqual(PointAdjustment.objects.count(), 0)

    def test_resolves_earliest_pending_tag_first(self):
        earlier = self._make_pending_tag()
        later = Tag.objects.create(
            tagger=self.tagger,
            tagged=self.tagged,
            season=self.season,
            expires_at=timezone.now() + timedelta(hours=48),
            status="pending",
        )
        activity = make_activity(self.tagged, self.season, points=4)
        resolve_tag_on_activity(activity)
        earlier.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual(earlier.status, "responded")
        self.assertEqual(later.status, "pending")


# ---------------------------------------------------------------------------
# expire_overdue_tags
# ---------------------------------------------------------------------------

class ExpireOverdueTagsTest(TestCase):

    def setUp(self):
        self.season = make_season()
        self.tagger = make_player("Tagger")
        self.tagged = make_player("Tagged")
        team = make_team(self.season)
        make_membership(self.tagger, team, self.season)
        make_membership(self.tagged, team, self.season)

    def _make_tag(self, status="pending", expired=True):
        expires_at = timezone.now() + timedelta(hours=-1 if expired else 24)
        return Tag.objects.create(
            tagger=self.tagger,
            tagged=self.tagged,
            season=self.season,
            expires_at=expires_at,
            status=status,
        )

    def test_expires_overdue_pending_tag(self):
        tag = self._make_tag(expired=True)
        count = expire_overdue_tags()
        tag.refresh_from_db()
        self.assertEqual(count, 1)
        self.assertEqual(tag.status, "expired")
        self.assertTrue(tag.penalty_applied)

    def test_penalty_applied_to_tagged_player(self):
        self._make_tag(expired=True)
        expire_overdue_tags()
        adj = PointAdjustment.objects.get(player=self.tagged, reason="tag_penalty")
        self.assertEqual(adj.points, -3)

    def test_does_not_expire_active_tag(self):
        tag = self._make_tag(expired=False)
        count = expire_overdue_tags()
        tag.refresh_from_db()
        self.assertEqual(count, 0)
        self.assertEqual(tag.status, "pending")

    def test_does_not_reprocess_already_expired_tag(self):
        self._make_tag(status="expired", expired=True)
        count = expire_overdue_tags()
        self.assertEqual(count, 0)
        self.assertEqual(PointAdjustment.objects.count(), 0)

    def test_returns_correct_count(self):
        self._make_tag(expired=True)
        self._make_tag(expired=True)
        self.assertEqual(expire_overdue_tags(), 2)


# ---------------------------------------------------------------------------
# can_player_challenge
# ---------------------------------------------------------------------------

class CanPlayerChallengeTest(TestCase):

    def setUp(self):
        self.season = make_season()
        self.player = make_player("Alice")
        self.opponent = make_player("Bob")
        team_a = make_team(self.season, "Team A")
        team_b = make_team(self.season, "Team B")
        make_membership(self.player, team_a, self.season)
        make_membership(self.opponent, team_b, self.season)

    def test_can_challenge_after_recent_activity(self):
        make_activity(self.player, self.season,
                      created_at=timezone.now() - timedelta(minutes=10))
        can, _ = can_player_challenge(self.player, self.season)
        self.assertTrue(can)

    def test_cannot_challenge_without_recent_activity(self):
        can, reason = can_player_challenge(self.player, self.season)
        self.assertFalse(can)
        self.assertIn("aktivite", reason)

    def test_cannot_challenge_with_expired_activity_window(self):
        make_activity(self.player, self.season,
                      created_at=timezone.now() - timedelta(minutes=31))
        can, _ = can_player_challenge(self.player, self.season)
        self.assertFalse(can)

    def test_cannot_challenge_with_pending_outgoing_tag(self):
        make_activity(self.player, self.season,
                      created_at=timezone.now() - timedelta(minutes=5))
        Tag.objects.create(
            tagger=self.player, tagged=self.opponent, season=self.season,
            expires_at=timezone.now() + timedelta(hours=48), status="pending",
        )
        can, reason = can_player_challenge(self.player, self.season)
        self.assertFalse(can)
        self.assertIn("meydan okuman var", reason)

    def test_cannot_challenge_with_pending_incoming_tag(self):
        make_activity(self.player, self.season,
                      created_at=timezone.now() - timedelta(minutes=5))
        Tag.objects.create(
            tagger=self.opponent, tagged=self.player, season=self.season,
            expires_at=timezone.now() + timedelta(hours=48), status="pending",
        )
        can, reason = can_player_challenge(self.player, self.season)
        self.assertFalse(can)
        self.assertIn("yanıtlamalısın", reason)

    def test_challenge_right_consumed_after_sending_tag(self):
        activity_time = timezone.now() - timedelta(minutes=5)
        make_activity(self.player, self.season, created_at=activity_time)
        # Send a tag after the activity
        Tag.objects.create(
            tagger=self.player, tagged=self.opponent, season=self.season,
            expires_at=timezone.now() + timedelta(hours=48), status="pending",
            # created_at defaults to now, which is after activity_time
        )
        # There's now a pending outgoing tag → cannot challenge
        can, _ = can_player_challenge(self.player, self.season)
        self.assertFalse(can)


# ---------------------------------------------------------------------------
# check_weekly_goals
# ---------------------------------------------------------------------------

class CheckWeeklyGoalsTest(TestCase):

    def setUp(self):
        self.season = make_season(days_ago=0)
        self.player = make_player()
        team = make_team(self.season)
        make_membership(self.player, team, self.season)

    def test_no_goals_does_nothing(self):
        check_weekly_goals(self.player, self.season, 1)
        self.assertEqual(PointAdjustment.objects.count(), 0)

    def test_awards_bonus_when_activity_type_goal_met(self):
        WeeklyGoal.objects.create(
            season=self.season, week_number=1, description="Train once",
            activity_type="training", required_count=1,
        )
        make_activity(self.player, self.season, activity_type="training")
        check_weekly_goals(self.player, self.season, 1)
        adj = PointAdjustment.objects.get(player=self.player, reason="weekly_goal_bonus")
        self.assertEqual(adj.points, 3)

    def test_no_bonus_when_activity_type_goal_not_met(self):
        WeeklyGoal.objects.create(
            season=self.season, week_number=1, description="Train twice",
            activity_type="training", required_count=2,
        )
        make_activity(self.player, self.season, activity_type="training")
        check_weekly_goals(self.player, self.season, 1)
        self.assertEqual(PointAdjustment.objects.filter(reason="weekly_goal_bonus").count(), 0)

    def test_awards_bonus_when_min_points_goal_met(self):
        WeeklyGoal.objects.create(
            season=self.season, week_number=1, description="Earn 5 pts",
            min_points=5,
        )
        make_activity(self.player, self.season, points=6)
        check_weekly_goals(self.player, self.season, 1)
        adj = PointAdjustment.objects.get(reason="weekly_goal_bonus")
        self.assertEqual(adj.points, 3)

    def test_no_bonus_when_min_points_goal_not_met(self):
        WeeklyGoal.objects.create(
            season=self.season, week_number=1, description="Earn 10 pts",
            min_points=10,
        )
        make_activity(self.player, self.season, points=4)
        check_weekly_goals(self.player, self.season, 1)
        self.assertEqual(PointAdjustment.objects.filter(reason="weekly_goal_bonus").count(), 0)

    def test_bonus_awarded_only_once(self):
        WeeklyGoal.objects.create(
            season=self.season, week_number=1, description="Train once",
            activity_type="training", required_count=1,
        )
        make_activity(self.player, self.season, activity_type="training")
        check_weekly_goals(self.player, self.season, 1)
        check_weekly_goals(self.player, self.season, 1)
        self.assertEqual(PointAdjustment.objects.filter(reason="weekly_goal_bonus").count(), 1)


# ---------------------------------------------------------------------------
# apply_weekly_penalties
# ---------------------------------------------------------------------------

class ApplyWeeklyPenaltiesTest(TestCase):

    def setUp(self):
        self.season = make_season(days_ago=0)
        self.player = make_player()
        team = make_team(self.season)
        make_membership(self.player, team, self.season)

    def test_penalty_applied_when_under_10_points(self):
        make_activity(self.player, self.season, points=5)
        apply_weekly_penalties(self.season, 1)
        adj = PointAdjustment.objects.get(player=self.player, reason="weekly_penalty")
        self.assertEqual(adj.points, -3)

    def test_no_penalty_when_at_least_10_points(self):
        make_activity(self.player, self.season, points=10)
        apply_weekly_penalties(self.season, 1)
        self.assertEqual(PointAdjustment.objects.filter(reason="weekly_penalty").count(), 0)

    def test_no_penalty_exactly_10_points(self):
        make_activity(self.player, self.season, points=4)
        make_activity(self.player, self.season, points=6)
        apply_weekly_penalties(self.season, 1)
        self.assertEqual(PointAdjustment.objects.filter(reason="weekly_penalty").count(), 0)

    def test_penalty_applied_only_once_per_player_per_week(self):
        make_activity(self.player, self.season, points=3)
        apply_weekly_penalties(self.season, 1)
        apply_weekly_penalties(self.season, 1)
        self.assertEqual(PointAdjustment.objects.filter(reason="weekly_penalty").count(), 1)

    def test_penalty_counts_adjustments_in_week_total(self):
        # Player has 8 activity pts + 3 tag bonus = 11 total → no penalty
        make_activity(self.player, self.season, points=8)
        PointAdjustment.objects.create(
            player=self.player, season=self.season,
            reason="tag_bonus", points=3, week_number=1,
        )
        apply_weekly_penalties(self.season, 1)
        self.assertEqual(PointAdjustment.objects.filter(reason="weekly_penalty").count(), 0)

    def test_unapproved_activities_not_counted(self):
        make_activity(self.player, self.season, points=12, approved=False)
        apply_weekly_penalties(self.season, 1)
        self.assertEqual(PointAdjustment.objects.filter(reason="weekly_penalty").count(), 1)


# ---------------------------------------------------------------------------
# tag_player view — target restriction
# ---------------------------------------------------------------------------

class TagPlayerViewTargetTest(TestCase):
    def setUp(self):
        self.season = make_season()
        self.team_a = make_team(self.season, "Team A")
        self.team_b = make_team(self.season, "Team B")
        self.me = make_player("Me")
        self.teammate = make_player("Teammate")
        self.opponent = make_player("Opponent")
        make_membership(self.me, self.team_a, self.season)
        make_membership(self.teammate, self.team_a, self.season)
        make_membership(self.opponent, self.team_b, self.season)
        # Earn the 30-minute challenge window
        make_activity(self.me, self.season, points=4)
        session = self.client.session
        session["player_id"] = self.me.pk
        session.save()

    def test_can_tag_opponent(self):
        self.client.post("/meydan-oku/", {"tagged_player_id": self.opponent.pk})
        self.assertTrue(Tag.objects.filter(tagger=self.me, tagged=self.opponent).exists())

    def test_cannot_tag_teammate(self):
        self.client.post("/meydan-oku/", {"tagged_player_id": self.teammate.pk})
        self.assertFalse(Tag.objects.exists())

    def test_cannot_tag_self(self):
        self.client.post("/meydan-oku/", {"tagged_player_id": self.me.pk})
        self.assertFalse(Tag.objects.exists())
