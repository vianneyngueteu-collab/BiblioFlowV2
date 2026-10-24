"""Règles métier de la bibliothèque (prêts, sanctions, commandes en ligne, achats)."""
import re
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from .models import Achat, Emprunt, Exemplaire, LigneAchat, Livre, Utilisateur

HORS_CIRCUIT = ("perdu", "retire")


def params():
    """Règles de la bibliothèque (réglées dans settings.BIBLIO)."""
    d = dict(settings.BIBLIO)
    for cle in ("amende_par_jour", "amende_plafond", "frais_perte"):
        d[cle] = Decimal(str(d[cle]))
    return SimpleNamespace(**d)


def fmt(d):
    return d.strftime("%d/%m/%Y")


def generer_numero_carte():
    n = 1001
    existants = set(Utilisateur.objects.filter(numero_carte__startswith="ADH-").values_list("numero_carte", flat=True))
    while f"ADH-{n}" in existants:
        n += 1
    return f"ADH-{n}"


# ---------- Sanctions ----------
def montant_amende(jours):
    p = params()
    montant = p.amende_par_jour * jours
    if p.amende_plafond and p.amende_plafond > 0:
        montant = min(montant, p.amende_plafond)
    return montant


def montant_impaye(adherent):
    return (Emprunt.objects.filter(adherent=adherent, statut_paiement="impayee")
            .aggregate(t=Sum("montant_sanction"))["t"] or Decimal(0))


def _appliquer_sanction(e, supplement=Decimal(0), motif_supp=""):
    """Calcule la sanction de l'emprunt : amende de retard + éventuel supplément (perte, dégâts).
    - sanction payée : plus rien ne change ;
    - amende de retard annulée par l'administrateur : le retard n'est plus compté, mais un supplément
      (livre perdu, dégâts) s'applique quand même et rouvre la sanction."""
    if e.statut_paiement == "payee":
        return None
    retard_annule = e.statut_paiement == "annulee"
    jours = 0 if retard_annule else e.jours_retard
    montant = (montant_amende(jours) if jours > 0 else Decimal(0)) + supplement
    if montant <= 0:
        return None
    motifs = [f"Retard de {jours} jour(s)"] if jours > 0 else []
    if motif_supp:
        motifs.append(motif_supp)
    if retard_annule:
        motifs.append("amende de retard annulée")
    e.montant_sanction, e.motif_sanction, e.statut_paiement = montant, " + ".join(motifs), "impayee"
    if not e.date_sanction or retard_annule:
        e.date_sanction = timezone.now()
    e.save(update_fields=["montant_sanction", "motif_sanction", "statut_paiement", "date_sanction"])
    return e


def maj_quotidienne():
    """Retards et amendes, fins de suspension, demandes prêtes non retirées. Idempotent."""
    today = timezone.localdate()
    en_retard = Emprunt.objects.filter(statut__in=Emprunt.OUVERTS, date_retour_prevue__lt=today)
    for e in en_retard.select_related("adherent", "exemplaire__livre"):
        if e.statut == "en_cours":
            e.statut = "retard"
            e.save(update_fields=["statut"])
        _appliquer_sanction(e)
    Utilisateur.objects.filter(statut="suspendu", suspendu_jusqu__lt=today).update(statut="actif", suspendu_jusqu=None)
    limite = today - timedelta(days=params().delai_retrait_jours)
    for e in Emprunt.objects.filter(statut="prete").filter(
            Q(date_limite_retrait__lt=today) | Q(date_limite_retrait__isnull=True, date_emprunt__lt=limite)):
        annuler_emprunt(e)
    # Achats en ligne : non préparés dans le délai, ou prêts à retirer mais non retirés -> le stock est restitué.
    # (Une livraison déjà préparée n'est jamais annulée automatiquement.)
    expires = Achat.objects.filter(canal="en_ligne", date_limite_retrait__lt=today).filter(
        Q(statut="en_attente") | Q(statut="prete", mode_reception="retrait"))
    for a in expires:
        annuler_achat(a)


# ---------- Règles d'éligibilité ----------
def verifier_adherent(adherent):
    """Lève ValueError si l'adhérent n'a pas le droit d'emprunter."""
    today = timezone.localdate()
    if not adherent.numero_carte:
        raise ValueError("Ce compte n'est pas un compte adhérent.")
    if adherent.statut == "en_attente":
        raise ValueError("Votre adhésion n'a pas encore été validée : déclarez votre cotisation puis présentez-vous à la bibliothèque.")
    if not adherent.date_expiration:
        raise ValueError("Aucune cotisation active n’est enregistrée. Faites vérifier votre paiement à la bibliothèque.")
    if adherent.date_expiration < today:
        raise ValueError("Votre adhésion a expiré : renouvelez-la au comptoir de la bibliothèque.")
    if adherent.suspendu_jusqu and adherent.suspendu_jusqu >= today:
        raise ValueError(f"Vos emprunts sont suspendus jusqu'au {fmt(adherent.suspendu_jusqu)} (retard précédent).")
    dette = montant_impaye(adherent)
    if dette > 0:
        raise ValueError(f"Vous avez {dette:.0f} FCFA de sanctions impayées : réglez-les au comptoir pour emprunter.")
    if Emprunt.objects.filter(adherent=adherent, statut__in=Emprunt.OUVERTS, date_retour_prevue__lt=today).exists():
        raise ValueError("Vous avez un livre en retard : rapportez-le avant d'emprunter à nouveau.")


def nb_emprunts_actifs(adherent):
    return Emprunt.objects.filter(adherent=adherent, statut__in=Emprunt.ACTIFS).count()


def verifier_quota(adherent, nb=1):
    maxi = params().max_emprunts
    actifs = nb_emprunts_actifs(adherent)
    if actifs + nb > maxi:
        raise ValueError(f"Limite de {maxi} emprunts simultanés atteinte (vous en avez déjà {actifs}, "
                         f"demandes en cours comprises).")


def deja_emprunte(adherent, livre):
    return Emprunt.objects.filter(adherent=adherent, exemplaire__livre=livre, statut__in=Emprunt.ACTIFS).exists()


# ---------- Exemplaires ----------
def liberer_exemplaire(ex):
    ex.refresh_from_db()
    if ex.statut not in HORS_CIRCUIT:
        ex.statut = "disponible"
        ex.save(update_fields=["statut"])


def attribuer_exemplaire(livre):
    """Met de côté un exemplaire disponible."""
    ex = Exemplaire.objects.select_for_update().filter(livre=livre, statut="disponible").first()
    if not ex:
        raise ValueError(f"« {livre.titre} » n'a plus d'exemplaire disponible.")
    ex.statut = "reserve"
    ex.save(update_fields=["statut"])
    return ex


# ---------- Prêts ----------
@transaction.atomic
def creer_emprunt_comptoir(adherent, code_barres, staff, jours=None):
    verifier_adherent(adherent)
    ex = Exemplaire.objects.select_for_update().select_related("livre").get(code_barres=code_barres)
    if ex.statut in HORS_CIRCUIT:
        raise ValueError("Cet exemplaire est retiré du fonds ou perdu.")
    if ex.statut == "reserve":
        dem = Emprunt.objects.filter(exemplaire=ex, statut__in=("demande", "prete")).first()
        if dem and dem.adherent_id == adherent.id:
            return remettre_emprunt(dem, staff, jours)
        raise ValueError("Cet exemplaire est mis de côté pour un autre adhérent.")
    if ex.statut != "disponible":
        raise ValueError("Exemplaire déjà emprunté ou indisponible.")
    verifier_quota(adherent, 1)
    if deja_emprunte(adherent, ex.livre):
        raise ValueError("Cet adhérent a déjà un exemplaire de ce livre.")
    today = timezone.localdate()
    e = Emprunt.objects.create(adherent=adherent, personnel=staff, exemplaire=ex, date_emprunt=today, statut="en_cours",
                               date_retour_prevue=today + timedelta(days=jours or params().duree_pret_jours))
    ex.statut = "emprunte"
    ex.save(update_fields=["statut"])
    return e


@transaction.atomic
def preparer_emprunt(e, staff):
    """Le personnel accepte la demande en ligne : le livre est prêt (à retirer ou à livrer)."""
    if e.statut != "demande":
        raise ValueError("Cette demande est déjà préparée.")
    e.statut, e.personnel, e.date_emprunt = "prete", staff, timezone.localdate()
    e.date_limite_retrait = timezone.localdate() + timedelta(days=params().delai_retrait_jours)
    e.save(update_fields=["statut", "personnel", "date_emprunt", "date_limite_retrait"])


@transaction.atomic
def remettre_emprunt(e, staff, jours=None):
    """Remise du livre à l'adhérent (au comptoir ou à domicile) : le prêt commence."""
    if e.statut not in ("demande", "prete"):
        raise ValueError("Cette demande n'est plus en attente.")
    verifier_adherent(e.adherent)
    today = timezone.localdate()
    e.statut, e.personnel, e.date_emprunt = "en_cours", staff, today
    e.date_retour_prevue = today + timedelta(days=jours or params().duree_pret_jours)
    e.date_limite_retrait = None
    e.save(update_fields=["statut", "personnel", "date_emprunt", "date_retour_prevue", "date_limite_retrait"])
    Exemplaire.objects.filter(pk=e.exemplaire_id).update(statut="emprunte")
    return e


@transaction.atomic
def annuler_emprunt(e):
    if e.statut not in ("demande", "prete"):
        raise ValueError("Cette demande ne peut plus être annulée.")
    e.statut = "annule"
    e.save(update_fields=["statut"])
    liberer_exemplaire(e.exemplaire)


@transaction.atomic
def enregistrer_retour(e, etat="bon", degats=0):
    """Clôt un prêt : calcule la sanction (retard, dégâts), suspend l'adhérent si besoin, remet le livre en rayon."""
    if e.statut not in Emprunt.OUVERTS:
        raise ValueError("Cet emprunt n'est pas en cours.")
    today, p = timezone.localdate(), params()
    e.date_retour_effective, e.statut = today, "rendu"
    e.save(update_fields=["date_retour_effective", "statut"])
    ex = e.exemplaire
    degats = Decimal(str(degats or 0))
    if etat == "abime":
        ex.etat_physique = "abime"
        ex.save(update_fields=["etat_physique"])
    motif = ("Livre rendu abîmé" if etat == "abime" else "Dégradation du livre") if degats > 0 else ""
    sanction = _appliquer_sanction(e, degats, motif)
    jours = e.jours_retard
    a = e.adherent
    if jours > 0 and p.coef_suspension > 0 and a.statut == "actif":
        fin = today + timedelta(days=jours * p.coef_suspension)
        if not a.suspendu_jusqu or a.suspendu_jusqu < fin:
            a.suspendu_jusqu, a.statut = fin, "suspendu"
            a.save(update_fields=["suspendu_jusqu", "statut"])
    liberer_exemplaire(ex)
    return sanction


@transaction.atomic
def prolonger(e):
    p, today = params(), timezone.localdate()
    if e.statut not in Emprunt.OUVERTS:
        raise ValueError("Cet emprunt n'est pas en cours.")
    if e.date_retour_prevue < today:
        raise ValueError("Ce livre est en retard : il doit être rapporté, il ne peut plus être prolongé.")
    if e.nb_prolongations >= p.max_prolongations:
        raise ValueError(f"Limite de {p.max_prolongations} prolongation(s) atteinte pour ce prêt.")
    e.date_retour_prevue += timedelta(days=p.duree_prolongation_jours)
    e.nb_prolongations += 1
    e.save(update_fields=["date_retour_prevue", "nb_prolongations"])
    return e


@transaction.atomic
def declarer_perdu(e):
    """Livre perdu : sanction = prix du livre + frais de dossier (+ retard accumulé)."""
    if e.statut not in Emprunt.OUVERTS:
        raise ValueError("Cet emprunt n'est pas en cours.")
    e.date_retour_effective, e.statut = timezone.localdate(), "perdu"
    e.save(update_fields=["date_retour_effective", "statut"])
    ex = e.exemplaire
    ex.statut = "perdu"
    ex.save(update_fields=["statut"])
    return _appliquer_sanction(e, ex.livre.prix + params().frais_perte, "Livre perdu (prix + frais de dossier)")


@transaction.atomic
def encaisser_sanction(e):
    if e.statut_paiement != "impayee":
        raise ValueError("Cette sanction n'est plus à payer.")
    if e.statut in Emprunt.OUVERTS:
        raise ValueError("Le montant n'est définitif qu'au retour du livre : enregistrez d'abord le retour.")
    e.statut_paiement = "payee"
    e.save(update_fields=["statut_paiement"])


@transaction.atomic
def annuler_sanction(e):
    if e.statut_paiement != "impayee":
        raise ValueError("Seules les sanctions impayées peuvent être annulées.")
    e.statut_paiement = "annulee"
    e.save(update_fields=["statut_paiement"])


# ---------- Commande en ligne ----------
def normaliser_telephone(t):
    return re.sub(r"\D", "", t or "")


def meme_telephone(a, b):
    """Compare deux numéros sur leurs 8 derniers chiffres (tolère l'indicatif +237)."""
    a, b = normaliser_telephone(a), normaliser_telephone(b)
    return len(a) >= 8 and len(b) >= 8 and a[-8:] == b[-8:]


def _echeance_achat_en_ligne():
    return timezone.localdate() + timedelta(days=params().delai_achat_en_ligne_jours)


def _livre_en_vente(livre_id, qte):
    """Verrouille le livre et vérifie qu'il est vendable en quantité qte."""
    livre = Livre.objects.select_for_update().get(pk=livre_id)
    if not livre.actif:
        raise ValueError(f"« {livre.titre} » n'est plus disponible à la vente.")
    if qte > livre.stock_vente:
        raise ValueError(f"Stock insuffisant pour « {livre.titre} » ({livre.stock_vente} en vente).")
    return livre


def _vendre(achat, livre, qte):
    livre.stock_vente -= qte
    livre.save(update_fields=["stock_vente"])
    LigneAchat.objects.create(achat=achat, livre=livre, quantite=qte, prix_applique=livre.prix)


@transaction.atomic
def passer_commande(adherent, lignes, mode, adresse=""):
    """lignes : liste de (livre_id, type, quantité). Les emprunts deviennent des demandes (exemplaire mis de côté),
    les achats forment un Achat en ligne (stock mis de côté). Retourne (emprunts, achat)."""
    if not lignes:
        raise ValueError("Votre panier est vide.")
    if not adherent.numero_carte:
        raise ValueError("Seuls les adhérents peuvent emprunter.")
    if mode == "livraison" and not adresse.strip():
        raise ValueError("Indiquez l'adresse de livraison.")
    mode = "livraison" if mode == "livraison" else "retrait"
    adresse = adresse.strip() if mode == "livraison" else ""
    nb_emprunts = sum(1 for _, t, _ in lignes if t == "emprunt")
    if nb_emprunts:
        verifier_adherent(adherent)
        verifier_quota(adherent, nb_emprunts)
    emprunts, achat = [], None
    for livre_id, type_, qte in lignes:
        if type_ == "emprunt":
            livre = Livre.objects.select_for_update().get(pk=livre_id)
            if not livre.actif:
                raise ValueError(f"« {livre.titre} » n'est plus proposé à l'emprunt.")
            if deja_emprunte(adherent, livre):
                raise ValueError(f"Vous avez déjà « {livre.titre} » (emprunt ou demande en cours).")
            ex = attribuer_exemplaire(livre)
            emprunts.append(Emprunt.objects.create(adherent=adherent, exemplaire=ex, statut="demande",
                                                   adresse_livraison=adresse))
        else:
            qte = max(1, int(qte))
            livre = _livre_en_vente(livre_id, qte)
            if achat is None:
                # l'identité d'un adhérent vient de son compte : aucune copie dans client_*
                achat = Achat.objects.create(adherent=adherent, canal="en_ligne", mode_reception=mode,
                                             adresse_livraison=adresse, statut_paiement="en_attente",
                                             date_limite_retrait=_echeance_achat_en_ligne())
            _vendre(achat, livre, qte)
    return emprunts, achat


@transaction.atomic
def passer_achat_invite(prenom, nom, email, telephone, lignes, mode="retrait", adresse=""):
    """Achat sans compte adhérent, avec des garde-fous contre les commandes abusives."""
    p = params()
    if not lignes:
        raise ValueError("Votre panier est vide.")
    if mode not in ("retrait", "livraison"):
        raise ValueError("Mode de réception invalide.")
    if mode == "livraison" and not adresse.strip():
        raise ValueError("Indiquez l'adresse de livraison.")
    if len(normaliser_telephone(telephone)) < 8:
        raise ValueError("Indiquez un numéro de téléphone valide : la bibliothèque vous y joindra.")
    total_exemplaires = sum(max(1, int(q)) for _, q in lignes)
    if total_exemplaires > p.max_exemplaires_achat_invite:
        raise ValueError(f"Une commande sans compte est limitée à {p.max_exemplaires_achat_invite} livres. "
                         f"Pour davantage, créez un compte ou contactez la bibliothèque.")
    en_cours = [a for a in Achat.objects.filter(adherent__isnull=True, statut__in=Achat.ACTIFS)
                if meme_telephone(a.client_telephone, telephone)]
    if len(en_cours) >= p.max_achats_invites_actifs_par_telephone:
        raise ValueError("Vous avez déjà des commandes en cours avec ce numéro : attendez qu'elles soient "
                         "retirées ou annulées avant d'en passer une autre.")
    verifies = []
    for livre_id, qte in lignes:
        qte = max(1, int(qte))
        verifies.append((_livre_en_vente(livre_id, qte), qte))
    achat = Achat.objects.create(
        adherent=None, canal="en_ligne", mode_reception=mode,
        adresse_livraison=adresse.strip() if mode == "livraison" else "",
        client_prenom=prenom.strip(), client_nom=nom.strip(), client_email=email.strip(),
        client_telephone=telephone.strip(), statut_paiement="en_attente",
        date_limite_retrait=_echeance_achat_en_ligne())
    for livre, qte in verifies:
        _vendre(achat, livre, qte)
    return achat


def retrouver_achat(reference, telephone):
    """Suivi public d'une commande : la référence ET le téléphone de la commande doivent correspondre."""
    ref = (reference or "").strip()
    if not ref:
        return None
    a = Achat.objects.filter(reference__iexact=ref).select_related("adherent").first()
    if a and meme_telephone(a.client_telephone_effectif, telephone):
        return a
    return None


# ---------- Achats ----------
@transaction.atomic
def achat_comptoir(adherent, lignes, mode_paiement, client=None, reference_paiement=""):
    """Vente immédiate au comptoir, à un adhérent ou à un client de passage."""
    if not lignes:
        raise ValueError("Ajoutez au moins un livre.")
    if mode_paiement not in dict(Achat.MODES_PAIEMENT):
        raise ValueError("Choisissez le mode de paiement.")
    if mode_paiement == "mobile" and not (reference_paiement or "").strip():
        raise ValueError("Indiquez la référence de la transaction Mobile money.")
    # un adhérent est identifié par son compte : les coordonnées saisies à la main ne servent qu'aux clients de passage
    client = {} if adherent else (client or {})
    verifies = [(_livre_en_vente(livre_id, qte), qte) for livre_id, qte in lignes]
    achat = Achat.objects.create(adherent=adherent, canal="comptoir", mode_reception="retrait",
                                 mode_paiement=mode_paiement, reference_paiement=(reference_paiement or "").strip(),
                                 statut_paiement="paye", date_paiement=timezone.now(), statut="terminee",
                                 client_prenom=client.get("prenom", ""), client_nom=client.get("nom", ""),
                                 client_email=client.get("email", ""), client_telephone=client.get("telephone", ""))
    for livre, qte in verifies:
        _vendre(achat, livre, qte)
    return achat


@transaction.atomic
def annuler_achat(a):
    if a.statut not in Achat.ACTIFS:
        raise ValueError("Cet achat ne peut plus être annulé.")
    for l in a.lignes.all():
        Livre.objects.filter(pk=l.livre_id).update(stock_vente=F("stock_vente") + l.quantite)
    a.statut, a.statut_paiement, a.date_limite_retrait = "annulee", "annule", None
    a.save(update_fields=["statut", "statut_paiement", "date_limite_retrait"])


@transaction.atomic
def avancer_achat(a, action, mode_paiement=None, reference_paiement=""):
    """Étapes d'un achat en ligne : preparer, expedier (livraison), remettre (paiement à la remise)."""
    if action == "preparer":
        if a.statut != "en_attente":
            raise ValueError("Cet achat est déjà préparé.")
        a.statut = "prete"
        a.date_limite_retrait = timezone.localdate() + timedelta(days=params().delai_retrait_jours)
    elif action == "expedier":
        if a.statut != "prete" or not a.livraison:
            raise ValueError("Seul un achat prêt, à livrer, peut partir en livraison.")
        a.statut, a.date_limite_retrait = "en_livraison", None
    elif action == "remettre":
        if a.statut not in ("prete", "en_livraison"):
            raise ValueError("L'achat doit d'abord être préparé.")
        if mode_paiement not in dict(Achat.MODES_PAIEMENT):
            raise ValueError("Choisissez le mode de paiement.")
        if mode_paiement == "mobile" and not (reference_paiement or "").strip():
            raise ValueError("Indiquez la référence de la transaction Mobile money.")
        a.statut, a.mode_paiement, a.reference_paiement = "terminee", mode_paiement, (reference_paiement or "").strip()
        a.statut_paiement, a.date_paiement, a.date_limite_retrait = "paye", timezone.now(), None
    else:
        raise ValueError("Action inconnue.")
    a.save()
