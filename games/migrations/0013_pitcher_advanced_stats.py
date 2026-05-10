from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0012_game_away_starter_innings_game_home_starter_innings'),
    ]

    operations = [
        migrations.AddField(
            model_name='pitcher',
            name='fip',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='pitcher',
            name='k_bb_pct',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='pitcher',
            name='woba',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='pitcher',
            name='xera',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='pitcher',
            name='xwoba',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='pitcher',
            name='barrel_pct',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
