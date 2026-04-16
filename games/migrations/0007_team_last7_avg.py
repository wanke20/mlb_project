from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0006_team_trend_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='last7_avg',
            field=models.CharField(blank=True, max_length=8, null=True),
        ),
    ]
