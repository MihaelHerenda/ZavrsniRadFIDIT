import camelot
import re
import pandas as pd
from datetime import datetime
import pickle
import os
import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import gc  

# -----------------------------------------------------------------------------
# KONFIGURACIJA I STILIZACIJA
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Ispitni Kalendar PDS/DS", page_icon="📅", layout="wide")

st.markdown("""
    <style>
    .stMultiSelect[data-baseweb="tag"] { background-color: #007bff !important; color: white !important; }
    .semester-header { color: #1f4e79; border-bottom: 2px solid #dee2e6; padding-bottom: 5px; margin-top: 20px; }
    div[st-decorator="true"] { display:none; }
    </style>
    """, unsafe_allow_html=True)

# Definicija svih službenih planova i njihovih konfiguracija
SLUZBENI_PROGRAMI = {
    "Prijediplomski studij": {
        "pdf": "Izvedbeni_program_Prijediplomski.pdf",
        "cache": "cache_pds.pkl"
    },
    "Diplomski studij (Opći)": {
        "pdf": "Izvedbeni_program_Diplomski_Opci.pdf",
        "cache": "cache_ds_opci.pkl"
    },
    "Diplomski studij (Nastavnički)": {
        "pdf": "Izvedbeni_program_Diplomski_Nastavnicki.pdf",
        "cache": "cache_ds_nast.pkl"
    },
    "Diplomski studij (Nastavnički paket)": {
        "pdf": "Izvedbeni_program_Nastavnicki_paket.pdf",
        "cache": "cache_ds_paket.pkl"
    }
}

KATEGORIJE = {
    "nadoknade": {
        "ukljuci":[r"nadoknad\w*", r"popravn\w*", r"isprav\w*", r"poprav\w*"],
        "iskljuci":[r"(?<!\w)(uput\w*)", r"(?<!\w)(17\.11\.\w*)", r"Python Matplotlib"],
    },
    "ispiti": {
        "ukljuci":[r"samoprovjer\w*", r"ispit\w*", r"\blab\b", r"labo\w*", r"provjer\w*", r"kolokvij\w*", r"kviz\w*", r"kontroln\w*", r"test\w*", r"rok\w*", r"\bdz\b", r"domać\w*", r"PZ\w*"],
        "iskljuci":[r"priprem\w*", r"grešak\w*", r"testira\w*", r"u tjednu.*nema", r"kontrolni postupci", r"temelj kontrolnog", r"(?<!\w)(uput\w*)", r"odabir\w*", r"oblikovan\w*", r"definiran\w*", r"ponavljanje\w*", r"testnih", r"priprema", r"dovršavanje", r"zadavanje", r"sudova", r"binarnih relacija", r"\w*bijektivnosti funkcije\w*", r"kompozicije"],
    },
    "dz": {
        "ukljuci":[r"usmen\w*", r"obran\w*", r"seminar\w*", r"zadatk\w*", r"projekt\w*", r"prezentacij\w*", r"izlaganj\w*", r"predaja"],
        "iskljuci":[r"predstavljanje tem\w*", r"odabir\w*", r"indukcij\w*", r"(?<!\w)(uput\w*)", r"raspodjel\w*", r"grupama\w*", r"konzult\w*", r"rad na", r"zadavanje\w*", r"ocjen\w*", r"definiran\w*", r"projektiranje IS", r"izrad\w*", r"životni ciklus", r"upravljanje", r"stvaranje", r"rješavanje", r"zadavanje", r"arhitektura", r"postavke", r"projektni pristup", r"primjena", r"projektni jezik", r"domaće zadaće", r"oblikovanje", r"predaja obrazaca", r"prezentacija informacija", r"bijektivnosti funkcije"],
    },
}

# -----------------------------------------------------------------------------
# WEB SCRAPER LOGIKA
# -----------------------------------------------------------------------------
def scrape_and_download():
    url = "https://www.inf.uniri.hr/nastava/izvedbeni-planovi"
    baza_url = "https://www.inf.uniri.hr" 
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, 'html.parser')
        
        pronadjeno = 0
        for a in soup.find_all('a'):
            href = a.get('href')
            if not href or not href.endswith('.pdf'):
                continue
                
            tekst_linka = a.text.lower().strip()
            
            prog_key = None
            if "prijediplomskog" in tekst_linka:
                prog_key = "Prijediplomski studij"
            elif "diplomskog" in tekst_linka:
                if "paket" in tekst_linka:
                    prog_key = "Diplomski studij (Nastavnički paket)"
                elif "nastavnički" in tekst_linka or "nastavnicki" in tekst_linka:
                    prog_key = "Diplomski studij (Nastavnički)"
                else:
                    prog_key = "Diplomski studij (Opći)"
            
            if prog_key:
                puni_pdf_link = urljoin(baza_url, href)
                pdf_data = requests.get(puni_pdf_link, headers=headers).content
                naziv_datoteke = SLUZBENI_PROGRAMI[prog_key]["pdf"]
                
                try:
                    with open(naziv_datoteke, 'wb') as f:
                        f.write(pdf_data)
                except PermissionError:
                    st.error(f"⚠️ Nije moguće osvježiti dokument '{naziv_datoteke}'. Čini se da vam je taj PDF otvoren u nekom drugom programu. Zatvorite PDF i pokušajte ponovno.")
                    continue
                
                cache_file = SLUZBENI_PROGRAMI[prog_key]["cache"]
                if os.path.exists(cache_file):
                    os.remove(cache_file)
                
                pronadjeno += 1

        st.cache_data.clear()
        return pronadjeno > 0
    except Exception as e:
        st.error(f"Došlo je do greške prilikom preuzimanja s weba: {e}")
        return False

# -----------------------------------------------------------------------------
# LOGIKA OBRADE PODATAKA I POMOĆNE FUNKCIJE
# -----------------------------------------------------------------------------

def napravi_kraticu(naziv):
    rijeci = re.split(r'[\s\-]+', naziv)
    kratica = ""
    for r in rijeci:
        m = re.search(r'[a-zA-ZčćžšđČĆŽŠĐ0-9]', r)
        if m:
            kratica += m.group().upper()
    return kratica

def normaliziraj_datum_prikaz(dt, sirovi_string):
    if dt and dt.year != 2099:
        return dt.strftime("%d.%m.%Y.")
    cisto = re.sub(r"\s+", "", sirovi_string)
    if not cisto.endswith("."): cisto += "."
    return cisto

def pretvori_u_datetime(datum_str):
    try:
        datum_str = datum_str.replace(" ", "").strip()
        parts = re.match(r"(\d{1,2})\.(\d{1,2})\.?(\d{2,4})?", datum_str)
        if parts:
            dan, mjesec = int(parts.group(1)), int(parts.group(2))
            godina_match = parts.group(3)
            if godina_match:
                godina = (2000 + int(godina_match)) if len(godina_match) == 2 else int(godina_match)
            else:
                sada = datetime.now()
                pocetak_akademske = sada.year if sada.month >= 8 else sada.year - 1
                godina = pocetak_akademske if mjesec >= 8 else pocetak_akademske + 1
            return datetime(godina, mjesec, dan)
    except: return None
    return None

@st.cache_data(show_spinner=False)
def ucitaj_podatke(pdf_putanje, cache_fajl=None):
    if cache_fajl and os.path.exists(cache_fajl):
        with open(cache_fajl, "rb") as f: 
            tablice_dfs = pickle.load(f)
    else:
        tablice_dfs =[]
        for doc_putanja in pdf_putanje:
            try:
                ukupno_stranica = None
                try:
                    import pypdf
                    with open(doc_putanja, "rb") as f: ukupno_stranica = len(pypdf.PdfReader(f).pages)
                except ImportError:
                    try:
                        import PyPDF2
                        with open(doc_putanja, "rb") as f: ukupno_stranica = len(PyPDF2.PdfReader(f).pages)
                    except ImportError: pass
                
                if ukupno_stranica:
                    velicina_bloka = 10
                    for start_str in range(1, ukupno_stranica + 1, velicina_bloka):
                        kraj_str = min(start_str + velicina_bloka - 1, ukupno_stranica)
                        stranice_str = f"{start_str}-{kraj_str}"
                        
                        tablice = camelot.read_pdf(doc_putanja, pages=stranice_str)
                        for t in tablice:
                            tablice_dfs.append(t.df.copy())
                        
                        del tablice
                        gc.collect()
                else:
                    tablice = camelot.read_pdf(doc_putanja, pages="all")
                    for t in tablice:
                        tablice_dfs.append(t.df.copy())
                    del tablice
                    gc.collect()

            except Exception as e:
                st.warning(f"Problem sa čitanjem dokumenta {doc_putanja}: {e}")
                
        if cache_fajl and tablice_dfs:
            with open(cache_fajl, "wb") as f: 
                pickle.dump(tablice_dfs, f)
            
    naziv_datumi_dict, naziv_semestar_dict = {}, {} 
    i = 0
    while i < len(tablice_dfs):
        df = tablice_dfs[i]
        je_naslov, novi_naziv, semestar = False, "", ""
        try:
            c1, c0 = str(df.iloc[1,0]), str(df.iloc[0,0])
            if "Naziv kolegija" in c1:
                novi_naziv = str(df.iloc[1,1]).replace('\n', ' ').strip()
                semestar = str(df.iloc[4,1]).strip() if df.shape[0]>4 else "Ostalo"
                je_naslov = True
            elif "Naziv kolegija" in c0:
                novi_naziv = str(df.iloc[0,1]).replace('\n', ' ').strip()
                semestar = str(df.iloc[3,1]).strip() if df.shape[0]>3 else "Ostalo"
                je_naslov = True
            
            if je_naslov:
                if semestar and semestar[0].isdigit():
                    broj = semestar.split('.')[0]
                    semestar = f"{broj}. Semestar"
                elif not semestar or len(semestar) > 30:
                    semestar = "Ostalo"
                naziv_semestar_dict[novi_naziv] = semestar
                naziv_kolegija = novi_naziv
        except: pass

        if not je_naslov:
            try:
                zaglavlje = " ".join([str(x) for x in df.iloc[0].values])
                if "Datum" in zaglavlje:
                    spojena, cols = df, df.shape[1]
                    i += 1
                    while i < len(tablice_dfs):
                        ndf = tablice_dfs[i]
                        if ndf.shape[1] == cols and "Naziv kolegija" not in str(ndf.iloc[0,0]):
                            spojena = pd.concat([spojena, ndf.iloc[1:] if "Datum" in str(ndf.iloc[0,0]) else ndf], ignore_index=True)
                            i += 1
                        else: break
                    i -= 1
                    if 'naziv_kolegija' in locals(): naziv_datumi_dict[naziv_kolegija] = spojena
            except: pass
        i += 1

    svi_ispiti =[]
    for kolegij, df_d in naziv_datumi_dict.items():
        if df_d.shape[1] < 4: continue
        p_dat, p_rez = "", ""
        for idx, tekst in df_d.iloc[1:, 3].items():
            if not isinstance(tekst, str) or not tekst.strip(): continue
            for _, pravila in KATEGORIJE.items():
                if re.search(r"\b(" + "|".join(pravila["ukljuci"]) + r")\b", tekst, re.I):
                    if pravila["iskljuci"] and re.search("(" + "|".join(pravila["iskljuci"]) + ")", tekst, re.I): break
                    s_dat = str(df_d.iloc[idx, 1]).replace('\n', '').strip()
                    if s_dat in ["", "None"] and idx > 1: s_dat = str(df_d.iloc[idx-1, 1]).strip()
                    d_m = re.search(r"\d{1,2}[.]\d{1,2}[.\d]*", s_dat)
                    c_dat_sirovi = d_m.group().strip() if d_m else s_dat
                    rez = tekst.replace("\n", " ")
                    c_m = re.search(r'\s{3,}(.+?)(?:\s{3,}|$)', rez)
                    rez = c_m.group(1).strip() if c_m else rez.strip()
                    dt = pretvori_u_datetime(c_dat_sirovi)
                    formatiran_datum = normaliziraj_datum_prikaz(dt, c_dat_sirovi)
                    if formatiran_datum == p_dat and rez == p_rez: break
                    svi_ispiti.append({
                        "kolegij": kolegij, "semestar": naziv_semestar_dict.get(kolegij, "Ostalo"), 
                        "datum_obj": dt or datetime(2099,1,1), "datum_prikaz": formatiran_datum, "aktivnost": rez
                    })
                    p_dat, p_rez = formatiran_datum, rez
                    break 
    return sorted(svi_ispiti, key=lambda x: x['datum_obj']), naziv_semestar_dict

# -----------------------------------------------------------------------------
# UI/UX SUČELJE
# -----------------------------------------------------------------------------
def main():
    st.title("📅 Pametni Ispitni Kalendar")

    st.sidebar.title("Postavke aplikacije")
    izvor_podataka = st.sidebar.radio("Odaberite izvor podataka:",["Službeni izvedbeni planovi FIDIT-a", "Moji PDF-ovi (Custom)"])
    
    pdf_liste = ()
    cache_to_use = None
    podnaslov = ""

    if izvor_podataka == "Službeni izvedbeni planovi FIDIT-a":
        odabrani_studij = st.sidebar.selectbox("Razina i smjer studija:", list(SLUZBENI_PROGRAMI.keys()))
        podnaslov = f"{odabrani_studij} Informatike FIDIT"
        
        podaci = SLUZBENI_PROGRAMI[odabrani_studij]
        pdf_fajl = podaci["pdf"]
        cache_to_use = podaci["cache"]
        
        # AUTOMATSKO PREUZIMANJE S WEBA AKO SERVER NEMA DOKUMENTE (Na cloud deploymentu)
        if not os.path.exists(pdf_fajl) and not os.path.exists(cache_to_use):
            st.toast("Pripremam podatke na poslužitelju...", icon="📥")
            with st.spinner(f"Automatsko preuzimanje dokumenata s weba (Prvo pokretanje)..."):
                uspjeh = scrape_and_download()
                if not uspjeh or not os.path.exists(pdf_fajl):
                    st.error("Nije moguće preuzeti izvedbene planove. Provjerite vezu ili pokušajte kasnije.")
                    st.stop()
        
        with st.sidebar.expander("🛠️ Admin / Ažuriranje podataka"):
            st.write("Klikom na gumb ažurirat će se svi službeni PDF-ovi izravno sa stranice fakulteta.")
            if st.button("⬇️ Osvježi podatke s weba", width="stretch"):
                with st.spinner("Preuzimam datoteke s weba... To može potrajati par sekundi."):
                    uspjeh = scrape_and_download()
                if uspjeh:
                    st.success("✅ Datoteke uspješno ažurirane! Spremno za instant prikaz.")
                else:
                    st.warning("Ažuriranje djelomično ili potpuno neuspješno. Provjerite greške iznad.")

        if not os.path.exists(pdf_fajl) and not os.path.exists(cache_to_use):
            st.error("Greška: Niti postoji PDF niti Cache za ovaj program. Molim vas ažurirajte podatke u Admin panelu.")
            st.stop()
            
        pdf_liste = (pdf_fajl,) # Korištenje TUPLE-a popravlja problem sa Streamlit memorijom!

    else:
        podnaslov = "Vlastiti izvedbeni planovi (Custom)"
        
        st.sidebar.markdown("---")
        st.sidebar.info("Ovdje možete ubaciti jedan ili više izvedbenih planova. Sustav će ih spojiti u jedan raspored.")
        
        uploaded_files = st.sidebar.file_uploader("Učitajte svoje PDF-ove:", type="pdf", accept_multiple_files=True)
        
        if not uploaded_files:
            st.info("👈 Molimo učitajte barem jedan PDF dokument u izborniku lijevo.")
            st.stop()
            
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        
        temp_paths =[]
        for f in uploaded_files:
            file_path = os.path.join(temp_dir, f.name)
            with open(file_path, "wb") as tmp:
                tmp.write(f.getvalue())
            temp_paths.append(file_path)
            
        pdf_liste = tuple(temp_paths)
        cache_to_use = None 

    st.markdown(f"##### {podnaslov}")

    # Učitavanje podataka
    with st.spinner("Očitavam podatke (Može potrajati par minuta ako server nema Cache)..." if not cache_to_use or not os.path.exists(cache_to_use) else "Učitavam podatke iz memorije..."):
        svi_ispiti, svi_predmeti = ucitaj_podatke(pdf_liste, cache_to_use)

    if not svi_predmeti:
        st.error("Nisam uspio izvući niti jedan kolegij iz predanih PDF-ova. Provjerite radi li se o ispravnom izvedbenom programu.")
        st.stop()

    semestri_mape = {}
    for kol, sem in svi_predmeti.items():
        if sem not in semestri_mape: semestri_mape[sem] =[]
        semestri_mape[sem].append(kol)

    # GLAVNI DIO 
    st.markdown("### 🎯 Odabir Predmeta")
    odabrani_kolegiji =[]
    sortirani_semestri = sorted(semestri_mape.keys(), key=lambda x: x if not x[0].isdigit() else f"{int(x.split('.')[0]):02d}")
    
    for sem_naziv in sortirani_semestri:
        st.markdown(f"<h4 class='semester-header'>{sem_naziv}</h4>", unsafe_allow_html=True)
        label_semestar = sem_naziv.replace("Semestar", "semestra")
        
        odabir = st.multiselect(
            f"Odaberi kolegije {label_semestar}:", 
            options=sorted(semestri_mape[sem_naziv]),
            key=f"ms_{izvor_podataka}_{sem_naziv}"
        )
        odabrani_kolegiji.extend(odabir)
    
    st.divider()
    
    st.markdown("### ⚙️ Postavke prikaza")
    prikaz_kolegija = st.radio("Format naziva kolegija u kalendaru:",["Puno ime", "Kratica", "Kratica + Puno ime"], horizontal=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if "prikazi_raspored" not in st.session_state:
        st.session_state.prikazi_raspored = False

    if st.button("🚀 Kreiraj raspored", width="stretch"):
        if odabrani_kolegiji:
            st.session_state.prikazi_raspored = True
            st.balloons()
        else:
            st.warning("⚠️ Molimo prvo odaberite barem jedan kolegij.")
            st.session_state.prikazi_raspored = False

    if st.session_state.prikazi_raspored and odabrani_kolegiji:
        
        st.markdown("## 🗓️ Vaš Raspored")
        
        filtrirani =[]
        for x in svi_ispiti:
            if x['kolegij'] in odabrani_kolegiji:
                novi_x = dict(x) 
                
                if prikaz_kolegija == "Kratica":
                    novi_x['kolegij'] = napravi_kraticu(novi_x['kolegij'])
                elif prikaz_kolegija == "Kratica + Puno ime":
                    novi_x['kolegij'] = f"{napravi_kraticu(novi_x['kolegij'])} - {novi_x['kolegij']}"
                    
                filtrirani.append(novi_x)
        
        m1, m2 = st.columns(2)
        m1.metric("Odabrano kolegija", len(odabrani_kolegiji))
        m2.metric("Ukupno obveza", len(filtrirani))

        if filtrirani:
            df_final = pd.DataFrame(filtrirani).drop(columns=['datum_obj'])
            df_final = df_final[["datum_prikaz", "kolegij", "aktivnost", "semestar"]]
            df_final.columns =["Datum", "Kolegij", "Aktivnost", "Semestar"]
            
            st.dataframe(df_final, width="stretch", hide_index=True)

            st.markdown("### 📥 Izvoz podataka", unsafe_allow_html=True)
            txt_content = f"MOJ KALENDAR OBAVEZA\n{'='*80}\n"
            for x in filtrirani:
                sirina_kolegija = 35 if prikaz_kolegija == "Puno ime" else (10 if prikaz_kolegija == "Kratica" else 45)
                txt_content += f"{x['datum_prikaz']:<15} | {x['kolegij']:<{sirina_kolegija}} | {x['aktivnost']}\n"
            
            st.download_button("📥 Preuzmi .txt raspored", txt_content, "moj_kalendar.txt", width="stretch")
        else:
            st.warning("Za odabrane kolegije nema zapisanih obaveza u bazi.")

if __name__ == "__main__":
    main()