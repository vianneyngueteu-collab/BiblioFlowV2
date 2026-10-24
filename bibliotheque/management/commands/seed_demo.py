from datetime import date, timedelta

from django.core.management.base import BaseCommand

from bibliotheque import services
from bibliotheque.models import Emprunt, Exemplaire, Livre, Utilisateur

RAYONS = {"Informatique": ("Étagère A", "INF"), "Science": ("Étagère B", "SCI"), "Éducation": ("Étagère C", "EDU"),
          "Économie": ("Étagère D", "ECO"), "Roman": ("Étagère E", "ROM"), "Développement personnel": ("Étagère F", "DEV")}


DESCRIPTIONS = {
    "Introduction à Python": "Les bases de la programmation avec Python : variables, boucles, fonctions et premiers projets.",
    "Développement Web moderne": "Construire un site web complet : HTML, CSS, JavaScript et un framework côté serveur.",
    "Bases de données relationnelles": "Modéliser, interroger et sécuriser une base de données : MCD, MLD, SQL.",
    "Algorithmes et structures de données": "Tris, recherches, piles, files et arbres, expliqués pas à pas avec des exercices.",
    "Mathématiques pour tous": "Un cours clair d'algèbre, de géométrie et de probabilités, avec des exemples du quotidien.",
    "Sciences de la vie": "Cellule, génétique, écosystèmes : les notions essentielles de biologie.",
    "Méthodes de recherche universitaire": "Chercher, citer et rédiger : la démarche d'un travail universitaire rigoureux.",
    "Réussir son projet académique": "Organiser ses études, planifier un mémoire et présenter ses résultats.",
    "Entrepreneuriat au Cameroun": "Créer et développer une entreprise : marché, financement, démarches locales.",
    "Gestion financière simplifiée": "Budget, trésorerie, comptabilité de base et lecture des chiffres d'une activité.",
    "Les classiques de la littérature": "Une sélection de grands textes et de repères pour entrer dans la lecture.",
    "Lire, apprendre et progresser": "Méthodes de lecture active, de mémorisation et de développement personnel.",
}


class Command(BaseCommand):
    help = "Crée les données de démonstration de la bibliothèque (idempotent)."

    def handle(self, *args, **kwargs):
        livres = [
            ("Introduction à Python", "Équipe BiblioTech", "Informatique", 2025, 8500, 12),
            ("Développement Web moderne", "Équipe BiblioTech", "Informatique", 2025, 12000, 9),
            ("Bases de données relationnelles", "Jean Mvondo", "Informatique", 2024, 10000, 8),
            ("Algorithmes et structures de données", "Collectif Campus", "Informatique", 2024, 9500, 7),
            ("Mathématiques pour tous", "Paul Essomba", "Science", 2023, 7500, 15),
            ("Sciences de la vie", "Amina K.", "Science", 2024, 9000, 10),
            ("Méthodes de recherche universitaire", "Marie Ndom", "Éducation", 2025, 6500, 14),
            ("Réussir son projet académique", "Marie Ndom", "Éducation", 2025, 7000, 11),
            ("Entrepreneuriat au Cameroun", "Paul Essomba", "Économie", 2024, 11000, 6),
            ("Gestion financière simplifiée", "Jean Mvondo", "Économie", 2023, 9500, 8),
            ("Les classiques de la littérature", "Collectif Campus", "Roman", 2022, 8000, 10),
            ("Lire, apprendre et progresser", "Amina K.", "Développement personnel", 2024, 6000, 13),
        ]
        for titre, auteur, categorie, annee, prix, stock in livres:
            # get_or_create : relancer la démo ne remet jamais à zéro le prix ou le stock d'un livre existant
            livre, _ = Livre.objects.get_or_create(titre=titre, defaults={
                "auteur": auteur, "categorie": categorie, "annee_publication": annee, "langue": "Français",
                "prix": prix, "stock_vente": stock})
            # ISBN et description : renseignés seulement s'ils sont vides (on n'écrase jamais une saisie du personnel)
            if not livre.isbn:
                livre.isbn = f"DEMO-{livre.pk:04d}"
            if not livre.description:
                livre.description = DESCRIPTIONS.get(titre, "")
            livre.save(update_fields=["isbn", "description"])
            etagere, code = RAYONS[categorie]
            existants = livre.exemplaires.count()
            for i in range(existants + 1, min(stock, 3) + 1):
                Exemplaire.objects.get_or_create(code_barres=f"EX-{livre.pk:04d}-{i:02d}", defaults={
                    "livre": livre, "etagere": etagere, "code_rayon": f"{code}-{livre.pk:02d}"})

        comptes = [("admin", "Admin", "Bibliothèque", "administrateur"), ("bibliothecaire", "Aline", "Ndom", "bibliothecaire"),
                   ("etudiant", "Vianney", "Ngueteu", "adherent"), ("lecteur2", "Sarah", "Manga", "adherent")]
        today = date.today()
        for username, prenom, nom, role in comptes:
            u, cree = Utilisateur.objects.get_or_create(username=username, defaults={"nom": nom, "prenom": prenom})
            if cree:
                u.set_password("Bibliotheque2026!")
            u.nom, u.prenom, u.role, u.is_active = nom, prenom, role, True
            u.email, u.telephone, u.adresse = f"{username}@bibliotheque.local", "690000000", "Yaoundé, Cameroun"
            u.is_staff = u.is_superuser = (username == "admin")
            if role == "adherent":
                u.numero_carte = u.numero_carte or services.generer_numero_carte()
                u.statut = u.statut or "actif"
                u.date_expiration = u.date_expiration or today + timedelta(days=services.params().duree_adhesion_jours)
            u.save()

        # Scénario de démonstration : un prêt en retard (sanction automatique) et un prêt normal
        if not Emprunt.objects.exists():
            personnel = Utilisateur.objects.get(username="bibliothecaire")
            ex_retard = Exemplaire.objects.filter(livre__titre="Introduction à Python").first()
            ex_normal = Exemplaire.objects.filter(livre__titre="Développement Web moderne").first()
            Emprunt.objects.create(adherent=Utilisateur.objects.get(username="lecteur2"), personnel=personnel,
                                   exemplaire=ex_retard, date_emprunt=today - timedelta(days=23),
                                   date_retour_prevue=today - timedelta(days=9), statut="retard")
            Emprunt.objects.create(adherent=Utilisateur.objects.get(username="etudiant"), personnel=personnel,
                                   exemplaire=ex_normal, date_emprunt=today - timedelta(days=4),
                                   date_retour_prevue=today + timedelta(days=10), statut="en_cours")
            Exemplaire.objects.filter(pk__in=[ex_retard.pk, ex_normal.pk]).update(statut="emprunte")
            services.maj_quotidienne()
        self.stdout.write(self.style.SUCCESS("Données de démonstration créées."))
        self.stdout.write("Démo : lecteur2 a un livre en retard (sanction automatique) ; etudiant a un prêt en cours.")
        self.stdout.write("Comptes : admin / bibliothecaire / etudiant / lecteur2  (mot de passe : Bibliotheque2026!)")
