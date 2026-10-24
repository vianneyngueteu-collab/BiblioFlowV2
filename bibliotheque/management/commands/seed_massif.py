"""Peuple la base avec un jeu de données varié : livres de tous les genres, adhérents dans tous les états,
prêts (en cours, en retard, rendus, perdus, demandés…), achats (comptoir, en ligne, invités).

    python manage.py seed_massif            # ajoute les données (une seule fois)
    python manage.py seed_massif --force    # ajoute quand même, même si déjà exécuté

Les données respectent les règles métier : quotas, sanctions, stocks, statuts des exemplaires.
"""
import random
import unicodedata
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import uuid4

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from bibliotheque import services
from bibliotheque.models import Achat, Emprunt, Exemplaire, LigneAchat, Livre, Utilisateur

SENTINELLE = "amina.tchoupo"
MOT_DE_PASSE = "Bibliotheque2026!"

# categorie -> (étagère, code rayon, fourchette de prix FCFA)
RAYONS = {
    "Informatique": ("Étagère A", "INF", (8000, 18000)), "Science": ("Étagère B", "SCI", (6500, 15000)),
    "Éducation": ("Étagère C", "EDU", (5000, 12000)), "Économie": ("Étagère D", "ECO", (8000, 16000)),
    "Roman": ("Étagère E", "ROM", (4000, 9000)), "Développement personnel": ("Étagère F", "DEV", (5000, 11000)),
    "Policier": ("Étagère G", "POL", (4000, 8000)), "Science-fiction": ("Étagère G", "SFI", (4500, 9000)),
    "Histoire": ("Étagère H", "HIS", (6000, 14000)), "Géographie et voyage": ("Étagère H", "GEO", (7000, 15000)),
    "Cuisine": ("Étagère I", "CUI", (5000, 12000)), "Santé et bien-être": ("Étagère I", "SAN", (5000, 11000)),
    "Art et musique": ("Étagère J", "ART", (6000, 16000)), "Droit": ("Étagère K", "DRO", (9000, 20000)),
    "Jeunesse": ("Étagère L", "JEU", (2500, 6500)), "Bandes dessinées": ("Étagère L", "BD", (4500, 10000)),
    "Poésie": ("Étagère M", "POE", (3500, 7500)), "Théâtre": ("Étagère M", "THE", (3000, 7000)),
    "Religion et spiritualité": ("Étagère N", "REL", (4000, 9000)), "Philosophie": ("Étagère N", "PHI", (5000, 11000)),
    "Langues": ("Étagère O", "LAN", (5000, 12000)), "Sport": ("Étagère O", "SPO", (5000, 11000)),
    "Agriculture": ("Étagère P", "AGR", (6000, 13000)), "Biographie": ("Étagère P", "BIO", (6000, 13000)),
}

DESCRIPTIONS = {
    "Informatique": "Un guide pratique, illustré d'exemples et d'exercices corrigés, pour progresser pas à pas.",
    "Science": "Les grandes idées de la science expliquées simplement, avec schémas et exemples du quotidien.",
    "Éducation": "Des méthodes concrètes pour enseigner, apprendre et réussir ses examens.",
    "Économie": "Les notions clés de l'économie et de la gestion, mises en perspective avec des cas réels.",
    "Roman": "Un récit marquant, des personnages inoubliables et une langue qui reste en mémoire.",
    "Développement personnel": "Des idées simples et applicables dès aujourd'hui pour changer ses habitudes.",
    "Policier": "Une enquête menée tambour battant : indices à recouper, fausses pistes et dénouement surprenant.",
    "Science-fiction": "Un voyage imaginaire qui interroge notre rapport à la science et à l'avenir.",
    "Histoire": "Un regard documenté sur les événements et les idées qui ont façonné le monde et l'Afrique.",
    "Géographie et voyage": "Cartes, repères et conseils pratiques pour comprendre un territoire et le parcourir.",
    "Cuisine": "Des recettes accessibles, des gestes de base et des astuces pour cuisiner tous les jours.",
    "Santé et bien-être": "Des conseils fiables pour prendre soin de son corps, de son sommeil et de son esprit.",
    "Art et musique": "Une initiation aux arts, aux styles et aux grands noms, pour regarder et écouter autrement.",
    "Droit": "Les règles essentielles expliquées clairement, avec des exemples et des modèles de documents.",
    "Jeunesse": "Un livre illustré qui donne le goût de lire aux plus jeunes, à partager en famille.",
    "Bandes dessinées": "Une bande dessinée au dessin vivant et à l'humour efficace, pour tous les âges.",
    "Poésie": "Des vers à lire à voix haute, entre révolte, tendresse et musique des mots.",
    "Théâtre": "Une pièce à lire ou à jouer, avec des dialogues vifs et un propos qui n'a pas vieilli.",
    "Religion et spiritualité": "Un parcours de lecture pour comprendre les traditions et nourrir la réflexion intérieure.",
    "Philosophie": "Un texte fondateur qui pose les grandes questions : liberté, vérité, sens de l'existence.",
    "Langues": "Une méthode progressive avec vocabulaire, grammaire et exercices d'application.",
    "Sport": "Des programmes d'entraînement, des règles de jeu et des conseils pour progresser sans se blesser.",
    "Agriculture": "Techniques culturales et d'élevage adaptées au climat local, avec conseils de rentabilité.",
    "Biographie": "Le parcours d'une personnalité raconté de l'intérieur, avec ses doutes et ses engagements.",
}

# (titre, auteur, catégorie, année, langue)
LIVRES = [
    ("Clean Code", "Robert C. Martin", "Informatique", 2008, "Anglais"), ("Réseaux informatiques", "Collectif Campus", "Informatique", 2022, "Français"),
    ("Cybersécurité pour tous", "Jean Mvondo", "Informatique", 2025, "Français"), ("Excel pas à pas", "Équipe BiblioTech", "Informatique", 2023, "Français"),
    ("Une brève histoire du temps", "Stephen Hawking", "Science", 1988, "Français"), ("Le gène égoïste", "Richard Dawkins", "Science", 1976, "Français"),
    ("Astronomie pour tous", "Paul Essomba", "Science", 2021, "Français"), ("Physique-chimie, cours de lycée", "Collectif Campus", "Science", 2023, "Français"),
    ("Pédagogie active en classe", "Marie Ndom", "Éducation", 2024, "Français"), ("Préparer le baccalauréat", "Collectif Campus", "Éducation", 2025, "Français"),
    ("Le Capital au XXIe siècle", "Thomas Piketty", "Économie", 2013, "Français"), ("Père riche, père pauvre", "Robert Kiyosaki", "Économie", 1997, "Français"),
    ("Marketing digital en Afrique", "Collectif Campus", "Économie", 2024, "Français"),
    ("Le Vieux Nègre et la Médaille", "Ferdinand Oyono", "Roman", 1956, "Français"), ("Mission terminée", "Mongo Beti", "Roman", 1957, "Français"),
    ("Le Pauvre Christ de Bomba", "Mongo Beti", "Roman", 1956, "Français"), ("Les Soleils des indépendances", "Ahmadou Kourouma", "Roman", 1968, "Français"),
    ("Une si longue lettre", "Mariama Bâ", "Roman", 1979, "Français"), ("Things Fall Apart", "Chinua Achebe", "Roman", 1958, "Anglais"),
    ("Le Petit Prince", "Antoine de Saint-Exupéry", "Roman", 1943, "Français"), ("L'Étranger", "Albert Camus", "Roman", 1942, "Français"),
    ("Les Misérables", "Victor Hugo", "Roman", 1862, "Français"), ("L'Alchimiste", "Paulo Coelho", "Roman", 1988, "Français"),
    ("Cent ans de solitude", "Gabriel García Márquez", "Roman", 1967, "Français"),
    ("Atomic Habits", "James Clear", "Développement personnel", 2018, "Anglais"),
    ("Les 7 habitudes de ceux qui réalisent tout ce qu'ils entreprennent", "Stephen R. Covey", "Développement personnel", 1989, "Français"),
    ("Le Crime de l'Orient-Express", "Agatha Christie", "Policier", 1934, "Français"), ("Le Meurtre de Roger Ackroyd", "Agatha Christie", "Policier", 1926, "Français"),
    ("Arsène Lupin, gentleman-cambrioleur", "Maurice Leblanc", "Policier", 1907, "Français"), ("Les Aventures de Sherlock Holmes", "Arthur Conan Doyle", "Policier", 1892, "Français"),
    ("Le Chien des Baskerville", "Arthur Conan Doyle", "Policier", 1902, "Français"),
    ("Vingt mille lieues sous les mers", "Jules Verne", "Science-fiction", 1870, "Français"), ("Le Tour du monde en quatre-vingts jours", "Jules Verne", "Science-fiction", 1872, "Français"),
    ("La Machine à explorer le temps", "H. G. Wells", "Science-fiction", 1895, "Français"), ("Dune", "Frank Herbert", "Science-fiction", 1965, "Français"),
    ("Fahrenheit 451", "Ray Bradbury", "Science-fiction", 1953, "Français"), ("1984", "George Orwell", "Science-fiction", 1949, "Français"),
    ("Sapiens : une brève histoire de l'humanité", "Yuval Noah Harari", "Histoire", 2011, "Français"), ("Discours sur le colonialisme", "Aimé Césaire", "Histoire", 1950, "Français"),
    ("L'Afrique noire est mal partie", "René Dumont", "Histoire", 1962, "Français"), ("Histoire du Cameroun", "Collectif Campus", "Histoire", 2019, "Français"),
    ("Atlas du Cameroun", "Collectif Campus", "Géographie et voyage", 2020, "Français"), ("Guide du voyageur en Afrique centrale", "Collectif Campus", "Géographie et voyage", 2023, "Français"),
    ("Carnets de voyage au Cameroun", "Marie Ndom", "Géographie et voyage", 2022, "Français"),
    ("Cuisine camerounaise : recettes de famille", "Amina K.", "Cuisine", 2023, "Français"), ("Le ndolé et autres plats du Cameroun", "Jean Mvondo", "Cuisine", 2021, "Français"),
    ("Pâtisserie facile", "Collectif Campus", "Cuisine", 2024, "Français"), ("Jus, tisanes et boissons d'ici", "Amina K.", "Cuisine", 2022, "Français"),
    ("Nutrition et santé au quotidien", "Paul Essomba", "Santé et bien-être", 2024, "Français"), ("Paludisme : prévenir et soigner", "Collectif Campus", "Santé et bien-être", 2023, "Français"),
    ("Bien dormir, mieux vivre", "Amina K.", "Santé et bien-être", 2025, "Français"),
    ("Histoire de la musique camerounaise", "Jean Mvondo", "Art et musique", 2021, "Français"), ("Apprendre le piano", "Collectif Campus", "Art et musique", 2020, "Français"),
    ("Le dessin pas à pas", "Marie Ndom", "Art et musique", 2022, "Français"), ("L'art africain", "Collectif Campus", "Art et musique", 2018, "Français"),
    ("Droit des affaires OHADA", "Collectif Campus", "Droit", 2023, "Français"), ("Introduction au droit camerounais", "Paul Essomba", "Droit", 2022, "Français"),
    ("Droit du travail pratique", "Jean Mvondo", "Droit", 2024, "Français"),
    ("Contes d'Afrique pour s'endormir", "Amina K.", "Jeunesse", 2021, "Français"), ("Les aventures de Nkoa le malin", "Marie Ndom", "Jeunesse", 2023, "Français"),
    ("Mon premier dictionnaire illustré", "Collectif Campus", "Jeunesse", 2022, "Français"), ("Apprendre à compter avec Lili", "Marie Ndom", "Jeunesse", 2024, "Français"),
    ("Le Petit Nicolas", "René Goscinny", "Jeunesse", 1960, "Français"),
    ("Astérix le Gaulois", "René Goscinny et Albert Uderzo", "Bandes dessinées", 1961, "Français"), ("Tintin : Le Lotus bleu", "Hergé", "Bandes dessinées", 1936, "Français"),
    ("Aya de Yopougon", "Marguerite Abouet", "Bandes dessinées", 2005, "Français"), ("Lucky Luke : La Ville fantôme", "Morris", "Bandes dessinées", 1965, "Français"),
    ("Cahier d'un retour au pays natal", "Aimé Césaire", "Poésie", 1939, "Français"), ("Les Fleurs du mal", "Charles Baudelaire", "Poésie", 1857, "Français"),
    ("Chants d'ombre", "Léopold Sédar Senghor", "Poésie", 1945, "Français"), ("Alcools", "Guillaume Apollinaire", "Poésie", 1913, "Français"),
    ("Le Malade imaginaire", "Molière", "Théâtre", 1673, "Français"), ("En attendant Godot", "Samuel Beckett", "Théâtre", 1952, "Français"), ("Antigone", "Jean Anouilh", "Théâtre", 1944, "Français"),
    ("Les grandes religions du monde", "Collectif Campus", "Religion et spiritualité", 2019, "Français"), ("Méditer chaque jour", "Amina K.", "Religion et spiritualité", 2024, "Français"),
    ("Discours de la méthode", "René Descartes", "Philosophie", 1637, "Français"), ("Le Mythe de Sisyphe", "Albert Camus", "Philosophie", 1942, "Français"),
    ("Ainsi parlait Zarathoustra", "Friedrich Nietzsche", "Philosophie", 1883, "Français"), ("Introduction à la philosophie africaine", "Collectif Campus", "Philosophie", 2017, "Français"),
    ("Apprendre l'anglais facilement", "Collectif Campus", "Langues", 2024, "Anglais"), ("Grammaire française essentielle", "Marie Ndom", "Langues", 2022, "Français"),
    ("Espagnol débutant", "Collectif Campus", "Langues", 2021, "Espagnol"), ("Parlons duala", "Jean Mvondo", "Langues", 2016, "Français"),
    ("Football : tactiques et entraînement", "Paul Essomba", "Sport", 2022, "Français"), ("Courir sans se blesser", "Amina K.", "Sport", 2023, "Français"),
    ("Le basketball pour débutants", "Collectif Campus", "Sport", 2020, "Français"),
    ("La cacaoculture au Cameroun", "Jean Mvondo", "Agriculture", 2021, "Français"), ("Maraîchage en milieu urbain", "Amina K.", "Agriculture", 2023, "Français"),
    ("Élevage de volaille : guide pratique", "Paul Essomba", "Agriculture", 2022, "Français"),
    ("Un long chemin vers la liberté", "Nelson Mandela", "Biographie", 1995, "Français"), ("Mémoires d'un instituteur de brousse", "Marie Ndom", "Biographie", 2019, "Français"),
]

PRENOMS = ["Aline", "Brice", "Christelle", "Daniel", "Estelle", "Fabrice", "Grâce", "Hervé", "Inès", "Joël", "Karine", "Landry", "Mireille", "Nadège",
           "Olivier", "Pascaline", "Rodrigue", "Sandrine", "Thierry", "Ursule", "Valérie", "Wilfried", "Yvette", "Zacharie", "Brenda", "Cédric",
           "Dorine", "Elvis", "Flore", "Gaëtan", "Hortense", "Ibrahim", "Josiane", "Kevin", "Laure", "Moussa"]
NOMS = ["Tchoupo", "Kamga", "Fotso", "Nkeng", "Abega", "Mbarga", "Tagne", "Ngono", "Essama", "Kenfack", "Njoya", "Atangana", "Bella", "Owona", "Ekani",
        "Nana", "Djomo", "Tchamba", "Fouda", "Ndongo", "Mouko", "Eyenga", "Yimga", "Wamba", "Sime", "Pouth", "Lemb", "Mvogo", "Kouam", "Ahidjo", "Oumarou", "Tamo", "Bikoï", "Nguimfack", "Zogo", "Mbida"]
LIEUX = [("Douala", "Akwa"), ("Douala", "Bonamoussadi"), ("Douala", "Deïdo"), ("Yaoundé", "Bastos"), ("Yaoundé", "Mvog-Ada"), ("Yaoundé", "Essos"),
         ("Bafoussam", "Tamdja"), ("Garoua", "Roumdé Adjia"), ("Kribi", "Mpalla"), ("Limbé", "Down Beach"), ("Bamenda", "Commercial Avenue"),
         ("Buea", "Molyko"), ("Ebolowa", "Nko'ovos"), ("Maroua", "Domayo"), ("Bertoua", "Mokolo"), ("Ngaoundéré", "Bini")]


def ascii_min(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower().replace(" ", "").replace("'", "")


def dt(d, h=10, m=0):
    return timezone.make_aware(datetime.combine(d, time(h, m)))


class Command(BaseCommand):
    help = "Remplit la base avec un grand jeu de données varié (livres, adhérents, prêts, achats)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Ajouter même si le jeu a déjà été créé.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if Utilisateur.objects.filter(username=SENTINELLE).exists() and not opts["force"]:
            self.stdout.write(self.style.WARNING("Le jeu de données massif existe déjà (utilisez --force pour en ajouter)."))
            return
        self.rng = random.Random(2026 + Utilisateur.objects.count())   # autre tirage à chaque ajout
        self.today = timezone.localdate()
        self.p = services.params()
        self.livres()
        self.personnel_et_adherents()
        self.emprunts()
        self.achats()
        services.maj_quotidienne()
        self.rapport()

    # ------------------------------------------------------------------ livres
    def livres(self):
        rng, nouveaux = self.rng, 0
        for titre, auteur, cat, annee, langue in LIVRES:
            etagere, code, (pmin, pmax) = RAYONS[cat]
            prix = round(rng.randint(pmin, pmax) / 500) * 500
            stock = rng.choice([0, 0, 3, 5, 8, 10, 12, 15, 20, 25])
            livre, cree = Livre.objects.get_or_create(titre=titre, defaults={
                "auteur": auteur, "categorie": cat, "annee_publication": annee, "langue": langue, "prix": prix,
                "stock_vente": stock, "description": DESCRIPTIONS[cat], "actif": True})
            if not cree:
                continue
            nouveaux += 1
            livre.isbn = f"DEMO-{livre.pk:04d}"
            livre.save(update_fields=["isbn"])
            for i in range(1, rng.choice([1, 2, 2, 3, 3, 4]) + 1):
                Exemplaire.objects.get_or_create(code_barres=f"EX-{livre.pk:04d}-{i:02d}", defaults={
                    "livre": livre, "etagere": etagere, "code_rayon": f"{code}-{livre.pk:02d}",
                    "etat_physique": "abime" if rng.random() < 0.12 else "bon"})
        # quelques titres hors catalogue ou retirés du fonds, pour voir les cas limites en gestion
        for l in Livre.objects.filter(titre__in=["Parlons duala", "Alcools"]):
            l.actif = False
            l.save(update_fields=["actif"])
        for ex in Exemplaire.objects.filter(livre__titre="Mémoires d'un instituteur de brousse")[:1]:
            ex.statut = "retire"
            ex.save(update_fields=["statut"])
        self.stdout.write(f"Livres ajoutés : {nouveaux}")

    # --------------------------------------------------------------- utilisateurs
    def personnel_et_adherents(self):
        rng, today = self.rng, self.today
        for username, prenom, nom in [("bibliothecaire2", "Landry", "Eyenga"), ("bibliothecaire3", "Pascaline", "Tamo")]:
            u, cree = Utilisateur.objects.get_or_create(username=username, defaults={"nom": nom, "prenom": prenom})
            if cree:
                u.set_password(MOT_DE_PASSE)
            u.nom, u.prenom, u.role, u.is_active = nom, prenom, "bibliothecaire", True
            u.email, u.telephone, u.adresse = f"{username}@bibliotheque.local", "690000001", "Douala, Cameroun"
            u.save()
        self.staff = list(Utilisateur.objects.filter(role="bibliothecaire"))

        # --force : on ne recrée jamais un compte existant, on en ajoute de nouveaux
        vus = set(Utilisateur.objects.values_list("username", flat=True))
        couples = [] if SENTINELLE in vus else [("Amina", "Tchoupo")]
        vus.add(SENTINELLE)
        while len(couples) < 36:
            c = (rng.choice(PRENOMS), rng.choice(NOMS))
            u = f"{ascii_min(c[0])}.{ascii_min(c[1])}"
            if u not in vus:
                vus.add(u); couples.append(c)
        self.adherents = []
        for i, (prenom, nom) in enumerate(couples):
            username = f"{ascii_min(prenom)}.{ascii_min(nom)}"
            ville, quartier = rng.choice(LIEUX)
            u = Utilisateur(username=username, prenom=prenom, nom=nom, email=f"{username}@exemple.cm", role="adherent",
                            telephone="6" + rng.choice(["50", "55", "70", "75", "77", "80", "90", "99"]) + f"{rng.randint(0, 999999):06d}",
                            adresse=f"{quartier}, {ville}", numero_carte=services.generer_numero_carte(), statut="actif",
                            date_expiration=today + timedelta(days=rng.randint(1, services.params().duree_adhesion_jours)))
            u.set_password(MOT_DE_PASSE)
            u.save()
            Utilisateur.objects.filter(pk=u.pk).update(date_joined=dt(today - timedelta(days=rng.randint(30, 400))))
            self.adherents.append(u)
        # états particuliers : en attente de validation, adhésion expirée, bientôt expirée
        for u in self.adherents[-3:]:
            u.statut, u.date_expiration = "en_attente", None
            u.save(update_fields=["statut", "date_expiration"])
        for u in self.adherents[-6:-3]:
            u.date_expiration = today - timedelta(days=rng.randint(5, 90))
            u.save(update_fields=["date_expiration"])
        for u in self.adherents[-8:-6]:
            u.date_expiration = today + timedelta(days=rng.randint(2, 12))
            u.save(update_fields=["date_expiration"])
        self.actifs = [u for u in self.adherents if u.statut == "actif" and (u.date_expiration or today) >= today]
        self.stdout.write(f"Adhérents ajoutés : {len(self.adherents)} (dont 3 en attente, 3 expirés) ; personnel : 2")

    # ------------------------------------------------------------------- prêts
    def exemplaire_libre(self, livre_exclus=()):
        """Un exemplaire disponible d'un livre actif, au hasard."""
        qs = Exemplaire.objects.filter(statut="disponible", livre__actif=True).exclude(livre__in=livre_exclus).select_related("livre")
        ids = list(qs.values_list("pk", flat=True))
        return Exemplaire.objects.select_related("livre").get(pk=self.rng.choice(ids)) if ids else None

    def creer_emprunt(self, adh, ex, statut, debut, **kw):
        e = Emprunt.objects.create(adherent=adh, personnel=kw.pop("personnel", None) or self.rng.choice(self.staff), exemplaire=ex,
                                   date_emprunt=debut, statut=statut, **kw)
        Emprunt.objects.filter(pk=e.pk).update(date_demande=dt(debut - timedelta(days=self.rng.choice([0, 0, 1])), self.rng.randint(8, 17)))
        e.refresh_from_db()
        return e

    def emprunts(self):
        rng, today, p = self.rng, self.today, self.p
        livres_par_adh = {u.pk: set() for u in self.adherents}
        total = {k: 0 for k in ("rendu_ok", "rendu_retard", "perdu", "annule", "en_cours", "retard", "prete", "demande")}

        # 1) Historique : prêts rendus (à temps ou en retard avec sanction, payée ou non)
        for _ in range(110):
            adh = rng.choice([u for u in self.adherents if u.statut != "en_attente"])
            ex = self.exemplaire_libre()
            if not ex:
                break
            debut = today - timedelta(days=rng.randint(25, 210))
            prevue = debut + timedelta(days=p.duree_pret_jours)
            prolonge = rng.random() < 0.18
            if prolonge:
                prevue += timedelta(days=p.duree_prolongation_jours)
            retard = rng.choice([0] * 7 + [2, 4, 7, 12, 20, 55])
            effectif = min(prevue + timedelta(days=retard), today - timedelta(days=1))
            e = self.creer_emprunt(adh, ex, "rendu", debut, date_retour_prevue=prevue, date_retour_effective=effectif,
                                   nb_prolongations=1 if prolonge else 0)
            if e.jours_retard > 0:
                services._appliquer_sanction(e)
                e.refresh_from_db()
                if e.statut_paiement == "impayee" and rng.random() < 0.8:
                    e.statut_paiement = "payee"
                    e.save(update_fields=["statut_paiement"])
                elif e.statut_paiement == "impayee" and rng.random() < 0.5:
                    e.statut_paiement = "annulee"
                    e.save(update_fields=["statut_paiement"])
                total["rendu_retard"] += 1
            else:
                total["rendu_ok"] += 1
            # un livre rendu abîmé de temps en temps, avec supplément de dégâts
            if rng.random() < 0.05:
                e.exemplaire.etat_physique = "abime"
                e.exemplaire.save(update_fields=["etat_physique"])
                services._appliquer_sanction(e, Decimal(1000), "Livre rendu abîmé")

        # 2) Prêts perdus (sanction = prix + frais), exemplaire marqué perdu
        for _ in range(4):
            adh = rng.choice(self.actifs)
            ex = self.exemplaire_libre()
            debut = today - timedelta(days=rng.randint(40, 120))
            e = self.creer_emprunt(adh, ex, "perdu", debut, date_retour_prevue=debut + timedelta(days=p.duree_pret_jours),
                                   date_retour_effective=debut + timedelta(days=p.duree_pret_jours + rng.randint(1, 20)))
            services._appliquer_sanction(e, ex.livre.prix + p.frais_perte, "Livre perdu (prix + frais de dossier)")
            Exemplaire.objects.filter(pk=ex.pk).update(statut="perdu")
            total["perdu"] += 1

        # 3) Annulations (demande non retirée ou retirée par l'adhérent)
        for _ in range(8):
            adh = rng.choice(self.actifs)
            ex = self.exemplaire_libre()
            debut = today - timedelta(days=rng.randint(6, 90))
            self.creer_emprunt(adh, ex, "annule", debut, date_limite_retrait=debut + timedelta(days=p.delai_retrait_jours))
            total["annule"] += 1

        # 4) Situation actuelle : on respecte le quota (3 prêts actifs par adhérent) et « un exemplaire par livre »
        def actifs_de(u):
            return Emprunt.objects.filter(adherent=u, statut__in=Emprunt.ACTIFS).count()

        def candidat(avec_dette=False):
            sans_dette = [u for u in self.actifs if actifs_de(u) < 3 and services.montant_impaye(u) == 0
                          and not Emprunt.objects.filter(adherent=u, statut="retard").exists()]
            return rng.choice(sans_dette) if sans_dette else None

        def livre_deja(u):
            return list(Livre.objects.filter(exemplaires__emprunts__adherent=u, exemplaires__emprunts__statut__in=Emprunt.ACTIFS))

        for _ in range(22):   # en cours, certains bientôt à rendre, certains prolongés
            adh = candidat()
            ex = self.exemplaire_libre(livre_deja(adh)) if adh else None
            if not ex:
                continue
            debut = today - timedelta(days=rng.randint(0, 13))
            prevue = debut + timedelta(days=p.duree_pret_jours)
            prolonge = rng.random() < 0.2
            if prolonge:
                prevue += timedelta(days=p.duree_prolongation_jours)
            self.creer_emprunt(adh, ex, "en_cours", debut, date_retour_prevue=prevue, nb_prolongations=1 if prolonge else 0)
            Exemplaire.objects.filter(pk=ex.pk).update(statut="emprunte")
            total["en_cours"] += 1
        for _ in range(7):    # en retard (la sanction est calculée par maj_quotidienne)
            adh = candidat()
            ex = self.exemplaire_libre(livre_deja(adh)) if adh else None
            if not ex:
                continue
            debut = today - timedelta(days=rng.randint(17, 60))
            self.creer_emprunt(adh, ex, "retard", debut, date_retour_prevue=debut + timedelta(days=p.duree_pret_jours))
            Exemplaire.objects.filter(pk=ex.pk).update(statut="emprunte")
            total["retard"] += 1
        for _ in range(6):    # prêts préparés, à retirer au comptoir (ou à livrer)
            adh = candidat()
            ex = self.exemplaire_libre(livre_deja(adh)) if adh else None
            if not ex:
                continue
            debut = today - timedelta(days=rng.randint(0, 1))
            adresse = f"{adh.adresse}, porte {rng.randint(1, 40)}" if rng.random() < 0.3 else ""
            self.creer_emprunt(adh, ex, "prete", debut, date_limite_retrait=today + timedelta(days=rng.randint(1, p.delai_retrait_jours)),
                               adresse_livraison=adresse)
            Exemplaire.objects.filter(pk=ex.pk).update(statut="reserve")
            total["prete"] += 1
        for _ in range(6):    # demandes en ligne reçues, pas encore traitées
            adh = candidat()
            ex = self.exemplaire_libre(livre_deja(adh)) if adh else None
            if not ex:
                continue
            adresse = f"{adh.adresse}, porte {rng.randint(1, 40)}" if rng.random() < 0.35 else ""
            e = self.creer_emprunt(adh, ex, "demande", today, adresse_livraison=adresse, personnel=self.staff[0])
            Emprunt.objects.filter(pk=e.pk).update(personnel=None)
            Exemplaire.objects.filter(pk=ex.pk).update(statut="reserve")
            total["demande"] += 1

        # 5) Adhérents suspendus après un retard récent (rendu en retard il y a quelques jours)
        suspendus = [u for u in self.actifs if actifs_de(u) == 0][:2]
        for u in suspendus:
            ex = self.exemplaire_libre()
            retour = today - timedelta(days=rng.randint(1, 3))
            prevue = retour - timedelta(days=rng.randint(6, 12))
            e = self.creer_emprunt(u, ex, "rendu", prevue - timedelta(days=p.duree_pret_jours), date_retour_prevue=prevue,
                                   date_retour_effective=retour)
            services._appliquer_sanction(e)
            u.statut, u.suspendu_jusqu = "suspendu", today + timedelta(days=rng.randint(3, 10))
            u.save(update_fields=["statut", "suspendu_jusqu"])
        self.stdout.write("Prêts ajoutés : " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in total.items()))

    # ------------------------------------------------------------------ achats
    def lignes_aleatoires(self, jusqua_stock=True):
        rng = self.rng
        livres = list(Livre.objects.filter(actif=True, stock_vente__gt=0))
        rng.shuffle(livres)
        out = []
        for l in livres[:rng.choice([1, 1, 2, 2, 3])]:
            out.append((l, rng.randint(1, min(3, l.stock_vente))))
        return out

    def creer_achat(self, jour, statut, canal="comptoir", mode_reception="retrait", adherent=None, invite=None,
                    mode_paiement="", paye=False, annule=False, **kw):
        rng = self.rng
        lignes = self.lignes_aleatoires()
        if not lignes:
            return None
        invite = invite or {}
        a = Achat.objects.create(
            adherent=adherent, canal=canal, mode_reception=mode_reception, statut=statut,
            mode_paiement=mode_paiement if paye else "", statut_paiement="annule" if annule else ("paye" if paye else "en_attente"),
            reference_paiement=f"MM-{rng.randint(10**7, 10**8 - 1)}" if paye and mode_paiement == "mobile" else "",
            date_paiement=dt(jour, rng.randint(9, 17)) if paye else None,
            client_prenom=invite.get("prenom", ""), client_nom=invite.get("nom", ""),
            client_email=invite.get("email", ""), client_telephone=invite.get("telephone", ""), **kw)
        Achat.objects.filter(pk=a.pk).update(date_achat=dt(jour, rng.randint(8, 18), rng.randint(0, 59)),
                                             reference=f"BF-{jour:%Y%m%d}-{uuid4().hex[:8].upper()}")
        for livre, q in lignes:
            LigneAchat.objects.create(achat=a, livre=livre, quantite=q, prix_applique=livre.prix)
            if not annule:   # le stock n'est restitué que pour un achat annulé
                Livre.objects.filter(pk=livre.pk).update(stock_vente=livre.stock_vente - q)
                livre.stock_vente -= q
        return a

    def invite(self):
        rng = self.rng
        prenom, nom = rng.choice(PRENOMS), rng.choice(NOMS)
        return {"prenom": prenom, "nom": nom, "email": f"{ascii_min(prenom)}.{ascii_min(nom)}{rng.randint(1, 99)}@mail.cm",
                "telephone": "6" + rng.choice(["50", "70", "75", "77", "90", "99"]) + f"{rng.randint(0, 999999):06d}"}

    def achats(self):
        rng, today, p = self.rng, self.today, self.p
        n = {"comptoir": 0, "ligne_terminee": 0, "annule": 0, "actifs": 0}
        # Comptoir : adhérents ou clients de passage, tous modes de paiement
        for _ in range(38):
            jour = today - timedelta(days=rng.randint(0, 150))
            mode = rng.choice(["especes", "especes", "mobile", "mobile", "carte"])
            adh = rng.choice(self.adherents) if rng.random() < 0.55 else None
            if self.creer_achat(jour, "terminee", "comptoir", adherent=adh, invite=None if adh else self.invite(), mode_paiement=mode, paye=True):
                n["comptoir"] += 1
        # En ligne terminés (retrait ou livraison), avec ou sans compte
        for _ in range(26):
            jour = today - timedelta(days=rng.randint(6, 160))
            livraison = rng.random() < 0.4
            adh = rng.choice(self.adherents) if rng.random() < 0.55 else None
            a = self.creer_achat(jour, "terminee", "en_ligne", "livraison" if livraison else "retrait", adherent=adh,
                                 invite=None if adh else self.invite(), mode_paiement=rng.choice(["especes", "mobile", "mobile"]), paye=True,
                                 adresse_livraison=f"{rng.choice(LIEUX)[1]}, {rng.choice(LIEUX)[0]}" if livraison else "")
            n["ligne_terminee"] += 1 if a else 0
        # Annulés (stock restitué)
        for _ in range(9):
            jour = today - timedelta(days=rng.randint(6, 120))
            adh = rng.choice(self.adherents) if rng.random() < 0.5 else None
            if self.creer_achat(jour, "annulee", "en_ligne", adherent=adh, invite=None if adh else self.invite(), annule=True):
                n["annule"] += 1
        # Commandes en cours : en attente, prêtes à retirer, en livraison
        for statut, nb in (("en_attente", 7), ("prete", 5), ("en_livraison", 4)):
            for _ in range(nb):
                jour = today - timedelta(days=rng.randint(0, 2))
                livraison = statut == "en_livraison" or (statut != "prete" and rng.random() < 0.4)
                adh = rng.choice(self.actifs) if rng.random() < 0.5 else None
                limite = None if statut == "en_livraison" else today + timedelta(days=rng.randint(1, p.delai_retrait_jours))
                a = self.creer_achat(jour, statut, "en_ligne", "livraison" if livraison else "retrait", adherent=adh,
                                     invite=None if adh else self.invite(), date_limite_retrait=limite,
                                     adresse_livraison=f"{rng.choice(LIEUX)[1]}, {rng.choice(LIEUX)[0]}" if livraison else "")
                n["actifs"] += 1 if a else 0
        self.stdout.write(f"Achats ajoutés : {n['comptoir']} au comptoir, {n['ligne_terminee']} en ligne terminés, "
                          f"{n['annule']} annulés, {n['actifs']} en cours")

    def rapport(self):
        self.stdout.write(self.style.SUCCESS("Jeu de données massif créé."))
        for m in (Utilisateur, Livre, Exemplaire, Emprunt, Achat, LigneAchat):
            self.stdout.write(f"  {m.__name__:12} {m.objects.count()}")
        self.stdout.write(f"Mot de passe de tous les nouveaux comptes : {MOT_DE_PASSE}")
