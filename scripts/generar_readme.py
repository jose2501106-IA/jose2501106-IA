"""Genera el README del perfil de GitHub desde data/perfil.yml del portafolio (fuente única).

Uso:
    python3 scripts/generar_readme.py --portafolio RUTA_AL_REPO_DEL_PORTAFOLIO
    (por omisión busca ../jose2501106-ia.github.io)

Salida: README.md, assets/encabezado.webp y assets/logos/<logos>.webp
Requiere: jinja2, pyyaml, pillow y playwright con Chromium (ver scripts/requisitos.txt).

El README va en texto real (tablas, enlaces y etiquetas de GitHub): se lee en celular, se puede
seleccionar, buscar y traducir, y toma solo el tema claro u oscuro de quien visita. Las únicas
imágenes son el encabezado (la marca y el nombre, en el petróleo del portafolio) y las fichas con
los logos de las instituciones, que van tal cual sobre blanco para leerse igual en los dos temas.
Herramientas, formación y liderazgo van plegadas: el detalle completo se abre con un clic.

Del portafolio solo se leen data/perfil.yml, las fuentes y los logos. Nada se publica si no está
en perfil.yml, y el README no depende de servicios externos.
"""
import argparse
import asyncio
import io
import pathlib
import re

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image
from playwright.async_api import async_playwright

RAIZ = pathlib.Path(__file__).resolve().parent.parent
ACTIVOS = RAIZ / "assets"
ESCALA = 2              # las imágenes salen al doble: nítidas en pantallas retina
CALIDAD_WEBP = 92

# Logos del portafolio (assets/img/logos/color): archivo y tamaño base en px, igual que en scripts/generar.py del portafolio.
LOGOS = {
    "hybridge": ("hybridge.svg", 110, 19), "uveg": ("uveg.svg", 78, 21), "anahuac": ("anahuac.svg", 32, 32),
    "aspire": ("aspire.svg", 80, 28), "one": ("one.svg", 62, 32), "oracle": ("oracle.svg", 104, 13), "lssi": ("lssi.svg", 78, 32),
    "stellar": ("stellar.svg", 96, 24), "baf": ("baf.webp", 56, 28), "oratoria": ("oratoria.svg", 46, 46),
    "congreso-oaxaca": ("congreso-oaxaca.webp", 88, 44), "wya": ("wya.webp", 50, 48),
}


def t(x):
    """Texto en español: los campos traducibles de perfil.yml traen {es, en}."""
    return x["es"] if isinstance(x, dict) and "es" in x else x


def oracion(texto):
    """«IA Y DATOS» → «IA y datos»: tipo oración sin romper las siglas."""
    s = texto.lower().capitalize()
    return re.sub(r"\bia\b", "IA", s, flags=re.I)


def logro(s):
    """La entrada de experiencia que trae «lamina» (un premio con bloque propio en el README), o None si no hay."""
    return next((x for x in s["experiencia"] if "lamina" in x), None)


def fichas_de_logos(entradas):
    """Una ficha por entrada, con sus logos y el nombre de la institución como texto alternativo.
    Se omite la entrada que no agrega ningún logo nuevo a la fila (así un mismo logo no sale dos veces)."""
    vistos, fichas = set(), []
    for f in entradas:
        logos = f.get("logos", [])
        if not logos or set(logos) <= vistos:
            continue
        desconocidos = [l for l in logos if l not in LOGOS]
        if desconocidos:
            raise SystemExit(f"Falta registrar en LOGOS (scripts/generar_readme.py): {', '.join(desconocidos)}")
        vistos |= set(logos)
        fichas.append({"clave": "-".join(logos), "logos": logos, "alt": t(f["institucion"])})
    return fichas


def entorno(autoescape):
    env = Environment(loader=FileSystemLoader(RAIZ / "plantillas"), autoescape=autoescape, undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.filters["t"] = t
    return env


def generar_readme(s):
    fichas = {"formacion": fichas_de_logos(s["perfil"]["formacion"]), "oratoria": fichas_de_logos(s["perfil"]["oratoria_comunidad"])}
    texto = entorno(False).get_template("README.md.j2").render(
        s=s, t=t, oracion=oracion, logro=logro(s), fichas_formacion=fichas["formacion"], fichas_oratoria=fichas["oratoria"],
        alt_encabezado=f'{s["sitio"]["marca"]} · {s["sitio"]["nombre"]}',
        dominio=s["sitio"]["url"].removeprefix("https://").rstrip("/"))
    texto = re.sub(r"\n{3,}", "\n\n", texto)  # sin renglones vacíos de más
    (RAIZ / "README.md").write_text(texto, encoding="utf-8")
    print(f"✓ README.md ({len(texto.encode()):,} bytes)")
    return {f["clave"]: f for grupo in fichas.values() for f in grupo}.values()   # cada ficha una sola vez


async def generar_imagenes(s, portafolio, fichas):
    """Dibuja el encabezado y las fichas de logos con las fuentes y los logos del portafolio."""
    fichas = list(fichas)
    logos = {clave: {"src": (portafolio / "assets/img/logos/color" / archivo).as_uri(), "ancho": ancho, "alto": alto}
             for clave, (archivo, ancho, alto) in LOGOS.items()}
    (ACTIVOS / "logos").mkdir(parents=True, exist_ok=True)
    for viejo in (ACTIVOS / "logos").glob("*.webp"):
        viejo.unlink()
    archivo = ACTIVOS / ".imagenes.html"
    archivo.write_text(entorno(True).get_template("imagenes.html.j2").render(s=s, t=t, fichas=fichas, logos=logos, base=portafolio.as_uri() + "/"),
                       encoding="utf-8")
    destinos = {"encabezado": ACTIVOS / "encabezado.webp"} | {f'logo-{f["clave"]}': ACTIVOS / "logos" / f'{f["clave"]}.webp' for f in fichas}
    total = 0
    async with async_playwright() as p:
        navegador = await p.chromium.launch()
        pagina = await navegador.new_page(viewport={"width": 1200, "height": 800}, device_scale_factor=ESCALA)
        await pagina.goto(archivo.as_uri(), wait_until="load")
        await pagina.evaluate("document.fonts.ready")
        await pagina.wait_for_timeout(300)
        for nombre, destino in destinos.items():
            elemento = await pagina.query_selector(f'[data-nombre="{nombre}"]')
            if elemento is None:
                raise SystemExit(f"La plantilla no tiene «{nombre}»")
            png = await elemento.screenshot(type="png", omit_background=True)   # las fichas llevan esquinas redondeadas
            imagen = Image.open(io.BytesIO(png))
            imagen = imagen.convert("RGB") if nombre == "encabezado" else imagen.convert("RGBA")
            imagen.save(destino, "WEBP", quality=CALIDAD_WEBP, method=6)
            total += destino.stat().st_size
        await navegador.close()
    archivo.unlink()
    print(f"✓ encabezado y {len(fichas)} fichas de logos en assets ({total / 1024:,.0f} KB en total)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--portafolio", type=pathlib.Path, default=RAIZ.parent / "jose2501106-ia.github.io",
                        help="carpeta del repo del portafolio (de ahí se leen perfil.yml, las fuentes y los logos)")
    parser.add_argument("--solo-texto", action="store_true", help="regenera README.md sin volver a dibujar las imágenes")
    args = parser.parse_args()
    portafolio = args.portafolio.resolve()
    perfil = portafolio / "data/perfil.yml"
    if not perfil.exists():
        raise SystemExit(f"No encuentro {perfil}. Indica la carpeta del portafolio con --portafolio.")
    s = yaml.safe_load(perfil.read_text(encoding="utf-8"))
    fichas = generar_readme(s)
    if not args.solo_texto:
        asyncio.run(generar_imagenes(s, portafolio, fichas))


if __name__ == "__main__":
    main()
