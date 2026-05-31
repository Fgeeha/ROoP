from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0004_assign_existing_data_to_admin'),
    ]

    operations = [
        migrations.AddField(
            model_name='document',
            name='processed_chunks',
            field=models.IntegerField(default=0, verbose_name='Обработано чанков'),
        ),
        migrations.AddField(
            model_name='document',
            name='total_chunks',
            field=models.IntegerField(default=0, verbose_name='Всего чанков'),
        ),
    ]
