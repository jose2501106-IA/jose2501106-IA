"""Genera el README del perfil de GitHub desde data/perfil.yml del portafolio (fuente única). Versión visual.

Uso:
    python3 scripts/generar_readme.py --portafolio RUTA_AL_REPO_DEL_PORTAFOLIO
    (por omisión busca ../jose2501106-ia.github.io)

Salida: README.md, assets/laminas/*.webp, assets/botones/*.webp y assets/logos/*.webp
Requiere: jinja2, pyyaml, pillow y playwright con Chromium (ver scripts/requisitos.txt).

Los bloques principales van como láminas en el petróleo del portafolio (estilo A · Laboratorio): portada,
una por cada premio, roles y proyectos. Cada lámina sale en dos anchos, computadora (846 px) y celular (326 px), y el README
elige con <picture>: en celular ningún texto baja de 12 px. Cada lámina lleva un texto alternativo con
todo lo que dice. Los enlaces son botones pequeños o texto real, y el detalle de herramientas,
formación y liderazgo va en texto, plegado.

Del portafolio solo se leen data/perfil.yml, las fuentes y los logos. Nada se publica si no está en
perfil.yml, y el README no depende de servicios externos.
"""
import argparse
import asyncio
import io
import pathlib
import re
import unicodedata

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image
from playwright.async_api import async_playwright

RAIZ = pathlib.Path(__file__).resolve().parent.parent
ACTIVOS = RAIZ / "assets"
ESCALA = 2              # las imágenes salen al doble: nítidas en pantallas retina
CALIDAD = {"laminas": None, "botones": 90, "logos": 92}   # None: WebP sin pérdida (en láminas de color plano pesa menos y no deja halos)

# Logos del portafolio (assets/img/logos/color): archivo y tamaño base en px, igual que en scripts/generar.py del portafolio.
LOGOS = {
    "medalla-1": ("medalla-1.svg", 37, 52), "medalla-2": ("medalla-2.svg", 37, 52), "medalla-3": ("medalla-3.svg", 37, 52),
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


def unir(partes, sep="; "):
    return sep.join(p for p in partes if p)


def logro(s):
    """La entrada de experiencia que trae «lamina» (un premio con lámina propia en el README), o None si no hay."""
    return next((x for x in s["experiencia"] if "lamina" in x), None)


def premios(s):
    """Las entradas de experiencia que son premios: van en la portada."""
    return [x for x in s["experiencia"] if x.get("tipo") == "premio"]


def codigo(texto):
    """«Goya Hack 2026» → «goya-hack-2026»: para nombres de archivo."""
    sin = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sin.lower()).strip("-")


def proyecto_de(s, x):
    """El proyecto premiado en esa entrada: el que cita el mismo certamen en «distinciones», o None."""
    return next((p for p in s["proyectos"] if "distinciones" in p and t(p["distinciones"]["texto"]) == t(x["donde"])), None)


def logros(s):
    """Los premios de experiencia, cada uno con su lámina. El que trae «lamina» usa ese contenido;
    los demás se arman con lo que ya dice su entrada (y su proyecto premiado, si lo hay)."""
    bloques = []
    for x in premios(s):
        if "lamina" in x:
            enlaces = [{"texto": t(x["lamina"]["enlace"]["texto"]), "url": x["lamina"]["enlace"]["url"]},
                       {"texto": "Ver en el portafolio", "url": f'{s["sitio"]["url"]}#{x["id"]}'}]
            bloques.append({"nombre": "logro", "x": x, "rico": True, "enlaces": enlaces})
            continue
        titulo, _, organiza = t(x["donde"]).partition(" · ")
        p = proyecto_de(s, x)
        enlaces = [{"texto": f'{p["codigo"]} {t(p["nombre"])} · {t(e["texto"])}', "url": e["url"]} for e in (p["enlaces"] if p else [])]
        bloques.append({"nombre": f"logro-{codigo(titulo)}", "x": x, "rico": False, "titulo": titulo, "organiza": organiza,
                        "proyecto": p, "enlaces": enlaces})
    return bloques


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


def botones(s):
    """Botones del README: cada uno es una imagen pequeña con su enlace. «donde» dice en qué fila va."""
    c, url = s["contacto"], s["sitio"]["url"]
    cv, correo = url + t(s["cv"]["archivo"]), f'mailto:{c["correo"]}'
    return [
        {"clave": "portafolio", "texto": "Portafolio", "url": url, "principal": True, "donde": "arriba"},
        {"clave": "english", "texto": "English", "url": url + "en/", "principal": False, "donde": "arriba"},
        {"clave": "linkedin", "texto": "LinkedIn", "url": c["linkedin_url"], "principal": False, "donde": "arriba"},
        {"clave": "cv", "texto": f'{t(s["cv"]["nav"])} (PDF)', "url": cv, "principal": False, "donde": "arriba"},
        {"clave": "correo", "texto": t(s["ui"]["correo"]), "url": correo, "principal": False, "donde": "arriba"},
        {"clave": "escribir-correo", "texto": t(s["seccion_contacto"]["boton_correo"]), "url": correo, "principal": True, "donde": "contacto"},
        {"clave": "ir-a-linkedin", "texto": t(s["seccion_contacto"]["boton_linkedin"]), "url": c["linkedin_url"], "principal": False, "donde": "contacto"},
        {"clave": "descargar-cv", "texto": t(s["cv"]["boton"]), "url": cv, "principal": False, "donde": "contacto"},
    ]


def textos_alternativos(s):
    """Lo que dice cada lámina, en texto: para lectores de pantalla y para quien no carga imágenes."""
    p = s["portada"]
    alt = {
        "portada": f'{s["sitio"]["marca"]} · {s["sitio"]["nombre"]}. {oracion(t(p["linea_superior"]))}. {t(p["subtitulo"])} {t(p["bajada"])}. '
                   + unir(f'{t(c["valor"])} {t(c["texto"])} ({c["codigo"]} · {t(s["ui"]["fuente"])} {t(c["fuente"]["corta"])})' for c in p["cifras"]) + ". "
                   + unir(f'{t(x["puesto"])} · {t(x["donde"])}' for x in premios(s)) + ". "
                   + unir(f'{oracion(t(d["etiqueta"]))}: {t(d["valor"])}' for d in p["datos"]) + ".",
        "roles": f'{t(s["secciones"]["roles"]["titulo"])}. '
                 + unir((f'{r["codigo"]} {t(r["titulo"])}: {t(r["texto"])} {oracion(t(s["ui"]["evidencia"]))} '
                         + ", ".join(r["evidencia"] + [t(x["texto"]) for x in r.get("evidencia_extra", [])]) + "." for r in s["roles"]), " ")
                 + " " + t(s["como_trabajo"]).lstrip("/ "),
        "proyectos": f'{t(s["secciones"]["proyectos"]["titulo"])}. '
                     + unir((f'{x["codigo"]} · {" · ".join(t(s["categorias"][c]["fig"]) for c in x["categorias"])} · {t(x["estado"])}. '
                             f'{t(x["nombre"])}: {t(x["subtitulo"])}. '
                             + (unir(t(d["titulo"]) for d in x["distinciones"]["premios"]) if "distinciones" in x
                                else unir(f'{t(c["valor"])} {t(c["texto"])}' for c in x["cifras"]))
                             + f'. {", ".join(map(t, x["tecnologias"]))}.'
                             + ("" if x["enlaces"] else f' {t(s["ui"]["privado"])}.') for x in s["proyectos"]), " "),
    }
    lg = logro(s)
    if lg:
        l = lg["lamina"]
        alt["logro"] = (f'{t(lg["puesto"])}: {t(l["titulo"])}. {t(lg["etiqueta"])} · {t(lg["lugar"])}. {t(l["equipo"])}. {t(l["propuesta"])} '
                        f'{oracion(t(l["metodo"]))}: '
                        + unir((f'{t(x["valor"])} · {t(x["texto"])}' for x in l["pasos"]), ", ") + ". "
                        + unir(f'{oracion(t(f["et"]))}: {t(f["valor"])}' for f in l["ficha"]) + ". "
                        + t(l["nota"]).lstrip("/ "))
    for b in logros(s):
        if b["rico"]:
            continue
        x, pr = b["x"], b["proyecto"]
        alt[b["nombre"]] = (f'{t(x["puesto"])}: {t(x["donde"])}. {t(x["etiqueta"])} · {t(x["lugar"])}. ' + " ".join(t(q) for q in x["puntos"])
                            + (f' {t(s["ui"]["proyecto"])}: {pr["codigo"]} {t(pr["nombre"])}. {t(s["ui"]["ficha"]["demuestra"])}: {t(pr["demuestra"])}. '
                               f'{t(s["ui"]["ficha"]["tecnologias"])}: {", ".join(map(t, pr["tecnologias"]))}.' if pr else ""))
    return alt


def entorno(autoescape):
    env = Environment(loader=FileSystemLoader(RAIZ / "plantillas"), autoescape=autoescape, undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)
    env.filters["t"] = t
    env.filters["pegar"] = lambda x: x.replace(" · ", "\u00a0· ")   # el punto medio nunca abre renglón
    return env


def generar_readme(s):
    fichas = {"formacion": fichas_de_logos(s["perfil"]["formacion"]), "oratoria": fichas_de_logos(s["perfil"]["oratoria_comunidad"])}
    texto = entorno(False).get_template("README.md.j2").render(
        s=s, t=t, oracion=oracion, logros=logros(s), alt=textos_alternativos(s), botones=botones(s),
        fichas_formacion=fichas["formacion"], fichas_oratoria=fichas["oratoria"],
        dominio=s["sitio"]["url"].removeprefix("https://").rstrip("/"))
    texto = re.sub(r"\n{3,}", "\n\n", texto)  # sin renglones vacíos de más
    (RAIZ / "README.md").write_text(texto, encoding="utf-8")
    print(f"✓ README.md ({len(texto.encode()):,} bytes)")
    return list({f["clave"]: f for grupo in fichas.values() for f in grupo}.values())   # cada ficha una sola vez


async def generar_imagenes(s, portafolio, fichas):
    """Dibuja las láminas, los botones y las fichas de logos con las fuentes y los logos del portafolio."""
    logos = {clave: {"src": (portafolio / "assets/img/logos/color" / archivo).as_uri(), "ancho": ancho, "alto": alto}
             for clave, (archivo, ancho, alto) in LOGOS.items()}
    lista_botones = botones(s)
    destinos = {}
    for nombre in ["portada", *[b["nombre"] for b in logros(s)], "roles", "proyectos"]:
        destinos[nombre] = ("laminas", f"{nombre}.webp")
        destinos[f"{nombre}-celular"] = ("laminas", f"{nombre}-celular.webp")
    destinos |= {f'boton-{b["clave"]}': ("botones", f'{b["clave"]}.webp') for b in lista_botones}
    destinos |= {f'logo-{f["clave"]}': ("logos", f'{f["clave"]}.webp') for f in fichas}
    for carpeta in CALIDAD:
        (ACTIVOS / carpeta).mkdir(parents=True, exist_ok=True)
        for viejo in (ACTIVOS / carpeta).glob("*.webp"):
            viejo.unlink()
    archivo = ACTIVOS / ".imagenes.html"
    archivo.write_text(entorno(True).get_template("laminas.html.j2").render(
        s=s, t=t, logro=logro(s), logros=logros(s), premios=premios(s), botones=lista_botones, fichas=fichas, logos=logos,
        dominio=s["sitio"]["url"].removeprefix("https://").rstrip("/"), base=portafolio.as_uri() + "/"), encoding="utf-8")
    pesos = dict.fromkeys(CALIDAD, 0)
    async with async_playwright() as p:
        navegador = await p.chromium.launch()
        pagina = await navegador.new_page(viewport={"width": 1340, "height": 900}, device_scale_factor=ESCALA)
        await pagina.goto(archivo.as_uri(), wait_until="load")
        await pagina.evaluate("document.fonts.ready")
        await pagina.wait_for_timeout(300)
        for nombre, (carpeta, destino) in destinos.items():
            elemento = await pagina.query_selector(f'[data-nombre="{nombre}"]')
            if elemento is None:
                raise SystemExit(f"La plantilla no tiene «{nombre}»")
            png = await elemento.screenshot(type="png", omit_background=True)   # esquinas redondeadas: fondo transparente
            ruta = ACTIVOS / carpeta / destino
            opciones = {"lossless": True, "quality": 100} if CALIDAD[carpeta] is None else {"quality": CALIDAD[carpeta]}
            Image.open(io.BytesIO(png)).convert("RGBA").save(ruta, "WEBP", method=6, **opciones)
            pesos[carpeta] += ruta.stat().st_size
        await navegador.close()
    archivo.unlink()
    print("✓ imágenes en assets: " + " · ".join(f"{c} {v / 1024:,.0f} KB" for c, v in pesos.items())
          + f" · total {sum(pesos.values()) / 1024:,.0f} KB")


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
