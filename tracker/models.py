from django.db import models

ACTIVITY_CHOICES = [
    ("training", "Antrenmana Katılım"),
    ("analysis", "Analize Katılım"),
    ("match_watching", "Maç İzleme"),
    ("other_team_frisbee", "Farklı Takım Frizbi Antrenmanı"),
    ("upper_body", "Üst Vücut Antrenmanı"),
    ("lower_body_core_hiit", "Alt Vücut / Core / HIIT"),
    ("endurance", "Koşu / Bisiklet / Patlayıcı Kuvvet"),
    ("other_sport", "Farklı Spor"),
    ("flexibility", "Yoga / Pilates / Mobilite"),
    ("hf_disk", "HF Disk"),
    ("tournament", "Turnuva Katılımı"),
]

BASE_POINTS = {
    "training": 4,
    "analysis": 4,
    "match_watching": 3,
    "other_team_frisbee": 2,
    "upper_body": 2,
    "lower_body_core_hiit": 3,
    "endurance": 3,
    "other_sport": 1,
    "flexibility": 1,
    "tournament": 3,
    # hf_disk: duration-based (1 pt per 20 min), not in BASE_POINTS
}

MIN_DURATION = {
    "match_watching": 30,
    "hf_disk": 20,
    # all others: 45
}


class Season(models.Model):
    number = models.PositiveIntegerField(unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)
    winner_team = models.ForeignKey(
        "Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="won_seasons",
    )

    class Meta:
        ordering = ["-number"]

    def __str__(self):
        return f"Sezon {self.number}"


class Player(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    joined_date = models.DateField(auto_now_add=True)
    total_points = models.IntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Team(models.Model):
    COLOR_CHOICES = [
        ("#8C1C2C", "Bordo"),
        ("#F5EAED", "Beyaz"),
    ]

    name = models.CharField(max_length=100)
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="teams")
    captain = models.ForeignKey(
        Player,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="captained_teams",
    )
    color_code = models.CharField(max_length=7, choices=COLOR_CHOICES, default="#8C1C2C")

    class Meta:
        unique_together = [("name", "season")]

    def __str__(self):
        return f"{self.name} ({self.season})"


class TeamMembership(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="memberships")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="memberships")
    season_points = models.IntegerField(default=0)

    class Meta:
        unique_together = [("player", "season")]

    def __str__(self):
        return f"{self.player.name} → {self.team.name} ({self.season})"


class WeeklyGoal(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="weekly_goals")
    week_number = models.PositiveIntegerField()
    description = models.CharField(max_length=255)
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_CHOICES, blank=True)
    required_count = models.PositiveIntegerField(default=1)
    min_points = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["season", "week_number"]

    def __str__(self):
        return f"{self.season} Hafta {self.week_number}: {self.description}"


class Activity(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="activities")
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=50, choices=ACTIVITY_CHOICES)
    date = models.DateField()
    duration_minutes = models.PositiveIntegerField()
    notes = models.TextField(blank=True)
    total_points = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_approved = models.BooleanField(default=True)

    class Meta:
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.player.name} – {self.get_activity_type_display()} ({self.date})"


class Tag(models.Model):
    STATUS_CHOICES = [
        ("pending", "Bekliyor"),
        ("responded", "Yanıtlandı"),
        ("expired", "Süresi Doldu"),
    ]

    tagger = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="tags_sent")
    tagged = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="tags_received")
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="tags")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    responding_activity = models.ForeignKey(
        Activity,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tag_response",
    )
    bonus_awarded = models.BooleanField(default=False)
    penalty_applied = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tagger.name} → {self.tagged.name} ({self.status})"


class PointAdjustment(models.Model):
    REASON_CHOICES = [
        ("weekly_goal_bonus", "Haftalık Hedef Bonusu"),
        ("weekly_penalty", "Haftalık Ceza (10 puan altı)"),
        ("tag_bonus", "Meydan Okuma Yanıtı Bonusu"),
        ("tag_penalty", "Meydan Okuma Cezası"),
        ("manual", "Manuel Düzeltme"),
    ]

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="adjustments")
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="adjustments")
    reason = models.CharField(max_length=50, choices=REASON_CHOICES)
    points = models.IntegerField()
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    week_number = models.PositiveIntegerField(null=True, blank=True)
    related_tag = models.ForeignKey(
        Tag, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.player.name} {self.points:+d} ({self.get_reason_display()})"
