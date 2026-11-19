from django.contrib.auth import views as auth
from django.urls import path
from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("ingresar/", auth.LoginView.as_view(template_name="servicios/ingresar.html"), name="ingresar"),
    path("salir/", auth.LogoutView.as_view(), name="salir"),
    path("tickets/nuevo/", views.nuevo, name="nuevo"),
    path("tickets/<int:pk>/", views.ticket, name="ticket"),
    path("tickets/<int:pk>/acciones/", views.agregar, name="agregar"),
    path("acciones/<int:pk>/estado/", views.cambiar_estado, name="cambiar_estado"),
    path("acciones/<int:pk>/realizar/", views.realizar, name="realizar"),
]
