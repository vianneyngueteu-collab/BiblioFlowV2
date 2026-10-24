from django import template
from urllib.parse import quote
import re
import hashlib
import html

register = template.Library()

_PALETTES = [
    ("#103c35", "#2dd4a7", "#f3f1df"),
    ("#182a55", "#65c8f2", "#f7e8c7"),
    ("#642b38", "#f2ad72", "#fff0d9"),
    ("#352451", "#c9a7ff", "#f6edff"),
    ("#1e4537", "#d5df91", "#f8f3df"),
    ("#8a3e20", "#f5c45e", "#fff1cf"),
    ("#173f67", "#e9a8bc", "#fff0f2"),
    ("#292d36", "#e4c16e", "#fff8df"),
]

@register.filter
def teinte(livre):
    return int(hashlib.sha256((livre.titre or str(livre.pk)).encode("utf-8")).hexdigest()[:8], 16) % len(_PALETTES)

@register.filter
def dos(livre):
    return f"height:{168 + (livre.pk * 37) % 56}px;width:{46 + (livre.pk * 11) % 18}px"

@register.filter
def couverture(livre):
    """Couverture vectorielle unique par livre, générée localement sans service externe."""
    image = getattr(livre, "image", "") or ""
    if image.startswith(("https://", "http://", "/")):
        return image
    # Les anciennes couvertures cover-1.svg à cover-8.svg étaient répétées ;
    # on les remplace par une illustration déterministe propre à chaque ouvrage.
    if image and not re.fullmatch(r"cover-[1-8]\.svg", image):
        return f"/static/bibliotheque/images/covers/{image}"

    titre = (livre.titre or "Livre sans titre").strip()
    auteur = (livre.auteur or "Auteur inconnu").strip()
    categorie = (livre.categorie or "Bibliothèque").strip()
    digest = hashlib.sha256(f"{titre}|{auteur}|{categorie}".encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(_PALETTES)
    fond, accent, papier = _PALETTES[idx]
    motif = int(digest[8:12], 16) % 5
    if motif == 0:
        art = f'<circle cx="300" cy="285" r="142" fill="{accent}" opacity=".92"/><circle cx="300" cy="285" r="92" fill="{fond}"/><circle cx="300" cy="285" r="43" fill="{accent}"/>'
    elif motif == 1:
        art = f'<path d="M0 360 L600 100 L600 440 L0 600Z" fill="{accent}"/><path d="M0 460 L600 200 L600 310 L0 570Z" fill="{papier}" opacity=".72"/>'
    elif motif == 2:
        art = f'<path d="M300 100 L480 420 L120 420Z" fill="{accent}"/><path d="M300 190 L410 390 L190 390Z" fill="{fond}"/>'
    elif motif == 3:
        art = f'<rect x="125" y="145" width="350" height="280" rx="24" fill="{accent}"/><path d="M150 390 L450 180" stroke="{papier}" stroke-width="18" opacity=".8"/>'
    else:
        art = f'<path d="M300 105 C430 200 480 270 300 445 C120 270 170 200 300 105Z" fill="{accent}"/><circle cx="300" cy="275" r="55" fill="{papier}"/>'

    lines, line = [], ""
    for word in titre.split():
        if len((line + " " + word).strip()) > 18 and line:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)
    title_svg = "".join(
        f'<text x="44" y="{510 + i*43}" font-family="Arial,sans-serif" font-size="32" font-weight="700" fill="{papier}">{html.escape(part)}</text>'
        for i, part in enumerate(lines[:4])
    )
    cat = html.escape(categorie[:28])
    aut = html.escape(auteur[:34])
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800" viewBox="0 0 600 800">'
        f'<rect width="600" height="800" fill="{fond}"/><rect x="22" y="22" width="556" height="756" rx="8" fill="none" stroke="{accent}" stroke-width="3"/>'
        f'<path d="M35 55V745" stroke="{accent}" stroke-width="12"/><text x="52" y="82" font-family="Arial,sans-serif" font-size="20" letter-spacing="5" fill="{accent}">BIBLIOFLOW</text>'
        f'<text x="52" y="122" font-family="Arial,sans-serif" font-size="17" fill="{papier}" opacity=".8">{cat}</text>'
        f'{art}{title_svg}<path d="M44 700H556" stroke="{accent}" stroke-width="2"/>'
        f'<text x="44" y="738" font-family="Arial,sans-serif" font-size="20" fill="{papier}">{aut}</text>'
        f'<text x="540" y="738" text-anchor="end" font-family="Arial,sans-serif" font-size="13" fill="{accent}">ÉDITION</text></svg>'
    )
    return "data:image/svg+xml;charset=UTF-8," + quote(svg, safe="")
