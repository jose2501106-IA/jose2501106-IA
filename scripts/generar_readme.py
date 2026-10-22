"""Genera el README del perfil de GitHub desde data/perfil.yml del portafolio (fuente única).

Uso:
    python3 scripts/generar_readme.py --portafolio RUTA_AL_REPO_DEL_PORTAFOLIO
    (por omisión busca ../jose2501106-ia.github.io)

Salida: README.md y assets/laminas/<lámina>-<claro|oscuro>.webp
Requiere: jinja2, pyyaml, pillow y playwright con Chromium (ver scripts/requisitos.txt).

Cada sección del README es una «lámina» con el estilo de plano del portafolio,
en versión clara y oscura (GitHub muestra la que corresponde al tema de quien
visita). Los proyectos van en una sola lámina compacta: las tarjetas completas las
muestran los repos fijados del perfil. Lo que se toca (enlaces, CV y contacto) también
queda como texto, y cada lámina lleva un texto alternativo con su contenido.

Del portafolio solo se leen data/perfil.yml, las fuentes y los logos. Nada se
publica si no está en perfil.yml, y el README no depende de servicios externos:
la única imagen remota es la serpiente, que genera el workflow de este mismo repo.
"""
import argparse
import asyncio
import html
import io
import pathlib
import re

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup
from PIL import Image
from playwright.async_api import async_playwright

RAIZ = pathlib.Path(__file__).resolve().parent.parent
LAMINAS = RAIZ / "assets/laminas"
SERPIENTE = "https://raw.githubusercontent.com/jose2501106-IA/jose2501106-IA/output"
TEMAS = ("claro", "oscuro")
ESCALA = 1.5            # 1200 px de diseño → 1800 px de imagen: nítida en pantallas retina
CALIDAD_WEBP = 90

# Logos del portafolio: archivo y tamaño base en px, igual que en scripts/generar.py del portafolio.
# En las láminas van a color de marca (assets/img/logos/color): una imagen no tiene cursor que los encienda.
LOGOS = {
    "medalla-2": ("medalla-2.svg", 37, 52), "medalla-3": ("medalla-3.svg", 37, 52),
    "hybridge": ("hybridge.svg", 110, 19), "uveg": ("uveg.svg", 78, 21), "anahuac": ("anahuac.svg", 32, 32),
    "aspire": ("aspire.svg", 80, 28), "one": ("one.svg", 62, 32), "oracle": ("oracle.svg", 104, 13), "lssi": ("lssi.svg", 78, 32),
    "stellar": ("stellar.svg", 96, 24), "baf": ("baf.webp", 56, 28), "oratoria": ("oratoria.svg", 32, 32),
}
TAMANO_LOGO = 1.7       # en las tarjetas de formación los logos van más grandes que en el portafolio


def t(x):
    """Texto en español: los campos traducibles de perfil.yml traen {es, en}."""
    return x["es"] if isinstance(x, dict) and "es" in x else x


def oracion(texto):
    """«IA Y DATOS» → «IA y datos»: tipo oración sin romper las siglas."""
    s = texto.lower().capitalize()
    return re.sub(r"\bia\b", "IA", s, flags=re.I)


def unir(partes, sep="; "):
    return sep.join(p for p in partes if p)


def estado_formacion(f):
    """Estado de un programa para el texto alternativo; si va por fases, cada fase con su estado."""
    if "fases" not in f:
        return t(f["estado"])
    return unir(f'{t(fa["nombre"])}, {t(fa["estado"])[:1].lower()}{t(fa["estado"])[1:]}' for fa in f["fases"])


def verificaciones(s):
    """Certificados verificables de formación: el del programa o, si va por fases, el de cada fase."""
    return [(f'{t(f["institucion"])} · {t(x["nombre"]) if "nombre" in x else t(f["programa"])}', x["verificar"])
            for f in s["perfil"]["formacion"] for x in (f, *f.get("fases", [])) if "verificar" in x]


def textos_alternativos(s):
    """Lo que dice cada lámina, en texto: para lectores de pantalla y para quien no carga imágenes."""
    alt = {
        "encabezado": f'{s["sitio"]["nombre"]} · {t(s["portada"]["subtitulo"])} {t(s["portada"]["bajada"])}. '
                      + unir(f'{t(c["valor"])} {t(c["texto"])} ({c["codigo"]})' for c in s["portada"]["cifras"]) + ".",
        "roles": f'{t(s["secciones"]["roles"]["titulo"])}. '
                 + unir((f'{t(r["titulo"])}: {t(r["texto"])} Evidencia: {", ".join(r["evidencia"])}.' for r in s["roles"]), " "),
        "proyectos": f'{t(s["secciones"]["proyectos"]["titulo"])}. '
                     + unir((f'{p["codigo"]} {t(p["nombre"])} ({t(p["estado"])}): {t(p["subtitulo"])}. '
                             + (unir(t(d["titulo"]) for d in p["distinciones"]["premios"]) if "distinciones" in p
                                else unir(f'{t(c["valor"])} {t(c["texto"])}' for c in p["cifras"]))
                             + f'. Tecnologías: {", ".join(map(t, p["tecnologias"]))}.'
                             + ("" if p["enlaces"] else f' {t(s["ui"]["privado"])}.') for p in s["proyectos"]), " "),
        "herramientas": "Herramientas. " + unir(f'{oracion(t(g["grupo"]))}: {", ".join(map(t, g["lista"]))}' for g in s["perfil"]["herramientas"])
                        + f'. Idiomas: {", ".join(map(t, s["perfil"]["idiomas"]))}. {oracion(t(s["ui"]["habilidades_blandas"]))}: {t(s["perfil"]["habilidades_blandas"])}'
,
        "formacion": f'{oracion(t(s["ui"]["formacion_programas"]))}. '
                     + unir(f'{t(f["institucion"])}: {t(f["programa"])} ({estado_formacion(f)})' for f in s["perfil"]["formacion"]) + ".",
        "oratoria": f'{oracion(t(s["ui"]["oratoria_comunidad"]))}. '
                    + unir(f'{t(f["institucion"])}: {t(f["programa"])} ({t(f["estado"])})' for f in s["perfil"]["oratoria_comunidad"]) + ".",
        "contacto": f'{t(s["seccion_contacto"]["titulo"])} Correo: {s["contacto"]["correo"]}; LinkedIn: {s["contacto"]["linkedin_txt"]}; '
                    f'CV en PDF; {t(s["contacto"]["ubicacion"])}.',
    }
    return alt


def generar_readme(s):
    alt = textos_alternativos(s)

    def lamina(nombre, enlace=None):
        imagen = (f'<picture>\n  <source media="(prefers-color-scheme: dark)" srcset="assets/laminas/{nombre}-oscuro.webp">\n'
                  f'  <img src="assets/laminas/{nombre}-claro.webp" width="100%" alt="{html.escape(alt[nombre], quote=True)}">\n</picture>')
        return Markup(f'<a href="{enlace}">\n{imagen}\n</a>' if enlace else imagen)

    env = Environment(loader=FileSystemLoader(RAIZ / "plantillas"), autoescape=False,
                      undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.filters["t"] = t
    texto = env.get_template("README.md.j2").render(s=s, t=t, lamina=lamina, serpiente=SERPIENTE,
                                                          verificaciones=verificaciones(s))
    texto = re.sub(r"\n{3,}", "\n\n", texto)  # sin renglones vacíos de más
    (RAIZ / "README.md").write_text(texto, encoding="utf-8")
    print(f"✓ README.md ({len(texto.encode()):,} bytes)")
    return [nombre for nombre in alt]


async def generar_laminas(s, portafolio, nombres):
    logos = {clave: {"src": (portafolio / "assets/img/logos/color" / archivo).as_uri(),
                     "ancho": round(ancho * TAMANO_LOGO), "alto": round(alto * TAMANO_LOGO)}
             for clave, (archivo, ancho, alto) in LOGOS.items()}
    env = Environment(loader=FileSystemLoader(RAIZ / "plantillas"), autoescape=True, undefined=StrictUndefined)
    env.filters["t"] = t
    plantilla = env.get_template("laminas.html.j2")
    LAMINAS.mkdir(parents=True, exist_ok=True)
    for viejo in LAMINAS.glob("*.webp"):
        viejo.unlink()
    total = 0
    async with async_playwright() as p:
        navegador = await p.chromium.launch()
        for tema in TEMAS:
            html_tema = plantilla.render(s=s, t=t, tema=tema, base=portafolio.as_uri() + "/", logos=logos,
                                         dominio=s["sitio"]["url"].removeprefix("https://").rstrip("/"))
            archivo = LAMINAS.parent / f".laminas-{tema}.html"
            archivo.write_text(html_tema, encoding="utf-8")
            pagina = await navegador.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=ESCALA)
            await pagina.goto(archivo.as_uri(), wait_until="load")
            await pagina.evaluate("document.fonts.ready")
            await pagina.wait_for_timeout(300)
            for nombre in nombres:
                elemento = await pagina.query_selector(f'[data-nombre="{nombre}"]')
                if elemento is None:
                    raise SystemExit(f"La plantilla no tiene la lámina «{nombre}»")
                png = await elemento.screenshot(type="png")
                destino = LAMINAS / f"{nombre}-{tema}.webp"
                Image.open(io.BytesIO(png)).convert("RGB").save(destino, "WEBP", quality=CALIDAD_WEBP, method=6)
                total += destino.stat().st_size
            archivo.unlink()
        await navegador.close()
    print(f"✓ {len(nombres) * len(TEMAS)} láminas en assets/laminas ({total / 1024:,.0f} KB en total)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--portafolio", type=pathlib.Path, default=RAIZ.parent / "jose2501106-ia.github.io",
                        help="carpeta del repo del portafolio (de ahí se leen perfil.yml, fuentes y logos)")
    parser.add_argument("--solo-texto", action="store_true", help="regenera README.md sin volver a dibujar las láminas")
    args = parser.parse_args()
    portafolio = args.portafolio.resolve()
    perfil = portafolio / "data/perfil.yml"
    if not perfil.exists():
        raise SystemExit(f"No encuentro {perfil}. Indica la carpeta del portafolio con --portafolio.")
    s = yaml.safe_load(perfil.read_text(encoding="utf-8"))
    nombres = generar_readme(s)
    if not args.solo_texto:
        asyncio.run(generar_laminas(s, portafolio, nombres))


if __name__ == "__main__":
    main()
