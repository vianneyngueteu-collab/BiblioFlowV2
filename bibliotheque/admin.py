from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Achat, CotisationAdhesion, Emprunt, Exemplaire, LigneAchat, Livre, Utilisateur

admin.site.site_header = "BiblioFlow SCING2 – Administration"
admin.site.site_title = "BiblioFlow SCING2"
admin.site.index_title = "Gestion de la bibliothèque"


@admin.register(Utilisateur)
class UtilisateurAdmin(UserAdmin):
    list_display = ("username", "prenom", "nom", "role", "numero_carte", "statut")
    list_filter = ("role", "statut")
    search_fields = ("username", "nom", "prenom", "numero_carte", "telephone")
    readonly_fields = ("date_expiration",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Identité", {"fields": ("nom", "prenom", "email", "telephone", "adresse")}),
        ("Bibliothèque", {"fields": ("role", "statut", "numero_carte", "date_expiration", "suspendu_jusqu")}),
        ("Droits", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("username", "nom", "prenom", "email", "role", "password1", "password2")}),)


class LigneAchatInline(admin.TabularInline):
    model = LigneAchat
    extra = 0


@admin.register(Achat)
class AchatAdmin(admin.ModelAdmin):
    list_display = ("id", "adherent", "canal", "statut", "date_achat")
    list_filter = ("canal", "statut")
    inlines = [LigneAchatInline]


@admin.register(Livre)
class LivreAdmin(admin.ModelAdmin):
    list_display = ("titre", "auteur", "categorie", "prix", "stock_vente")
    search_fields = ("titre", "auteur")
    list_filter = ("categorie",)


admin.site.register(Exemplaire)
admin.site.register(Emprunt)


@admin.register(CotisationAdhesion)
class CotisationAdhesionAdmin(admin.ModelAdmin):
    list_display = ("adherent", "montant", "operateur", "reference_transaction", "statut", "date_declaration")
    list_filter = ("statut", "operateur")
    search_fields = ("adherent__username", "adherent__nom", "adherent__prenom", "reference_transaction")
    readonly_fields = tuple(field.name for field in CotisationAdhesion._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
