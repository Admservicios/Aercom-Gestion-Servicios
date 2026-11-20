from getpass import getpass
import sys

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from servicios.permisos import ROLES_SERVICIOS, Rol


class Command(BaseCommand):
    help = "Crea una cuenta individual con un rol de Servicios y solicita la clave de forma interactiva."

    def add_arguments(self, parser):
        parser.add_argument("usuario")
        parser.add_argument("--rol", required=True, choices=sorted(ROLES_SERVICIOS - {Rol.OFICINA_ANTERIOR}))

    def handle(self, usuario, rol, **options):
        if not sys.stdin.isatty():
            raise CommandError("Ejecutá este comando en una terminal interactiva.")
        modelo = get_user_model()
        if modelo.objects.filter(username=usuario).exists():
            raise CommandError("Ya existe una cuenta con ese usuario.")
        persona = modelo(username=usuario)
        try:
            persona.full_clean(exclude=["password"])
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error
        clave = getpass("Clave de la cuenta: ")
        if not clave or clave != getpass("Repetí la clave: "):
            raise CommandError("Las claves deben ser iguales y tener contenido.")
        try:
            validate_password(clave, persona)
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error
        persona.set_password(clave)
        try:
            with transaction.atomic():
                persona.save()
                grupo, _ = Group.objects.get_or_create(name=rol)
                persona.groups.add(grupo)
        except IntegrityError as error:
            if modelo.objects.filter(username=usuario).exists():
                raise CommandError("Ya existe una cuenta con ese usuario.") from error
            raise
        self.stdout.write(self.style.SUCCESS("Cuenta creada."))
