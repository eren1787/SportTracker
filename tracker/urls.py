from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("giris/", views.login_view, name="login"),
    path("kayit/", views.signup_view, name="signup"),
    path("cikis/", views.logout_view, name="logout"),
    path("aktivite/ekle/", views.log_activity, name="log_activity"),
    path("aktivite/liste/", views.activity_list, name="activity_list"),
    path("siralama/", views.leaderboard, name="leaderboard"),
    path("meydan-oku/", views.tag_player, name="tag_player"),
    path("meydan-okumalar/", views.tag_list, name="tag_list"),
    path("hedefler/", views.weekly_goals, name="weekly_goals"),
    path("sezon/<int:pk>/", views.season_detail, name="season_detail"),
    path("profil/<int:pk>/", views.player_profile, name="player_profile"),
    path("hareketler/", views.feed, name="feed"),
]
