from django.urls import path
from . import views

app_name = 'tracker'

urlpatterns = [
    path('session/<int:session_id>/', views.coach_session_view, name='coach_session'),
    path('swimmer/<int:swimmer_id>/metrics/', views.swimmer_metrics_view, name='swimmer_metrics'),
]