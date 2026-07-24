"""
Extractor Peru Compras (Catalogos Electronicos / Acuerdos Marco)
-----------------------------------------------------------------
Descarga los archivos MENSUALES de datos abiertos de ordenes de compra por
catalogo (compras directas del Estado) y filtra el rubro Brighter.

Como funciona (sin scraping):
  1) POST getListaDescargaMasiva -> lista de archivos por mes.
  2) Cada archivo JSON vive en Azure Blob Storage y se descarga directo.
  3) Se filtra por palabras clave (busqueda generica sobre todos los textos
     del registro, asi funciona aunque no conozcamos los nombres exactos de
     los campos) y se guarda a CSV / SQLite.

Uso:
    python src/perucompras.py --anio 2023
    python src/perucompras.py --anio 2023 --inspeccionar   # solo muestra campos
    python src/perucompras.py --archivo local.json          # prueba con archivo local
"""
import argparse, json, os, sqlite3, unicodedata
import yaml

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LISTA_URL = "https://www.catalogos.perucompras.gob.pe/ConsultaOrdenesPub/getListaDescargaMasiva"
BLOB_BASE = "https://saeusceprod01.blob.core.windows.net/"

def cfg():
    return yaml.safe_load(open(os.path.join(BASE, "config.yaml"), encoding="utf-8"))

def norm(t):
    if t is None: return ""
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()

def aplanar_texto(registro):
    """Concatena TODOS los valores de texto del registro (recursivo)."""
    partes = []
    def rec(v):
        if isinstance(v, dict):
            for x in v.values(): rec(x)
        elif isinstance(v, list):
            for x in v: rec(x)
        elif isinstance(v, (str, int, float)):
            partes.append(str(v))
    rec(registro)
    return norm(" | ".join(partes))

def clasifica(texto, claves_por_cat, excluir):
    if any(x in texto for x in excluir): return None
    for cat, terminos in claves_por_cat.items():
        for termino in terminos:
            toks = [t for t in norm(termino).split() if len(t) >= 4]
            if toks and all(t in texto for t in toks): return cat
    return None

def listar_archivos(anio):
    import requests
    r = requests.post(LISTA_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                 "X-Requested-With": "XMLHttpRequest"},
        data={"Anio": anio, "Mes": ""}, timeout=60)
    r.raise_for_status()
    return r.json()

def descargar_json(item):
    import requests
    url = BLOB_BASE + item["C_Ruta"].strip("/") + "/" + item["C_FileJson"]
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    # Los archivos traen caracteres de control crudos -> parse tolerante
    texto = r.content.decode("utf-8", errors="replace")
    return json.loads(texto, strict=False)

def registros(data):
    """Normaliza la respuesta a una lista de registros, sea cual sea su forma."""
    if isinstance(data, list): return data
    if isinstance(data, dict):
        for k in ("releases", "records", "data", "ordenes", "result"):
            if isinstance(data.get(k), list): return data[k]
        return [data]
    return []

def procesar(data, c, inspeccionar=False):
    regs = registros(data)
    if inspeccionar and regs:
        print("Campos del primer registro:")
        print(" ", list(regs[0].keys()) if isinstance(regs[0], dict) else type(regs[0]))
        print(f"  ({len(regs)} registros en el archivo)")
    claves = {cat: [norm(t) for t in terms] for cat, terms in c["palabras_clave"].items()}
    excluir = [norm(t) for t in c.get("palabras_excluir", [])]
    filas = []
    for reg in regs:
        cat = clasifica(aplanar_texto(reg), claves, excluir)
        if cat:
            reg = dict(reg) if isinstance(reg, dict) else {"valor": reg}
            reg["_categoria"] = cat
            filas.append(reg)
    return filas

def guardar_csv(filas, ruta):
    import csv
    if not filas: return
    campos = sorted({k for f in filas for k in f.keys()})
    with open(ruta, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for f in filas: w.writerow(f)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anio", type=int, default=2023)
    ap.add_argument("--archivo", help="JSON local (prueba)")
    ap.add_argument("--inspeccionar", action="store_true")
    a = ap.parse_args()
    c = cfg()

    todas = []
    if a.archivo:
        data = json.loads(open(a.archivo, encoding="utf-8", errors="replace").read(), strict=False)
        todas = procesar(data, c, a.inspeccionar)
    else:
        items = listar_archivos(a.anio)
        print(f"Peru Compras {a.anio}: {len(items)} archivos mensuales.")
        for it in items:
            if not it.get("C_FileJson"): continue
            print(f"  Descargando {it.get('C_Mes')} ...")
            try:
                data = descargar_json(it)
            except Exception as e:
                print(f"    (error: {e})"); continue
            filas = procesar(data, c, a.inspeccionar)
            print(f"    {it.get('C_Mes')}: {len(filas)} relevantes")
            todas += filas
            if a.inspeccionar: break   # con inspeccionar, basta el primer mes

    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    salida = os.path.join(BASE, "data", f"perucompras_{a.anio}.csv")
    guardar_csv(todas, salida)
    print(f"\nTotal relevantes Peru Compras: {len(todas)} -> {salida}")

if __name__ == "__main__":
    main()