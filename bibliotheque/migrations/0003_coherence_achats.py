from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def reparer(apps, schema_editor):
    Achat = apps.get_model("bibliotheque", "Achat")
    # Achats annulés : ils ne sont plus « à payer »
    Achat.objects.filter(statut="annulee").update(statut_paiement="annule", date_limite_retrait=None)
    # Le mode de réception est la seule source de vérité de la livraison
    Achat.objects.filter(mode_reception="retrait").exclude(adresse_livraison="").update(mode_reception="livraison")
    # L'identité d'un adhérent vient de son compte : on supprime les copies client_*
    Achat.objects.filter(adherent__isnull=False).update(
        client_prenom="", client_nom="", client_email="", client_telephone="")
    # Achats en ligne encore actifs : ils reçoivent une échéance (sinon leur stock resterait bloqué)
    echeance = timezone.localdate() + timedelta(days=5)
    Achat.objects.filter(canal="en_ligne", statut__in=("en_attente", "prete"), date_limite_retrait__isnull=True
                         ).update(date_limite_retrait=echeance)


class Migration(migrations.Migration):
    dependencies = [("bibliotheque", "0002_biblio_metier")]
    operations = [migrations.RunPython(reparer, migrations.RunPython.noop)]
