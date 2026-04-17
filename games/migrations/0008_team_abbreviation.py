from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0007_team_last7_avg'),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='abbreviation',
            field=models.CharField(blank=True, max_length=5, null=True),
        ),
    ]
