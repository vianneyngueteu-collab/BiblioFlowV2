"""Tests des corrections 1 à 12 (audit du 8 octobre)."""
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django.utils.html import escape
from django.utils import timezone

from . import services
from .models import Achat, Emprunt, Livre, Utilisateur
from .tests import BDD, MATHS, PY, SVT, BaseTest


def texte(resp):
    return re.sub(r"<script.*?</script>", "", resp.content.decode(), flags=re.S)


class CorrectionsBase(BaseTest):
    def ajouter(self, livre, type_="achat", qte=1):
        return self.client.post(reverse("panier_action", args=["ajouter"]), {"livre": livre.pk, "type": type_, "quantite": qte})

    def commande_invite(self, livre=None, qte=1, tel="699123456", mode="retrait", adresse="", **extra):
        self.client.logout()
        self.ajouter(livre or self.livre(MATHS), "achat", qte)
        data = {"prenom": "Paul", "nom": "Invité", "telephone": tel, "email": "", "mode": mode, "adresse": adresse}
        data.update(extra)
        return self.client.post(reverse("commander"), data)


# ---------------------------------------------------------------- 1
class Point1SanctionAnnulee(BaseTest):
    def setUp(self):
        super().setUp()
        self.retard = Emprunt.objects.get(adherent__username="lecteur2")
        self.login("admin")
        self.client.post(reverse("sanction_action", args=[self.retard.pk, "annuler"]))

    def test_perdu_apres_annulation_ne_plante_plus_et_facture_la_perte(self):
        r = self.client.post(reverse("emprunt_action", args=[self.retard.pk, "perdu"]))
        self.assertEqual(r.status_code, 302)
        e = Emprunt.objects.get(pk=self.retard.pk)
        self.assertEqual(e.statut, "perdu")
        self.assertEqual((e.montant_sanction, e.statut_paiement), (self.livre(PY).prix + Decimal("500"), "impayee"))
        self.assertIn("perdu", e.motif_sanction)
        self.assertIn("annulée", e.motif_sanction)  # on garde la trace que l'amende de retard a été annulée

    def test_degats_apres_annulation_ne_sont_plus_perdus(self):
        self.client.post(reverse("emprunt_action", args=[self.retard.pk, "retour"]), {"etat": "abime", "degats": "3000"})
        e = Emprunt.objects.get(pk=self.retard.pk)
        self.assertEqual((e.montant_sanction, e.statut_paiement), (Decimal("3000"), "impayee"))

    def test_retour_simple_apres_annulation_ne_cree_pas_de_sanction(self):
        self.client.post(reverse("emprunt_action", args=[self.retard.pk, "retour"]), {"etat": "bon"})
        self.assertEqual(Emprunt.objects.get(pk=self.retard.pk).statut_paiement, "annulee")

    def test_perdu_sans_prix_ni_frais_ne_plante_pas(self):
        e = Emprunt.objects.get(adherent__username="etudiant")
        Livre.objects.filter(pk=e.exemplaire.livre_id).update(prix=0)
        with override_settings(BIBLIO={**settings.BIBLIO, "frais_perte": 0}):
            self.assertEqual(self.client.post(reverse("emprunt_action", args=[e.pk, "perdu"])).status_code, 302)
        self.assertEqual(Emprunt.objects.get(pk=e.pk).statut, "perdu")


# ---------------------------------------------------------------- 2
class Point2AbusEtExpiration(CorrectionsBase):
    def test_commande_invite_non_preparee_expire_et_restitue_le_stock(self):
        l = self.livre(MATHS)
        stock = l.stock_vente
        self.commande_invite(l, qte=stock if stock <= 10 else 10)
        a = Achat.objects.get()
        self.assertEqual(a.date_limite_retrait, timezone.localdate() + timedelta(days=5))
        l.refresh_from_db()
        self.assertLess(l.stock_vente, stock)
        Achat.objects.filter(pk=a.pk).update(date_limite_retrait=timezone.localdate() - timedelta(days=1))
        services.maj_quotidienne()
        a.refresh_from_db(); l.refresh_from_db()
        self.assertEqual((a.statut, a.statut_paiement, l.stock_vente), ("annulee", "annule", stock))

    def test_commande_prete_a_retirer_expire_mais_pas_une_livraison_en_cours(self):
        self.commande_invite()
        self.commande_invite(self.livre(SVT), tel="677000111")
        retrait, livraison = Achat.objects.order_by("id")
        self.login("bibliothecaire")
        services.avancer_achat(retrait, "preparer")
        Achat.objects.filter(pk=livraison.pk).update(mode_reception="livraison", adresse_livraison="Akwa")
        livraison.refresh_from_db()
        services.avancer_achat(livraison, "preparer")
        services.avancer_achat(livraison, "expedier")
        Achat.objects.filter(pk=retrait.pk).update(date_limite_retrait=timezone.localdate() - timedelta(days=1))
        services.maj_quotidienne()
        retrait.refresh_from_db(); livraison.refresh_from_db()
        self.assertEqual((retrait.statut, livraison.statut), ("annulee", "en_livraison"))

    def test_preparer_remet_l_echeance_a_zero_puis_la_remise_la_supprime(self):
        self.commande_invite()
        a = Achat.objects.get()
        services.avancer_achat(a, "preparer")
        self.assertEqual(a.date_limite_retrait, timezone.localdate() + timedelta(days=3))
        services.avancer_achat(a, "remettre", "especes")
        self.assertIsNone(a.date_limite_retrait)

    def test_quantite_maximale_par_commande_invite(self):
        self.commande_invite(self.livre(MATHS), qte=11)
        self.assertEqual(Achat.objects.count(), 0)

    def test_commandes_simultanees_limitees_par_telephone(self):
        for livre in (MATHS, SVT):
            self.commande_invite(self.livre(livre), tel="699 12 34 56")
        self.commande_invite(self.livre(BDD), tel="+237 699123456")  # même numéro écrit autrement
        self.assertEqual(Achat.objects.count(), 2)

    def test_limite_par_adresse_ip_et_par_heure(self):
        with override_settings(BIBLIO={**settings.BIBLIO, "max_achats_invites_par_ip_heure": 3}):
            for i in range(5):
                self.commande_invite(tel=f"69900000{i}")
        self.assertEqual(Achat.objects.count(), 3)

    def test_piege_a_robots(self):
        self.commande_invite(site_web="http://spam.example")
        self.assertEqual(Achat.objects.count(), 0)

    def test_telephone_invalide_refuse(self):
        self.commande_invite(tel="12")
        self.assertEqual(Achat.objects.count(), 0)


# ---------------------------------------------------------------- 3 et 4
class Point3et4AffichageEtSuivi(CorrectionsBase):
    def test_tableau_de_bord_sans_none_pour_un_invite(self):
        self.commande_invite()
        self.login("bibliothecaire")
        h = texte(self.client.get(reverse("tableau_bord")))
        self.assertNotIn("None", h)
        self.assertIn("Paul Invité", h)

    def test_meme_reference_partout(self):
        r = self.commande_invite()
        a = Achat.objects.get()
        self.assertIn(a.reference, texte(self.client.get(r.url)))
        self.login("bibliothecaire")
        for page in (reverse("achats"), reverse("commandes"), reverse("achat_detail", args=[a.pk]), reverse("tableau_bord")):
            self.assertIn(a.reference, texte(self.client.get(page)), page)

    def test_suivi_par_reference_et_telephone(self):
        self.commande_invite(tel="+237 699 12 34 56")
        a = Achat.objects.get()
        self.client.logout()
        ok = self.client.post(reverse("suivi_achat"), {"reference": a.reference.lower(), "telephone": "699123456"})
        self.assertContains(ok, "pas encore préparé")
        mauvais = self.client.post(reverse("suivi_achat"), {"reference": a.reference, "telephone": "677000000"})
        self.assertNotContains(mauvais, "pas encore préparé")
        self.assertContains(mauvais, "Aucune commande ne correspond")

    def test_suivi_accessible_depuis_un_autre_navigateur_et_montre_l_avancement(self):
        self.commande_invite()
        a = Achat.objects.get()
        services.avancer_achat(a, "preparer")
        self.client.logout()
        self.client.cookies.clear()
        r = self.client.post(reverse("suivi_achat"), {"reference": a.reference, "telephone": "699123456"})
        self.assertContains(r, "Votre commande est prête")

    def test_suivi_limite_contre_les_essais_repetes(self):
        with override_settings(BIBLIO={**settings.BIBLIO, "max_suivis_par_ip_heure": 2}):
            for _ in range(4):
                r = self.client.post(reverse("suivi_achat"), {"reference": "BF-X", "telephone": "699123456"})
        self.assertContains(r, "Trop de recherches")

    def test_suivi_d_une_commande_d_adherent(self):
        self.login("etudiant")
        self.ajouter(self.livre(MATHS))
        self.client.post(reverse("commander"), {"mode": "retrait", "telephone": "690000000"})
        a = Achat.objects.get()
        self.client.logout()
        r = self.client.post(reverse("suivi_achat"), {"reference": a.reference, "telephone": "690000000"})
        self.assertContains(r, a.reference)


# ---------------------------------------------------------------- 5
class Point5AchatAnnule(CorrectionsBase):
    def test_un_achat_annule_n_est_plus_a_payer(self):
        self.commande_invite()
        a = Achat.objects.get()
        self.login("bibliothecaire")
        self.client.post(reverse("achat_detail", args=[a.pk]), {"action": "annuler"})
        a.refresh_from_db()
        self.assertEqual(a.statut_paiement, "annule")
        h = texte(self.client.get(reverse("achats"), {"statut": "annulee"}))
        self.assertNotIn("À payer", h)
        self.assertIn("Annulé", h)


# ---------------------------------------------------------------- 7
class Point7SourcesDeVerite(CorrectionsBase):
    def test_livraison_depend_uniquement_du_mode_de_reception(self):
        self.assertTrue(Achat(mode_reception="livraison", adresse_livraison="").livraison)
        self.assertFalse(Achat(mode_reception="retrait", adresse_livraison="Akwa").livraison)

    def test_commande_d_adherent_ne_copie_pas_son_identite(self):
        self.login("etudiant")
        self.ajouter(self.livre(MATHS))
        self.client.post(reverse("commander"), {"mode": "livraison", "adresse": "Akwa", "telephone": "690000000"})
        a = Achat.objects.get()
        self.assertEqual((a.client_prenom, a.client_nom, a.client_email, a.client_telephone), ("", "", "", ""))
        self.assertTrue(a.livraison)
        etudiant = self.user("etudiant")
        self.assertEqual((a.client_nom_complet, a.client_email_effectif), (str(etudiant), etudiant.email))

    def test_comptoir_avec_carte_ignore_les_coordonnees_saisies(self):
        self.login("bibliothecaire")
        et = self.user("etudiant")
        self.client.post(reverse("achat_nouveau"), {
            "carte": et.numero_carte, "livre": [self.livre(MATHS).pk], "quantite": ["1"], "mode_paiement": "especes",
            "prenom": "Autre", "nom": "Personne", "telephone": "677000000", "email": "autre@x.cm"})
        a = Achat.objects.get()
        self.assertEqual((a.client_prenom, a.client_email), ("", ""))
        h = texte(self.client.get(reverse("achat_detail", args=[a.pk])))
        self.assertIn(et.email, h)
        self.assertNotIn("autre@x.cm", h)

    def test_comptoir_sans_carte_exige_les_coordonnees(self):
        self.login("bibliothecaire")
        self.client.post(reverse("achat_nouveau"), {"livre": [self.livre(MATHS).pk], "quantite": ["1"], "mode_paiement": "especes"})
        self.assertEqual(Achat.objects.count(), 0)


# ---------------------------------------------------------------- 8
class Point8ChampsUtiles(CorrectionsBase):
    def test_mobile_money_exige_une_reference_a_la_remise(self):
        self.commande_invite()
        a = Achat.objects.get()
        self.login("bibliothecaire")
        url = reverse("achat_detail", args=[a.pk])
        self.client.post(url, {"action": "preparer"})
        self.client.post(url, {"action": "remettre", "mode_paiement": "mobile"})
        a.refresh_from_db()
        self.assertEqual(a.statut, "prete")
        self.client.post(url, {"action": "remettre", "mode_paiement": "mobile", "reference_paiement": "MP123456", "paiement_verifie": "on"})
        a.refresh_from_db()
        self.assertEqual((a.statut, a.reference_paiement, a.statut_paiement), ("terminee", "MP123456", "paye"))
        self.assertIn("MP123456", texte(self.client.get(url)))

    def test_mobile_money_au_comptoir_exige_une_reference(self):
        self.login("bibliothecaire")
        base = {"carte": self.user("etudiant").numero_carte, "livre": [self.livre(MATHS).pk], "quantite": ["1"],
                "mode_paiement": "mobile"}
        self.client.post(reverse("achat_nouveau"), base)
        self.assertEqual(Achat.objects.count(), 0)
        self.client.post(reverse("achat_nouveau"), {**base, "reference_paiement": "MP999", "paiement_verifie": "on"})
        self.assertEqual(Achat.objects.get().reference_paiement, "MP999")

    def test_isbn_et_description_renseignes_et_affiches(self):
        self.assertFalse(Livre.objects.filter(isbn__isnull=True).exists())
        self.assertFalse(Livre.objects.filter(description="").exists())
        l = self.livre(MATHS)
        h = texte(self.client.get(reverse("livre_detail", args=[l.pk])))
        self.assertIn(escape(l.description), h)
        self.assertIn(l.isbn, h)


# ---------------------------------------------------------------- 9
class Point9LivreMasque(CorrectionsBase):
    def test_livre_masque_disparait_partout(self):
        Livre.objects.filter(categorie="Science").update(actif=False)
        h = texte(self.client.get(reverse("accueil")))
        self.assertNotIn("cat=Science", h)
        self.assertIn(f"{Livre.objects.filter(actif=True).count()} titres", re.sub(r"\s+", " ", h))
        self.assertEqual(self.client.get(reverse("livre_detail", args=[self.livre(MATHS).pk])).status_code, 404)

    def test_services_refusent_un_livre_masque(self):
        l = self.livre(MATHS)
        Livre.objects.filter(pk=l.pk).update(actif=False)
        et = self.user("etudiant")
        with self.assertRaisesMessage(ValueError, "plus disponible à la vente"):
            services.passer_commande(et, [(l.pk, "achat", 1)], "retrait")
        with self.assertRaisesMessage(ValueError, "plus proposé à l'emprunt"):
            services.passer_commande(et, [(l.pk, "emprunt", 1)], "retrait")
        with self.assertRaisesMessage(ValueError, "plus disponible à la vente"):
            services.achat_comptoir(et, [(l.pk, 1)], "especes")
        self.assertEqual(Achat.objects.count(), 0)


# ---------------------------------------------------------------- 10
class Point10Vocabulaire(CorrectionsBase):
    def test_plus_aucun_mot_reservation_cote_public(self):
        self.ajouter(self.livre(BDD), "emprunt")
        pages = [reverse(n) for n in ("accueil", "catalogue", "panier", "login", "inscription", "suivi_achat")]
        pages.append(reverse("livre_detail", args=[self.livre(BDD).pk]))
        for page in pages:
            self.assertNotRegex(texte(self.client.get(page)).lower(), r"r[ée]serv", page)
        self.login("etudiant")
        for page in (reverse("mon_compte"), reverse("mes_commandes")):
            self.assertNotRegex(texte(self.client.get(page)).lower(), r"r[ée]serv", page)


# ---------------------------------------------------------------- 11
class Point11PanierVisiteur(CorrectionsBase):
    def setUp(self):
        super().setUp()
        self.ajouter(self.livre(BDD), "emprunt")
        self.ajouter(self.livre(MATHS), "achat")

    def test_le_panier_explique_et_propose_les_bons_boutons(self):
        h = texte(self.client.get(reverse("panier")))
        self.assertIn("Pour emprunter, il faut un compte adhérent", h)
        self.assertIn("Se connecter et continuer", h)
        self.assertIn("Acheter seulement les livres à vendre", h)
        self.assertNotIn("Commander sans inscription", h)

    def test_commander_avec_un_emprunt_renvoie_vers_la_connexion_avec_retour(self):
        r = self.client.get(reverse("commander"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("next=/commander/", r.url)

    def test_apres_connexion_on_revient_a_la_commande(self):
        r = self.client.post(reverse("login") + "?next=/commander/", {"username": "etudiant", "password": "Bibliotheque2026!",
                                                                    "next": "/commander/"})
        self.assertEqual(r.url, "/commander/")
        self.assertEqual(self.client.get("/commander/").status_code, 200)

    def test_apres_inscription_on_revient_a_la_commande(self):
        r = self.client.post(reverse("inscription") + "?next=/commander/", {
            "prenom": "Jean", "nom": "Test", "telephone": "699123456", "username": "jtest",
            "password1": "Xk93!pqLmz", "password2": "Xk93!pqLmz"})
        self.assertEqual(r.url, "/commander/")

    def test_acheter_seulement_retire_les_emprunts_puis_ouvre_la_commande_invite(self):
        r = self.client.post(reverse("panier_action", args=["retirer_emprunts"]), {"next": "/commander/"})
        self.assertEqual(r.url, "/commander/")
        self.assertEqual(list(self.client.session["panier"]), [f"{self.livre(MATHS).pk}:achat"])
        self.assertContains(self.client.get("/commander/"), "Acheter sans créer de compte")

    def test_redirection_externe_ignoree(self):
        r = self.client.post(reverse("panier_action", args=["retirer_emprunts"]), {"next": "https://evil.example/"})
        self.assertEqual(r.url, reverse("panier"))


# ---------------------------------------------------------------- 12
class Point12Personnel(CorrectionsBase):
    def test_un_membre_du_personnel_peut_acheter_en_ligne(self):
        self.login("bibliothecaire")
        self.ajouter(self.livre(MATHS))
        page = self.client.get(reverse("commander"))
        self.assertContains(page, "Acheter sans créer de compte")
        self.assertContains(page, 'value="Aline"')  # coordonnées préremplies
        r = self.client.post(reverse("commander"), {"prenom": "Aline", "nom": "Ndom", "telephone": "690000000",
                                                   "email": "", "mode": "retrait", "adresse": ""})
        a = Achat.objects.get()
        self.assertRedirects(r, reverse("confirmation_achat", args=[a.pk]))
        self.assertIsNone(a.adherent)

    def test_le_personnel_ne_peut_pas_emprunter_et_est_bien_informe(self):
        self.login("bibliothecaire")
        self.ajouter(self.livre(BDD), "emprunt")
        r = self.client.get(reverse("commander"), follow=True)
        self.assertEqual(r.redirect_chain[-1][0], reverse("panier"))
        self.assertContains(r, "peuvent emprunter")
        self.assertContains(r, "Retirer les emprunts du panier")
