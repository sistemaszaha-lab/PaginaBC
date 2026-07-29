import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update a superuser from environment variables safely."

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

        if not username:
            self.stdout.write(
                self.style.WARNING(
                    "Skipping superuser setup: missing DJANGO_SUPERUSER_USERNAME."
                )
            )
            return

        user_model = get_user_model()
        user = user_model.objects.filter(username=username).first()

        if not user:
            # Require all fields for creation
            if not email or not password:
                self.stdout.write(
                    self.style.WARNING(
                        "Skipping superuser creation: missing DJANGO_SUPERUSER_EMAIL or DJANGO_SUPERUSER_PASSWORD."
                    )
                )
                return

            user = user_model.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' created successfully."))
        else:
            # User exists: verify permissions, optionally update email, do NOT change password
            updated = False
            if email and email.strip() and user.email != email:
                user.email = email
                updated = True

            if not user.is_staff or not user.is_superuser or not user.is_active:
                user.is_staff = True
                user.is_superuser = True
                user.is_active = True
                updated = True

            if updated:
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' updated (permissions/email). Password unchanged."))
            else:
                self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' already exists with correct permissions. Password unchanged."))
