import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update a superuser from environment variables."

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

        if not username or not email or not password:
            self.stdout.write(
                self.style.WARNING(
                    "Skipping superuser setup: missing DJANGO_SUPERUSER_USERNAME, "
                    "DJANGO_SUPERUSER_EMAIL or DJANGO_SUPERUSER_PASSWORD."
                )
            )
            return

        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )

        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created/updated."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' password updated."))
