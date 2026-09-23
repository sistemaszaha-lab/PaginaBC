from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('operaciones', '0013_operacionopcion_eliminado_en_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='operacioncolumna',
            name='usuarios_visibles',
            field=models.ManyToManyField(blank=True, related_name='columnas_operaciones_visibles', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='operacioncolumna',
            name='visible_para_todos',
            field=models.BooleanField(default=True),
        ),
    ]
