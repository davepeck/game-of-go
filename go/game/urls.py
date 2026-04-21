"""URL routing for the ``game`` app."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.MainView.as_view(), name="main"),
    path("get-going/", views.GetGoingView.as_view(), name="get-going"),
    path("play/<slug:cookie>/", views.PlayGameView.as_view(), name="play"),
    path("history/<slug:cookie>.sgf", views.SGFView.as_view(), name="sgf"),
    path("history/<slug:cookie>/", views.HistoryView.as_view(), name="history"),
    path(
        "history/<slug:cookie>/<int:move>/",
        views.HistoryMoveView.as_view(),
        name="history-move",
    ),
    path("options/<slug:cookie>/", views.OptionsView.as_view(), name="options"),
    path("service/create-game/", views.CreateGameView.as_view(), name="service-create-game"),
    path(
        "service/make-this-move/",
        views.MakeThisMoveView.as_view(),
        name="service-make-this-move",
    ),
    path(
        "service/has-opponent-moved/",
        views.HasOpponentMovedView.as_view(),
        name="service-has-opponent-moved",
    ),
    path("service/mark-stone/", views.MarkStoneView.as_view(), name="service-mark-stone"),
    path(
        "service/has-opponent-scored/",
        views.HasOpponentScoredView.as_view(),
        name="service-has-opponent-scored",
    ),
    path("service/done/", views.DoneView.as_view(), name="service-done"),
    path(
        "service/change-options/",
        views.ChangeOptionsView.as_view(),
        name="service-change-options",
    ),
    path(
        "service/change-grid-options/",
        views.ChangeGridOptionsView.as_view(),
        name="service-change-grid-options",
    ),
    path("service/pass/", views.PassView.as_view(), name="service-pass"),
    path("service/resign/", views.ResignView.as_view(), name="service-resign"),
    path("service/recent-chat/", views.RecentChatView.as_view(), name="service-recent-chat"),
    path("service/add-chat/", views.AddChatView.as_view(), name="service-add-chat"),
    path(
        "service/get-historical-state/",
        views.GetHistoricalStateView.as_view(),
        name="service-get-historical-state",
    ),
]
