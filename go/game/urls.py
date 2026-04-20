"""URL routing for the ``game`` app."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.MainView.as_view()),
    path("get-going/", views.GetGoingView.as_view()),
    path("play/<slug:cookie>/", views.PlayGameView.as_view()),
    path("history/<slug:cookie>.sgf", views.SGFView.as_view()),
    path("history/<slug:cookie>/", views.HistoryView.as_view()),
    path("history/<slug:cookie>/<int:move>/", views.HistoryMoveView.as_view()),
    path("options/<slug:cookie>/", views.OptionsView.as_view()),
    path("service/create-game/", views.CreateGameView.as_view()),
    path("service/make-this-move/", views.MakeThisMoveView.as_view()),
    path("service/has-opponent-moved/", views.HasOpponentMovedView.as_view()),
    path("service/mark-stone/", views.MarkStoneView.as_view()),
    path("service/has-opponent-scored/", views.HasOpponentScoredView.as_view()),
    path("service/done/", views.DoneView.as_view()),
    path("service/change-options/", views.ChangeOptionsView.as_view()),
    path("service/change-grid-options/", views.ChangeGridOptionsView.as_view()),
    path("service/pass/", views.PassView.as_view()),
    path("service/resign/", views.ResignView.as_view()),
    path("service/recent-chat/", views.RecentChatView.as_view()),
    path("service/add-chat/", views.AddChatView.as_view()),
    path("service/get-historical-state/", views.GetHistoricalStateView.as_view()),
]
