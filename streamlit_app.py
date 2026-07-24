"""
TRACKER DE LICITACIONES - Brighter Peru   (version NUBE / Streamlit Cloud)
Oportunidades VIGENTES con el Estado (a que postular ahora), en vivo desde
la API publica de SEACE. Combina: palabras clave por categoria + exclusiones
inteligentes + etiquetado por categoria. No necesita base de datos local.
"""
import os, unicodedata
import pandas as pd
import requests
import streamlit as st
import yaml

API = ("https://prod4.seace.gob.pe:8086/api/oportunidades/"
       "codObjeto/codDepartamento/sintesisProceso/codTipoProceso/0/0/0/0")

# Respaldo por si no hay config.yaml
DEF_CLAVES = {"Pantallas interactivas": ["pantalla interactiva","pizarra digital","monitor interactivo"]}
DEF_EXCLUIR = ["protector de pantalla","luminaria","presa","drone"]

def norm(t):
    if not t: return ""
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()

def cargar_config():
    ruta = os.path.join(os.path.dirname(__file__), "config.yaml")
    if os.path.exists(ruta):
        c = yaml.safe_load(open(ruta, encoding="utf-8"))
        return c.get("palabras_clave", DEF_CLAVES), c.get("palabras_excluir", DEF_EXCLUIR)
    return DEF_CLAVES, DEF_EXCLUIR

def clasifica(texto_norm, claves_por_cat, excluir):
    """Devuelve la categoria si coincide (tolera plurales), o None."""
    if any(x in texto_norm for x in excluir):
        return None
    for categoria, terminos in claves_por_cat.items():
        for termino in terminos:
            toks = [t for t in norm(termino).split() if len(t) >= 4]
            if toks and all(t in texto_norm for t in toks):
                return categoria
    return None

def num(v):
    return pd.to_numeric(str(v).replace(",", "") if v is not None else None, errors="coerce")

@st.cache_data(ttl=3600)
def traer_vigentes():
    import urllib3; urllib3.disable_warnings()
    r = requests.get(API, timeout=120, verify=False)
    r.raise_for_status()
    data = r.json()
    claves_cfg, excluir_cfg = cargar_config()
    claves = {cat: [norm(t) for t in terms] for cat, terms in claves_cfg.items()}
    excluir = [norm(t) for t in excluir_cfg]
    filas = []
    for o in data:
        txt = norm(f"{o.get('detObjeto','')} {o.get('detItem','')} {o.get('sintesisProceso','')} {o.get('nomenclatura','')}")
        cat = clasifica(txt, claves, excluir)
        if cat:
            # valor: primero el del proceso, si no el del item
            valor = num(o.get("valorReferencial"))
            if pd.isna(valor):
                valor = num(o.get("valorReferencialItem"))
            filas.append({
                "Categoria": cat,
                "Nomenclatura": o.get("nomenclatura",""),
                "Entidad": o.get("detEntidad",""),
                "Objeto": o.get("detObjeto",""),
                "Descripcion": o.get("detItem","") or o.get("sintesisProceso",""),
                "Valor referencial": valor,
                "Moneda": o.get("monedaProceso",""),
                "Tipo": o.get("detTipoProceso",""),
                "Fin inscripcion": o.get("fechaFin",""),
                "Presentacion propuestas": o.get("fechaPresentacionPropuestas",""),
            })
    return pd.DataFrame(filas), len(data)

st.set_page_config(page_title="Tracker de Licitaciones - Brighter", page_icon="📡", layout="wide")
st.title("📡 Tracker de Licitaciones — Brighter Perú")
st.caption("Oportunidades VIGENTES con el Estado (a las que postular ahora): pantallas interactivas, "
           "pizarras digitales, kioscos y equipamiento audiovisual. Fuente: SEACE / OECE (en vivo).")

try:
    df, total = traer_vigentes()
except Exception as e:
    st.error(f"No se pudo consultar la API de SEACE en este momento.\n\n{e}")
    st.info("Puede pasar si la API esta temporalmente caida. Intenta de nuevo en unos minutos.")
    st.stop()

if df.empty:
    st.warning("No hay oportunidades vigentes que coincidan con el rubro en este momento.")
    st.stop()

st.sidebar.header("Filtros")
cats = sorted(df["Categoria"].dropna().unique())
sel_cat = st.sidebar.multiselect("Categoría", cats, default=cats)
objetos = sorted(x for x in df["Objeto"].dropna().unique() if x)
sel_obj = st.sidebar.multiselect("Objeto", objetos)
vmin = st.sidebar.number_input("Valor referencial mínimo (S/)", 0, step=1000, value=0)
txt = st.sidebar.text_input("Buscar en descripción / entidad")

f = df.copy()
if sel_cat: f = f[f["Categoria"].isin(sel_cat)]
if sel_obj: f = f[f["Objeto"].isin(sel_obj)]
if vmin: f = f[f["Valor referencial"].fillna(0) >= vmin]
if txt:
    t = txt.lower()
    f = f[f["Descripcion"].str.lower().str.contains(t, na=False) |
          f["Entidad"].str.lower().str.contains(t, na=False)]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Oportunidades vigentes", len(f))
c2.metric("Valor referencial total", f"S/ {f['Valor referencial'].fillna(0).sum():,.0f}")
c3.metric("Categorías", f["Categoria"].nunique())
c4.metric("Procesos revisados", f"{total:,}")

st.divider()
st.dataframe(f.sort_values("Fin inscripcion"), use_container_width=True, hide_index=True)

# Resumen por categoria
with st.expander("Resumen por categoría"):
    resumen = (f.groupby("Categoria")
                 .agg(Oportunidades=("Nomenclatura","count"),
                      Valor_total=("Valor referencial","sum"))
                 .reset_index())
    st.dataframe(resumen, use_container_width=True, hide_index=True)

st.download_button("⬇️ Descargar Excel (CSV)",
                   f.to_csv(index=False).encode("utf-8-sig"),
                   file_name="tracker_licitaciones_vigentes.csv", mime="text/csv")
