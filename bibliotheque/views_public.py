"""Site public et espace adhérent : catalogue, panier, commande, inscription, compte."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import services
from .acces import lecteur_requis, redirection_sure
from .forms import AchatInviteForm, CommandeForm, CotisationAdhesionForm, InscriptionForm, SuiviCommandeForm
from .models import Achat, CotisationAdhesion, Emprunt, Exemplaire, Livre, Utilisateur


def _livres_avec_dispo():
    return Livre.objects.filter(actif=True).annotate(
        dispo=Count("exemplaires", filter=Q(exemplaires__statut="disponible"), distinct=True))


def _categories():
    return (Livre.objects.filter(actif=True).exclude(categorie="").values("categorie")
            .annotate(n=Count("id")).order_by("categorie"))


# ---------- Vitrine ----------
def accueil(request):
    return render(request, "bibliotheque/public/accueil.html", {
        "nouveautes": _livres_avec_dispo().order_by("-id")[:8],
        "categories": _categories(),
        "nb_livres": Livre.objects.filter(actif=True).count(),
        "nb_dispo": Exemplaire.objects.filter(statut="disponible", livre__actif=True).count(),
    })


def catalogue(request):
    q, cat, dispo = request.GET.get("q", "").strip(), request.GET.get("cat", ""), request.GET.get("dispo", "")
    livres = _livres_avec_dispo()
    if q:
        livres = livres.filter(Q(titre__icontains=q) | Q(auteur__icontains=q) | Q(categorie__icontains=q) | Q(isbn__icontains=q))
    if cat:
        livres = livres.filter(categorie=cat)
    if dispo == "pret":
        livres = livres.filter(dispo__gt=0)
    elif dispo == "achat":
        livres = livres.filter(stock_vente__gt=0)
    page = Paginator(livres.order_by("titre"), 12).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "bibliotheque/public/catalogue.html", {
        "page": page, "q": q, "cat": cat, "dispo": dispo, "categories": _categories(), "qs": params.urlencode()})


def livre_detail(request, pk):
    livre = get_object_or_404(_livres_avec_dispo(), pk=pk)
    emplacements = sorted({ex.emplacement for ex in livre.exemplaires.filter(statut="disponible") if ex.emplacement})
    ctx = {"livre": livre, "emplacements": emplacements,
           "similaires": _livres_avec_dispo().filter(categorie=livre.categorie).exclude(pk=pk)[:4] if livre.categorie else []}
    if request.user.is_authenticated and request.user.numero_carte:
        ctx["deja"] = services.deja_emprunte(request.user, livre)
    return render(request, "bibliotheque/public/livre.html", ctx)


# ---------- Inscription ----------
def inscription(request):
    if request.user.is_authenticated:
        return redirect("apres_connexion")
    form = InscriptionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d, p, today = form.cleaned_data, services.params(), timezone.localdate()
        valide = not p.validation_adhesion_requise
        u = Utilisateur.objects.create_user(
            username=d["username"], password=d["password1"], email=d["email"], nom=d["nom"], prenom=d["prenom"],
            telephone=d["telephone"], adresse=d["adresse"], role="adherent", numero_carte=services.generer_numero_carte(),
            statut="actif" if valide else "en_attente",
            date_expiration=today + timedelta(days=p.duree_adhesion_jours) if valide else None)
        login(request, u)
        if valide:
            messages.success(request, f"Bienvenue {u.prenom} ! Votre carte n° {u.numero_carte} est active.")
        else:
            messages.success(request, f"Compte créé, carte n° {u.numero_carte}. Passez à la bibliothèque pour valider "
                                      f"votre adhésion : vous pourrez alors emprunter.")
        return redirection_sure(request, "mon_compte")
    return render(request, "bibliotheque/public/inscription.html", {"form": form})


# ---------- Panier ----------
def _panier(request):
    return request.session.setdefault("panier", {})


def _lignes_panier(request):
    """Transforme le panier de session en lignes affichables."""
    lignes, total = [], 0
    for cle, qte in list(_panier(request).items()):
        livre_id, type_ = cle.split(":")
        livre = _livres_avec_dispo().filter(pk=livre_id).first()
        if not livre:
            _panier(request).pop(cle, None)
            request.session.modified = True
            continue
        sous = livre.prix * qte if type_ == "achat" else 0
        total += sous
        lignes.append({"cle": cle, "livre": livre, "type": type_, "quantite": qte, "sous_total": sous})
    return lignes, total


def panier(request):
    lignes, total = _lignes_panier(request)
    user = request.user if request.user.is_authenticated else None
    return render(request, "bibliotheque/public/panier.html", {
        "lignes": lignes, "total": total, "nb_emprunts": sum(1 for l in lignes if l["type"] == "emprunt"),
        "nb_achats": sum(1 for l in lignes if l["type"] == "achat"),
        "reste_quota": (services.params().max_emprunts - services.nb_emprunts_actifs(user))
        if user and user.numero_carte else None})


def panier_action(request, action):
    if request.method != "POST":
        return redirect("panier")
    pan = _panier(request)
    if action == "ajouter":
        livre = get_object_or_404(Livre, pk=request.POST.get("livre"), actif=True)
        type_ = request.POST.get("type")
        if type_ not in ("emprunt", "achat"):
            return redirect("catalogue")
        cle = f"{livre.pk}:{type_}"
        if type_ == "emprunt":
            if not Exemplaire.objects.filter(livre=livre, statut="disponible").exists():
                messages.error(request, f"« {livre.titre} » n'est pas disponible à l'emprunt pour le moment.")
                return redirect("livre_detail", pk=livre.pk)
            pan[cle] = 1
        else:
            try:
                qte = int(request.POST.get("quantite") or 1)
            except (TypeError, ValueError):
                qte = 1
            qte = max(1, min(qte, 100))
            if pan.get(cle, 0) + qte > livre.stock_vente:
                messages.error(request, f"Stock insuffisant : {livre.stock_vente} exemplaire(s) en vente.")
                return redirect("livre_detail", pk=livre.pk)
            pan[cle] = pan.get(cle, 0) + qte
        request.session.modified = True
        messages.success(request, f"« {livre.titre} » ajouté au panier ({'emprunt' if type_ == 'emprunt' else 'achat'}).")
        return redirection_sure(request, "panier")
    if action == "retirer":
        pan.pop(request.POST.get("cle", ""), None)
    elif action == "retirer_emprunts":
        for cle in [c for c in pan if c.endswith(":emprunt")]:
            pan.pop(cle)
        request.session.modified = True
        return redirection_sure(request, "panier")
    elif action == "vider":
        pan.clear()
    request.session.modified = True
    return redirect("panier")


def _cle_limite(request, nom):
    # NB : derrière un proxy inverse, configurer REMOTE_ADDR (sinon tous les visiteurs partagent le même quota).
    return f"biblio:{nom}:{request.META.get('REMOTE_ADDR', 'inconnu')}"


def _limite_atteinte(request, nom, maxi):
    return cache.get(_cle_limite(request, nom), 0) >= maxi


def _compter(request, nom, duree=3600):
    cle = _cle_limite(request, nom)
    try:
        cache.incr(cle)
    except ValueError:
        cache.set(cle, 1, duree)


def commander(request):
    """Finalise un panier. Les emprunts sont réservés aux adhérents ; les achats sont ouverts à tous
    (adhérent, visiteur, ou membre du personnel connecté) : sans carte, la commande se fait comme invité."""
    lignes, total = _lignes_panier(request)
    if not lignes:
        messages.info(request, "Votre panier est vide.")
        return redirect("catalogue")
    user = request.user if request.user.is_authenticated else None
    est_adherent = bool(user and user.numero_carte)
    contient_emprunt = any(l["type"] == "emprunt" for l in lignes)

    if contient_emprunt and not est_adherent:
        if user is None:  # on revient ici après la connexion ou l'inscription
            messages.info(request, "Connectez-vous avec votre compte adhérent pour emprunter. "
                                   "Pas encore de carte ? Inscrivez-vous. Vous pouvez aussi acheter sans compte "
                                   "en retirant les emprunts du panier.")
            return redirect_to_login(request.get_full_path())
        messages.error(request, "Seuls les comptes adhérents (avec une carte) peuvent emprunter. "
                                "Retirez les emprunts du panier pour acheter.")
        return redirect("panier")

    if est_adherent:
        form = CommandeForm(request.POST or None, initial={"telephone": user.telephone, "adresse": user.adresse})
        avertissement = None
        try:
            if contient_emprunt:
                services.verifier_adherent(user)
        except ValueError as e:
            avertissement = str(e)
        if request.method == "POST" and form.is_valid():
            d = form.cleaned_data
            try:
                items = [(l["livre"].pk, l["type"], l["quantite"]) for l in lignes]
                services.passer_commande(user, items, d["mode"], d["adresse"])
            except ValueError as e:
                messages.error(request, str(e))
            else:
                if d["telephone"] != user.telephone:
                    user.telephone = d["telephone"]
                    user.save(update_fields=["telephone"])
                request.session["panier"] = {}
                messages.success(request, "Commande enregistrée ! Nous la préparons : suivez-la ici.")
                return redirect("mes_commandes")
        return render(request, "bibliotheque/public/commander.html", {
            "form": form, "lignes": lignes, "total": total, "avertissement": avertissement, "invite": False})

    # Achat sans carte d'adhérent (visiteur, ou compte du personnel)
    initial = {"prenom": user.prenom, "nom": user.nom, "email": user.email, "telephone": user.telephone} if user else None
    form = AchatInviteForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        d, p = form.cleaned_data, services.params()
        if _limite_atteinte(request, "achat_invite", p.max_achats_invites_par_ip_heure):
            messages.error(request, "Trop de commandes ont été passées depuis votre connexion en peu de temps. "
                                    "Réessayez plus tard ou contactez la bibliothèque.")
        else:
            try:
                achat = services.passer_achat_invite(
                    d["prenom"], d["nom"], d["email"], d["telephone"],
                    [(l["livre"].pk, l["quantite"]) for l in lignes], d["mode"], d["adresse"])
            except ValueError as e:
                messages.error(request, str(e))
            else:
                _compter(request, "achat_invite")
                request.session["panier"] = {}
                request.session["dernier_achat_invite"] = achat.pk
                return redirect("confirmation_achat", pk=achat.pk)
    return render(request, "bibliotheque/public/commander.html", {
        "form": form, "lignes": lignes, "total": total, "avertissement": None, "invite": True})


def confirmation_achat(request, pk):
    """Confirmation publique limitée à l'achat créé pendant cette session."""
    if request.session.get("dernier_achat_invite") != pk:
        return redirect("accueil")
    achat = get_object_or_404(Achat.objects.prefetch_related("lignes__livre"), pk=pk)
    return render(request, "bibliotheque/public/confirmation_achat.html", {"achat": achat})


def suivi_achat(request):
    """Suivi d'une commande par sa référence et le téléphone indiqué à la commande (sans compte)."""
    p = services.params()
    form = SuiviCommandeForm(request.POST or None, initial={"reference": request.GET.get("reference", "")})
    achat = None
    if request.method == "POST" and form.is_valid():
        if _limite_atteinte(request, "suivi", p.max_suivis_par_ip_heure):
            messages.error(request, "Trop de recherches en peu de temps. Réessayez dans une heure.")
        else:
            _compter(request, "suivi")
            achat = services.retrouver_achat(form.cleaned_data["reference"], form.cleaned_data["telephone"])
            if achat is None:
                messages.error(request, "Aucune commande ne correspond à cette référence et à ce téléphone.")
    if achat:
        achat = Achat.objects.prefetch_related("lignes__livre").get(pk=achat.pk)
    return render(request, "bibliotheque/public/suivi_achat.html", {"form": form, "achat": achat})


# ---------- Espace adhérent ----------
@lecteur_requis
def mon_compte(request):
    services.maj_quotidienne()
    a = request.user
    emprunts = list(a.emprunts.filter(statut__in=Emprunt.ACTIFS).select_related("exemplaire__livre")
                    .order_by("date_retour_prevue", "id"))
    for e in emprunts:
        e.amende = services.montant_amende(e.jours_retard) if e.jours_retard else 0
    try:
        services.verifier_adherent(a)
        blocage = None
    except ValueError as e:
        blocage = str(e)
    return render(request, "bibliotheque/public/mon_compte.html", {
        "a": a, "emprunts": emprunts, "blocage": blocage,
        "sanctions": a.emprunts.filter(statut_paiement="impayee").select_related("exemplaire__livre"),
        "dette": services.montant_impaye(a),
        "historique": a.emprunts.filter(statut__in=("rendu", "perdu")).select_related("exemplaire__livre")
                       .order_by("-date_retour_effective")[:10],
        "cotisations": a.cotisations.all()[:10],
        "commandes_actives": a.emprunts.filter(statut__in=("demande", "prete")).count()
                              + a.achats.filter(statut__in=Achat.ACTIFS).count()})


@lecteur_requis
def mes_commandes(request):
    a = request.user
    return render(request, "bibliotheque/public/mes_commandes.html", {
        "demandes": a.emprunts.filter(statut__in=("demande", "prete", "annule")).select_related("exemplaire__livre")
                     .order_by("-id")[:20],
        "achats": a.achats.filter(canal="en_ligne").prefetch_related("lignes__livre")[:30]})


@lecteur_requis
def demande_annuler(request, pk):
    if request.method == "POST":
        e = get_object_or_404(Emprunt, pk=pk, adherent=request.user)
        try:
            services.annuler_emprunt(e)
            messages.info(request, "Demande d'emprunt annulée.")
        except ValueError as err:
            messages.error(request, str(err))
    return redirect("mes_commandes")


@lecteur_requis
def achat_annuler(request, pk):
    if request.method == "POST":
        a = get_object_or_404(Achat, pk=pk, adherent=request.user)
        if a.statut in ("en_attente", "prete"):
            try:
                services.annuler_achat(a)
                messages.info(request, f"Commande #{a.pk} annulée.")
            except ValueError as err:
                messages.error(request, str(err))
        else:
            messages.error(request, "Cette commande est déjà en livraison ou terminée : contactez la bibliothèque.")
    return redirect("mes_commandes")


@lecteur_requis
def emprunt_prolonger(request, pk):
    if request.method == "POST":
        e = get_object_or_404(Emprunt, pk=pk, adherent=request.user)
        try:
            services.prolonger(e)
            messages.success(request, f"Prêt prolongé : à rendre avant le {services.fmt(e.date_retour_prevue)}.")
        except ValueError as err:
            messages.error(request, str(err))
    return redirect("mon_compte")


# ---------- Cotisation mensuelle et renouvellement d'adhésion ----------
@lecteur_requis
def cotisation_nouvelle(request):
    """Enregistre une déclaration de paiement, sans activer automatiquement l'adhésion."""
    from django.db import IntegrityError, transaction

    p = services.params()
    form = CotisationAdhesionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        deja = CotisationAdhesion.objects.filter(
            operateur=data["operateur"],
            reference_transaction__iexact=data["reference_transaction"],
        ).exists()
        if deja:
            form.add_error("reference_transaction",
                           "Cette référence de transaction a déjà été déclarée.")
        else:
            try:
                with transaction.atomic():
                    CotisationAdhesion.objects.create(
                        adherent=request.user,
                        montant=p.cotisation_mensuelle_fcfa,
                        operateur=data["operateur"],
                        telephone_payeur=data["telephone_payeur"],
                        reference_transaction=data["reference_transaction"],
                        statut="en_attente",
                    )
            except IntegrityError:
                form.add_error("reference_transaction",
                               "Cette référence de transaction a déjà été déclarée.")
            else:
                messages.success(
                    request,
                    "Votre déclaration a été enregistrée. Elle ne vaut pas confirmation du paiement. "
                    "Présentez-vous à la bibliothèque avec votre pièce d'identité et le reçu Mobile Money."
                )
                return redirect("mon_compte")

    return render(request, "bibliotheque/public/cotisation.html", {
        "form": form,
        "montant": p.cotisation_mensuelle_fcfa,
        "orange_money_numero": getattr(p, "orange_money_numero", ""),
        "mtn_momo_numero": getattr(p, "mtn_momo_numero", ""),
    })
