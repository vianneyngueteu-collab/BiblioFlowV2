from .acces import est_personnel
from .services import params
from .models import CotisationAdhesion


def globales(request):
    ctx = {"p": params(), "panier_count": 0, "est_personnel": False, "cotisations_a_verifier": 0}
    try:
        ctx["panier_count"] = sum(request.session.get("panier", {}).values())
    except Exception:
        pass
    if request.user.is_authenticated:
        ctx["est_personnel"] = est_personnel(request.user)
        if ctx["est_personnel"]:
            ctx["cotisations_a_verifier"] = CotisationAdhesion.objects.filter(statut="en_attente").count()
    return ctx
