# Generated for BiblioFlow monthly membership payments.
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bibliotheque", "0003_coherence_achats"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="utilisateur",
            name="date_debut_adhesion",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="CotisationAdhesion",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("montant", models.PositiveIntegerField(default=1000)),
                ("operateur", models.CharField(choices=[("orange_money", "Orange Money"), ("mtn_momo", "MTN Mobile Money")], max_length=20)),
                ("telephone_payeur", models.CharField(max_length=20)),
                ("reference_transaction", models.CharField(max_length=100)),
                ("statut", models.CharField(choices=[("en_attente", "En attente de vérification"), ("validee", "Validée"), ("refusee", "Refusée")], default="en_attente", max_length=12)),
                ("date_declaration", models.DateTimeField(auto_now_add=True)),
                ("date_validation", models.DateTimeField(blank=True, null=True)),
                ("adherent", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="cotisations", to=settings.AUTH_USER_MODEL)),
                ("validee_par", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cotisations_validees", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-date_declaration"]},
        ),
        migrations.AddConstraint(
            model_name="cotisationadhesion",
            constraint=models.UniqueConstraint(fields=("operateur", "reference_transaction"), name="cotisation_reference_unique_par_operateur"),
        ),
    ]
