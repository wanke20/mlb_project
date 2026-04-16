from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0005_game_start_time_utc'),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='streak_type',
            field=models.CharField(blank=True, max_length=1, null=True),
        ),
        migrations.AddField(
            model_name='team',
            name='streak_length',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='team',
            name='last7_runs',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='team',
            name='season_avg',
            field=models.CharField(blank=True, max_length=8, null=True),
        ),
        migrations.AddField(
            model_name='team',
            name='season_ops',
            field=models.CharField(blank=True, max_length=8, null=True),
        ),
        migrations.AddField(
            model_name='team',
            name='season_runs',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='team',
            name='season_strikeouts',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
