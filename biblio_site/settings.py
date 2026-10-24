"""
Django settings for biblio_site project.

Configuration BiblioFlow compatible avec Django 5.2.18.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.2/ref/settings/
"""

from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-before-deployment")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

# Hôtes explicitement autorisés pour l'environnement de développement.
# Pour un nouveau tunnel trycloudflare.com, définir CLOUDFLARE_TUNNEL_HOST dans l’environnement.
CLOUDFLARE_TUNNEL_HOST = os.environ.get(
    "CLOUDFLARE_TUNNEL_HOST", "uni-workforce-cabinets-themes.trycloudflare.com"
).strip()
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
ALLOWED_HOSTS += [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
if CLOUDFLARE_TUNNEL_HOST:
    ALLOWED_HOSTS.append(CLOUDFLARE_TUNNEL_HOST)

CSRF_TRUSTED_ORIGINS = []
if CLOUDFLARE_TUNNEL_HOST:
    CSRF_TRUSTED_ORIGINS.append(f"https://{CLOUDFLARE_TUNNEL_HOST}")
CSRF_TRUSTED_ORIGINS += [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# Cloudflare termine HTTPS puis transmet la requête au serveur Django local.
# N'utiliser ce réglage que derrière le tunnel/proxy de confiance.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Les cookies sont sécurisés sur l'URL HTTPS du tunnel.
# Par défaut, compatible avec http://127.0.0.1:8000 en développement.
# Sur un déploiement HTTPS, définir BIBLIO_SECURE_COOKIES=1.
SECURE_COOKIES = os.environ.get("BIBLIO_SECURE_COOKIES", "0") == "1"
CSRF_COOKIE_SECURE = SECURE_COOKIES
SESSION_COOKIE_SECURE = SECURE_COOKIES
CSRF_COOKIE_HTTPONLY = False
# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'bibliotheque',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'biblio_site.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'bibliotheque.context.globales',
            ],
        },
    },
]

WSGI_APPLICATION = 'biblio_site.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "fr"
TIME_ZONE = "Africa/Douala"
AUTH_USER_MODEL = "bibliotheque.Utilisateur"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "apres_connexion"
LOGOUT_REDIRECT_URL = "accueil"

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "/static/"


# Email
# https://docs.djangoproject.com/en/5.2/topics/email/#topic-email-configuration

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}


# ---------- Règles de la bibliothèque (à modifier ici) ----------
BIBLIO = {
    "duree_pret_jours": 14,              # durée d'un prêt
    "max_emprunts": 3,                   # emprunts simultanés par adhérent (demandes en ligne comprises)
    "max_prolongations": 1,              # prolongations par prêt
    "duree_prolongation_jours": 7,
    "amende_par_jour": 100,              # FCFA par jour de retard
    "amende_plafond": 5000,              # FCFA, 0 = pas de plafond
    "frais_perte": 500,                  # FCFA, s'ajoutent au prix du livre perdu
    "coef_suspension": 1,                # jours de suspension par jour de retard (0 = aucune)
    "delai_retrait_jours": 3,
    "delai_achat_en_ligne_jours": 5,     # un achat en ligne non préparé au bout de ce délai est annulé (stock restitué)
    "max_achats_invites_actifs_par_telephone": 2,  # anti-abus : commandes invité simultanées par numéro
    "max_achats_invites_par_ip_heure": 5,          # anti-abus : commandes invité par adresse IP et par heure
    "max_exemplaires_achat_invite": 10,            # anti-abus : livres au total dans une commande invité
    "max_suivis_par_ip_heure": 20,                 # anti-abus : consultations du suivi de commande            # une commande prête non retirée est annulée après ce délai
    "cotisation_mensuelle_fcfa": 1000,
    "duree_adhesion_jours": 30,
    "validation_adhesion_requise": True, # True : les inscrits en ligne sont validés au comptoir
    "horaires": "Lundi – vendredi : 8h – 17h, samedi : 9h – 13h",
    "adresse": "",
}

# Conserve les clés primaires AutoField déjà utilisées par les migrations.
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
