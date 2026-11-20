from django.contrib.auth import views as auth
from django.urls import path
from . import alertas, catalogo, views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("ingresar/", auth.LoginView.as_view(template_name="servicios/ingresar.html"), name="ingresar"),
    path("salir/", auth.LogoutView.as_view(), name="salir"),
    path("clientes/abonados/", catalogo.clientes, {"tipo": "abonado"}, name="abonados"),
    path("clientes/terceros/", catalogo.clientes, {"tipo": "tercero"}, name="terceros"),
    path("clientes/nuevo/", catalogo.nuevo_cliente, name="nuevo_cliente"),
    path("clientes/<int:pk>/", catalogo.cliente, name="cliente"),
    path("plantas/nueva/", catalogo.nueva_planta, name="nueva_planta"),
    path("plantas/<int:pk>/", catalogo.planta, name="planta"),
    path("equipos/", catalogo.equipos, name="equipos"),
    path("equipos/nuevo/", catalogo.nuevo_equipo, name="nuevo_equipo"),
    path("equipos/<int:pk>/", catalogo.equipo, name="equipo"),
    path("alertas/", alertas.alertas, name="alertas"),
    path("alertas/nueva/", alertas.nueva_alerta, name="nueva_alerta"),
    path("tickets/nuevo/", views.nuevo, name="nuevo"),
    path("tickets/<int:pk>/", views.ticket, name="ticket"),
    path("tickets/<int:pk>/vincular/", views.vincular_ticket, name="vincular_ticket"),
    path("tickets/<int:pk>/acciones/", views.agregar, name="agregar"),
    path("acciones/<int:pk>/estado/", views.cambiar_estado, name="cambiar_estado"),
    path("acciones/<int:pk>/realizar/", views.realizar, name="realizar"),
]
