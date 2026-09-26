from django.urls import path
from . import views

app_name = 'tracker'

urlpatterns = [
    path('session/<int:session_id>/', views.coach_session_view, name='coach_session'),
    path('session/<int:session_id>/staging/', views.deck_staging_view, name='deck_staging'),
    path('session/<int:session_id>/pair/', views.pair_swimmer_tag_view, name='pair_swimmer_tag'),
    path('session/<int:session_id>/unassign/', views.unassign_swimmer_view, name='unassign_swimmer'),
    path('session/<int:session_id>/swap-tag/', views.swap_tag_view, name='swap_tag'),
    path('swimmer/<int:swimmer_id>/metrics/', views.swimmer_metrics_view, name='swimmer_metrics'),
]