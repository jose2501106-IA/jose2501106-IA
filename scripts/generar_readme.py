"""Genera el README del perfil de GitHub desde data/perfil.yml del portafolio (fuente única).

Uso:
    python3 scripts/generar_readme.py --portafolio RUTA_AL_REPO_DEL_PORTAFOLIO
    (por omisión busca ../jose2501106-ia.github.io)

Salida: README.md, assets/banner-claro.jpg y assets/banner-oscuro.jpg.
Requiere: jinja2, pyyaml, pillow y playwright con Chromium (ver scripts/requisitos.txt).

Del portafolio solo se leen data/perfil.yml, las fuentes y el retrato. Nada se
publica si no está en perfil.yml, y el README no depende de servicios externos:
la única imagen remota es la serpiente, que genera el workflow de este mismo repo.
"""
import argparse
import asyncio
import pathlib
import re
import tempfile

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image
from playwright.async_api import async_playwright

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SERPIENTE = "https://raw.githubusercontent.com/jose2501106-IA/jose2501106-IA/output"


def t(x):
    """Texto en español: los campos traducibles de perfil.yml traen {es, en}."""
    return x["es"] if isinstance(x, dict) and "es" in x else x


def ancla(texto):
    """El mismo id que GitHub le pone a un encabezado, para enlazar a él."""
    s = re.sub(r"[^\w\- ]", "", texto.strip().lower())
    return s.replace(" ", "-")


def generar_readme(s):
    env = Environment(loader=FileSystemLoader(RAIZ / "plantillas"), autoescape=False,
                      undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.filters["t"] = t
    anclas = {p["codigo"]: ancla(f'{p["codigo"]} · {t(p["nombre"])}') for p in s["proyectos"]}
    texto = env.get_template("README.md.j2").render(s=s, t=t, anclas=anclas, serpiente=SERPIENTE)
    texto = re.sub(r"\n{3,}", "\n\n", texto)  # sin renglones vacíos de más
    destino = RAIZ / "README.md"
    destino.write_text(texto, encoding="utf-8")
    print(f"✓ README.md ({len(texto.encode()):,} bytes)")


async def generar_banners(s, portafolio):
    env = Environment(loader=FileSystemLoader(RAIZ / "plantillas"), autoescape=True)
    plantilla = env.get_template("banner.html.j2")
    (RAIZ / "assets").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        async with async_playwright() as p:
            navegador = await p.chromium.launch()
            for tema in ("claro", "oscuro"):
                html = plantilla.render(
                    tema=tema, base=portafolio.as_uri() + "/", anio=s["sitio"]["anio"],
                    hoja=t(s["ui"]["hoja"]), escala=t(s["ui"]["escala"]), kicker=t(s["portada"]["linea_superior"]),
                    nombre=s["sitio"]["nombre_h1"], sub=t(s["portada"]["subtitulo"]), bajada=t(s["portada"]["bajada"]),
                    pie_izq=t(s["portada"]["retrato"]["pie_izq"]), pie_der=t(s["portada"]["retrato"]["pie_der"]),
                    dominio=s["sitio"]["url"].removeprefix("https://").rstrip("/"))
                archivo = tmp / f"banner-{tema}.html"
                archivo.write_text(html, encoding="utf-8")
                pagina = await navegador.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=2)
                await pagina.goto(archivo.as_uri(), wait_until="load")
                await pagina.evaluate("document.fonts.ready")
                await pagina.wait_for_timeout(300)
                png = tmp / f"banner-{tema}.png"
                await pagina.screenshot(path=str(png))
                destino = RAIZ / f"assets/banner-{tema}.jpg"
                Image.open(png).convert("RGB").save(destino, "JPEG", quality=84, optimize=True, progressive=True)
                print(f"✓ {destino.relative_to(RAIZ)} ({destino.stat().st_size:,} bytes)")
            await navegador.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--portafolio", type=pathlib.Path, default=RAIZ.parent / "jose2501106-ia.github.io",
                        help="carpeta del repo del portafolio (de ahí se leen perfil.yml, fuentes y retrato)")
    parser.add_argument("--solo-texto", action="store_true", help="regenera README.md sin volver a dibujar los encabezados")
    args = parser.parse_args()
    portafolio = args.portafolio.resolve()
    perfil = portafolio / "data/perfil.yml"
    if not perfil.exists():
        raise SystemExit(f"No encuentro {perfil}. Indica la carpeta del portafolio con --portafolio.")
    s = yaml.safe_load(perfil.read_text(encoding="utf-8"))
    generar_readme(s)
    if not args.solo_texto:
        asyncio.run(generar_banners(s, portafolio))


if __name__ == "__main__":
    main()
