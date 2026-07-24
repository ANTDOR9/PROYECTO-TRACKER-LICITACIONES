"""
Monitor de Licitaciones - Brighter Peru  (version NUBE / Streamlit Cloud)
Consulta la API publica de SEACE en vivo. No necesita base de datos local.
Archivo principal para desplegar en share.streamlit.io
"""
import unicodedata
import pandas as pd
import requests
import streamlit as st
import yaml, os

API = ("https://prod4.seace.gob.pe:8086/api/oportunidades/"
       "codObjeto/codDepartamento/sintesisProceso/codTipoProceso/0/0/0/0")

# --- Palabras clave (si no hay config.yaml, usa estas por defecto) ---
DEFAULT_CLAVES = [
    "pantalla interactiva","pantalla tactil","monitor interactivo","pizarra interactiva",
    "pizarra digital","pizarra electronica","panel interactivo","kiosco","kiosko","totem",
    "senalizacion digital","pantalla led","pantalla digital","videowall",
    "equipamiento audiovisual","proyector interactivo",
]
DEFAULT_EXCLUIR = ["protector de pantalla","mica de pantalla","lamina protectora"]

def cargar_config():
    ruta = os.path.join(os.path.dirname(__file__), "config.yaml")
    if os.path.exists(ruta):
        c = yaml.safe_load(open(ruta, encoding="utf-8"))
        return c.get("palabras_clave", DEFAULT_CLAVES), c.get("palabras_excluir", DEFAULT_EXCLUIR)
    return DEFAULT_CLAVES, DEFAULT_EXCLUIR

def norm(t):
    if not t: return ""
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()

def coincide(texto, claves, excluir):
    if any(x in texto for x in excluir): return False
    for clave in claves:
        toks = [t for t in clave.split() if len(t) >= 4]
        if toks and all(t in texto for t in toks): return True
    return False

@st.cache_data(ttl=3600)   # cachea 1 hora para no golpear la API en cada clic
def traer_vigentes():
    import urllib3; urllib3.disable_warnings()
    r = requests.get(API, timeout=120, verify=False)
    r.raise_for_status()
    data = r.json()
    claves = [norm(k) for k in DEFAULT_CLAVES]
    excluir = [norm(k) for k in DEFAULT_EXCLUIR]
    claves_cfg, excluir_cfg = cargar_config()
    claves = [norm(k) for k in claves_cfg]
    excluir = [norm(k) for k in excluir_cfg]
    filas = []
    for o in data:
        txt = norm(f"{o.get('detObjeto','')} {o.get('detItem','')} {o.get('sintesisProceso','')} {o.get('nomenclatura','')}")
        if coincide(txt, claves, excluir):
            filas.append({
                "Nomenclatura": o.get("nomenclatura",""),
                "Entidad": o.get("detEntidad",""),
                "Objeto": o.get("detObjeto",""),
                "Descripcion": o.get("detItem","") or o.get("sintesisProceso",""),
                "Valor referencial": pd.to_numeric(o.get("valorReferencial"), errors="coerce"),
                "Moneda": o.get("monedaProceso",""),
                "Tipo": o.get("detTipoProceso",""),
                "Fin inscripcion": o.get("fechaFin",""),
                "Presentacion propuestas": o.get("fechaPresentacionPropuestas",""),
            })
    return pd.DataFrame(filas), len(data)

st.set_page_config(page_title="Tracker de Licitaciones - Brighter", page_icon="📡", layout="wide")
st.title("📡 Tracker de Licitaciones — Brighter Perú")
st.caption("Oportunidades VIGENTES con el Estado: pantallas interactivas, pizarras digitales, "
           "kioscos y equipamiento audiovisual. Fuente: SEACE / OECE (en vivo).")

try:
    df, total = traer_vigentes()
except Exception as e:
    st.error(f"No se pudo consultar la API de SEACE.\n\n{e}")
    st.stop()

if df.empty:
    st.warning("No hay oportunidades vigentes que coincidan con el rubro en este momento.")
    st.stop()

st.sidebar.header("Filtros")
objetos = sorted(x for x in df["Objeto"].dropna().unique() if x)
so = st.sidebar.multiselect("Objeto", objetos)
vmin = st.sidebar.number_input("Valor referencial minimo (S/)", 0, step=1000, value=0)
txt = st.sidebar.text_input("Buscar en descripcion / entidad")

f = df.copy()
if so: f = f[f["Objeto"].isin(so)]
if vmin: f = f[f["Valor referencial"].fillna(0) >= vmin]
if txt:
    t = txt.lower()
    f = f[f["Descripcion"].str.lower().str.contains(t, na=False) |
          f["Entidad"].str.lower().str.contains(t, na=False)]

c1, c2, c3 = st.columns(3)
c1.metric("Oportunidades vigentes", len(f))
c2.metric("Valor referencial total", f"S/ {f['Valor referencial'].fillna(0).sum():,.0f}")
c3.metric("Total procesos revisados", f"{total:,}")

st.dataframe(f.sort_values("Fin inscripcion"), use_container_width=True, hide_index=True)

st.download_button("Descargar Excel", f.to_csv(index=False).encode("utf-8-sig"),
                   file_name="oportunidades_vigentes.csv", mime="text/csv")