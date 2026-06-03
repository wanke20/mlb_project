from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0013_pitcher_advanced_stats'),
    ]

    operations = [
        migrations.AddField(
            model_name='pitcher',
            name='throws',
            field=models.CharField(blank=True, max_length=1, null=True),
        ),
        migrations.CreateModel(
            name='Hitter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mlb_id', models.IntegerField(unique=True)),
                ('name', models.CharField(max_length=100)),
                ('bats', models.CharField(blank=True, max_length=1, null=True)),
                ('rank', models.IntegerField(blank=True, null=True)),
                ('season_pa', models.IntegerField(blank=True, null=True)),
                ('season_avg', models.CharField(blank=True, max_length=8, null=True)),
                ('season_ops', models.CharField(blank=True, max_length=8, null=True)),
                ('vs_l_pa', models.IntegerField(blank=True, null=True)),
                ('vs_l_avg', models.CharField(blank=True, max_length=8, null=True)),
                ('vs_l_ops', models.CharField(blank=True, max_length=8, null=True)),
                ('vs_r_pa', models.IntegerField(blank=True, null=True)),
                ('vs_r_avg', models.CharField(blank=True, max_length=8, null=True)),
                ('vs_r_ops', models.CharField(blank=True, max_length=8, null=True)),
                ('team', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='hitters',
                    to='games.team',
                )),
            ],
            options={'ordering': ['rank']},
        ),
    ]
