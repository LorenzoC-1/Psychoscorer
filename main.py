"""
PsychoScorer — v4
Piattaforma di Scoring Clinico e Sperimentale

Copyright (c) 2026 Lorenzo Calanca. Tutti i diritti riservati.

Questo software è distribuito a titolo gratuito (Freeware).
L'utilizzo per l'attività clinica e la libera professione è pienamente autorizzato.
È invece severamente vietata la rivendita, l'affitto o la distribuzione
a pagamento del software stesso o del suo codice sorgente.

ATTENZIONE: Il programma è fornito come mero strumento di supporto.
Non si garantisce la correttezza dei risultati calcolati. La verifica
dei punteggi e l'interpretazione clinica dei dati rimangono sotto l'esclusiva
responsabilità e supervisione del professionista che utilizza il software.

Per i termini completi, consultare il file LICENSE allegato.
"""

import os, json, datetime, shutil, tempfile, subprocess, sys, re, zipfile
import customtkinter as ctk
from tkinter import messagebox, filedialog
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import textwrap
from scipy import stats as scipy_stats
from xml.sax.saxutils import escape as xml_escape
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                Table, TableStyle, Image as RLImage, PageBreak, KeepTogether, CondPageBreak)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader

# ─────────────────────────────────────────────
#  GESTIONE CONFIGURAZIONI GLOBALI
# ─────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config_app.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "logo_path": "",
        "logo_position": "destra",
        "footer_text": "Report generato automaticamente da PsychoScorer",
        "firma_text": "",
        "tema": "System",
        "zoom_ui": "100%"
    }

def save_config(conf):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=4, ensure_ascii=False)


def registra_estensioni_windows():
    """Registra le icone .psyt e .psyp e il doppio clic nel registro utente di Windows."""
    if not sys.platform.startswith('win'):
        return False, "Funzione disponibile solo su Windows."
    try:
        import winreg, ctypes

        ico_default = os.path.join(BASE_DIR, "icona.ico")
        ico_psyt = os.path.join(BASE_DIR, "icona_psyt.ico")
        ico_psyp = os.path.join(BASE_DIR, "icona_psyp.ico")

        if not os.path.exists(ico_psyt): ico_psyt = ico_default
        if not os.path.exists(ico_psyp): ico_psyp = ico_default

        # Determina il comando di apertura (funziona sia da script .py che da futuro .exe)
        if getattr(sys, 'frozen', False):
            cmd_base = f'"{sys.executable}"'
        else:
            py_exe = sys.executable
            pyw_exe = py_exe.replace("python.exe", "pythonw.exe")
            if os.path.exists(pyw_exe): py_exe = pyw_exe
            script_path = os.path.abspath(__file__)
            cmd_base = f'"{py_exe}" "{script_path}"'

        estensioni = [
            (".psyt", "PsychoScorer.Test", "PsychoScorer Test File", ico_psyt),
            (".psyp", "PsychoScorer.Package", "PsychoScorer Package Bundle", ico_psyp)
        ]

        for ext, prog_id, desc, icon_path in estensioni:
            # 1. Associa l'estensione al ProgID
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"Software\\Classes\\{ext}") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, prog_id)

            # 2. Descrizione del tipo di file
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"Software\\Classes\\{prog_id}") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, desc)

            # 3. Imposta l'icona personalizzata
            if os.path.exists(icon_path):
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"Software\\Classes\\{prog_id}\\DefaultIcon") as key:
                    winreg.SetValue(key, "", winreg.REG_SZ, f'"{icon_path}",0')

            # 4. Comando di apertura al doppio clic
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                  f"Software\\Classes\\{prog_id}\\shell\\open\\command") as key:
                winreg.SetValue(key, "", winreg.REG_SZ, f'{cmd_base} "%1"')

        # Notifica a Windows Explorer di aggiornare subito la cache delle icone
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        return True, "Icone ed estensioni (.psyt / .psyp) registrate con successo in Windows!"
    except Exception as e:
        return False, f"Errore durante la registrazione nel sistema:\n{e}"

# ─────────────────────────────────────────────
#  TEST ENGINE (A DUE FASI)
# ─────────────────────────────────────────────

class TestEngine:
    def __init__(self, file_path):
        self.file_path = file_path
        if file_path.endswith('.psyt'):
            with zipfile.ZipFile(file_path, 'r') as z:
                with z.open('test.json') as f:
                    self.data = json.load(f)
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)

        info = self.data.get('info_generali', {})
        self.nome = info.get('nome', 'Test Sconosciuto')
        self.autore = info.get('autore', '')
        self.istruzioni = info.get('istruzioni', '')
        self.anagrafica = self.data.get('dati_richiesti', {}).get('anagrafica', [])
        self.sezioni = self.data.get('sezioni', [])
        self.dimensioni = self.data.get('dimensioni', [])
        self.ultimi_errori = []   # problemi bloccanti dell'ultimo calcolo
        self.ultimi_avvisi = []   # avvisi non bloccanti dell'ultimo calcolo

    @staticmethod
    def _format_num(val):
        """Arrotonda a 2 decimali e converte in int se il numero è intero (es. 12.0 -> 12)."""
        r = round(float(val), 2)
        return int(r) if r.is_integer() else r

    @staticmethod
    def valida_soglie_pe(pe_soglie):
        """Ritorna (ok, messaggio). Servono 4 soglie numeriche, tutte crescenti o tutte decrescenti."""
        if not pe_soglie:
            return True, ""
        if len(pe_soglie) != 4:
            return False, "servono esattamente 4 soglie"
        try:
            s = [float(x) for x in pe_soglie]
        except (ValueError, TypeError):
            return False, "le soglie devono essere numeriche"
        if s[0] == s[3]:
            return False, "prima e ultima soglia coincidono: direzione della scala non determinabile"
        if s[3] > s[0]:
            ok = all(s[i] <= s[i + 1] for i in range(3))
        else:
            ok = all(s[i] >= s[i + 1] for i in range(3))
        if not ok:
            return False, "le soglie devono essere ordinate (tutte crescenti oppure tutte decrescenti)"
        return True, ""

    @staticmethod
    def _calcola_pe(punteggio, pe_soglie, confine='alto'):
        """Punteggio Equivalente (0-4) per scale dirette (soglie crescenti) e inverse (decrescenti).

        confine='alto'  : punteggio == soglia  -> PE superiore (comportamento storico dell'app)
        confine='basso' : punteggio == soglia  -> PE inferiore (es. "<= cut-off = deficitario")
        Il PE e' il numero di soglie che il punteggio ha raggiunto/superato nella direzione della scala.
        Il confronto usa il valore esatto (arrotondato a 9 decimali solo per eliminare il rumore dei float).
        """
        if not pe_soglie or not TestEngine.valida_soglie_pe(pe_soglie)[0]:
            return None
        s = [float(x) for x in pe_soglie]
        x = round(float(punteggio), 9)
        eps = 1e-9
        diretta = s[3] > s[0]
        if confine == 'basso':
            return sum(1 for t in s if (x > t + eps if diretta else x < t - eps))
        return sum(1 for t in s if (x >= t - eps if diretta else x <= t + eps))

    def rileva_item_critici(self, risposte_per_sezione):
        """Restituisce la lista degli item critici (Red Flags) attivati dalle risposte del paziente."""
        critici_attivati = []

        for sez in self.sezioni:
            sez_id = sez['id']
            tipo = sez['tipo']
            risposte_sez = risposte_per_sezione.get(sez_id, {})
            etichette = sez.get('opzioni_etichette', [])
            valori = sez.get('opzioni_valori', [])

            for item in sez.get('items', []):
                crit = item.get('critico')
                if not crit or crit.get('op', 'No') == 'No':
                    continue
                iid = item['id']
                if iid not in risposte_sez:
                    continue

                op = crit.get('op')
                target_raw = str(crit.get('valore', '')).strip()
                nota = crit.get('nota', '').strip()
                attivato = False
                risp_testo = ""

                if tipo == 'likert':
                    idx_r = risposte_sez.get(iid)
                    if isinstance(idx_r, int) and 0 <= idx_r < len(valori):
                        # Usa sempre il valore nativo dell'opzione scelta per evitare conflitti tra sottoscale
                        val_num = valori[idx_r]
                        risp_testo = f"{etichette[idx_r]} ({val_num})" if idx_r < len(etichette) else str(val_num)
                        try:
                            t_val = float(target_raw.replace(',', '.'))
                            if op == '≥' and val_num >= t_val: attivato = True
                            elif op == '≤' and val_num <= t_val: attivato = True
                            elif op == '=' and val_num == t_val: attivato = True
                        except ValueError:
                            pass

                elif tipo == 'numerico':
                    val_num = risposte_sez.get(iid)
                    if isinstance(val_num, (int, float)):
                        risp_testo = f"{val_num:g}"
                        try:
                            t_val = float(target_raw.replace(',', '.'))
                            if op == '≥' and val_num >= t_val: attivato = True
                            elif op == '≤' and val_num <= t_val: attivato = True
                            elif op == '=' and val_num == t_val: attivato = True
                        except ValueError:
                            pass

                elif tipo == 'si_no':
                    risp_str = str(risposte_sez.get(iid, '')).strip()
                    risp_testo = risp_str
                    t_low = target_raw.lower()
                    if t_low in ['1', 'sì', 'si', 's', 'y', 'true']:
                        t_norm = 'sì'
                    elif t_low in ['0', 'no', 'n', 'false']:
                        t_norm = 'no'
                    else:
                        t_norm = t_low

                    risp_norm = 'sì' if risp_str.lower() in ['1', 'sì', 'si', 's', 'y', 'true'] else (
                                'no' if risp_str.lower() in ['0', 'no', 'n', 'false'] else risp_str.lower())
                    if risp_norm == t_norm:
                        attivato = True

                elif tipo == 'aperta':
                    risp_str = str(risposte_sez.get(iid, '')).strip()
                    risp_testo = risp_str
                    if risp_str and target_raw.lower() in risp_str.lower():
                        attivato = True

                if attivato:
                    critici_attivati.append({
                        'sezione_id': sez_id,
                        'sezione': sez['titolo'],
                        'id': iid,
                        'testo': item['testo'],
                        'risposta': risp_testo,
                        'condizione': f"{op} {target_raw}",
                        'nota': nota or "Item critico oltre soglia di attenzione"
                    })
        return critici_attivati

    def calcola_punteggi(self, risposte_per_sezione, dati_paziente=None):
        if dati_paziente is None:
            dati_paziente = {}

        self.ultimi_errori = []
        self.ultimi_avvisi = []

        # Costruisce l'ambiente delle variabili anagrafiche normalizzando gli spazi con underscore
        env_anagrafica = {}
        mappa_nomi_spazi = {}
        for k, v in dati_paziente.items():
            clean_k = re.sub(r'\[.*?\]', '', k).strip()
            safe_k = re.sub(r'\s+', '_', clean_k)
            mappa_nomi_spazi[clean_k] = safe_k

            val_str = str(v).strip().replace(',', '.')
            try:
                num_f = float(val_str)
                env_anagrafica[safe_k] = int(num_f) if num_f.is_integer() else num_f
            except ValueError:
                env_anagrafica[safe_k] = str(v).strip()

        PAROLE_RISERVATE = {'and', 'or', 'not', 'in', 'is', 'if', 'else', 'True', 'False', 'None'}
        FUNZIONI_FORMULE = {'abs': abs, 'min': min, 'max': max, 'round': round}

        def _identificatori(expr):
            senza_stringhe = re.sub(r"'[^']*'|\"[^\"]*\"", " ", expr)
            trovati = re.findall(r"(?<![0-9A-Za-zÀ-ÿ_.])[A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ0-9_]*", senza_stringhe)
            return [t for t in trovati if t not in PAROLE_RISERVATE]

        def _errore(msg):
            if msg not in self.ultimi_errori:
                self.ultimi_errori.append(msg)

        def _avviso(msg):
            if msg not in self.ultimi_avvisi:
                self.ultimi_avvisi.append(msg)

        def _valuta_espressione(expr_str, ctx='', silenzioso=False):
            cond = expr_str.strip()
            if not cond:
                return True
            # Sostituisce eventuali nomi con spazi (es. "Anni di studio") con la versione safe ("Anni_di_studio")
            for orig_k in sorted(mappa_nomi_spazi.keys(), key=len, reverse=True):
                if orig_k != mappa_nomi_spazi[orig_k] and orig_k in cond:
                    cond = cond.replace(orig_k, mappa_nomi_spazi[orig_k])
            nomi = _identificatori(cond)
            vuoti = [n for n in nomi if n in env_anagrafica and env_anagrafica[n] == ""]
            mancanti = [n for n in nomi if n not in env_anagrafica]
            if vuoti or mancanti:
                if not silenzioso:
                    if vuoti:
                        _errore(f"«{ctx}»: il campo anagrafico '{vuoti[0]}' è vuoto ma serve per valutare «{expr_str.strip()}»")
                    if mancanti:
                        _errore(f"«{ctx}»: il campo '{mancanti[0]}' usato in «{expr_str.strip()}» non esiste nell'anagrafica del test")
                return False
            try:
                return bool(eval(cond, {"__builtins__": None}, env_anagrafica))
            except Exception as e:
                if not silenzioso:
                    _errore(f"«{ctx}»: impossibile valutare «{expr_str.strip()}» ({e}); "
                            f"controlla che i campi anagrafici siano numerici dove richiesto")
                return False

        def _calcola_correzione(dim_obj):
            """modalita 'prima' (default): vale solo la prima regola valida; 'somma': si sommano tutte le regole valide."""
            modalita = dim_obj.get('correzioni_modalita', 'prima')
            nome = dim_obj.get('nome', dim_obj.get('id', ''))
            applicabili = []
            for regola in dim_obj.get('correzioni', []):
                condizioni = [c.strip() for c in regola.get('condizioni', []) if c.strip()]
                if not condizioni:
                    continue
                # in modalita 'prima', dopo la prima regola valida le altre servono solo a segnalare sovrapposizioni
                quiet = (modalita != 'somma') and len(applicabili) >= 1
                if all(_valuta_espressione(c, nome, quiet) for c in condizioni):
                    try:
                        applicabili.append(float(regola.get('valore', 0.0)))
                    except (ValueError, TypeError):
                        applicabili.append(0.0)
            if not applicabili:
                return 0.0
            if modalita == 'somma':
                return sum(applicabili)
            if len(applicabili) > 1:
                _avviso(f"«{nome}»: {len(applicabili)} regole di correzione sono applicabili, ma in modalità "
                        f"'solo la prima regola valida' si usa solo la prima ({applicabili[0]:+g}). "
                        f"Se le correzioni devono sommarsi (es. età + scolarità) imposta 'Somma tutte le regole valide'.")
            return applicabili[0]

        def _seleziona_cutoff(dim_obj, punteggio):
            nome = dim_obj.get('nome', dim_obj.get('id', ''))
            validi = [co for co in dim_obj.get('cutoffs', []) if _valuta_espressione(co.get('condizione', ''), nome)]
            attivo = None
            for co in validi:
                if co['da'] <= punteggio <= co['a']:
                    attivo = co
                    break
            if attivo is None and validi:
                lo = min(co['da'] for co in validi)
                hi = max(co['a'] for co in validi)
                if lo <= punteggio <= hi:
                    _avviso(f"«{nome}»: il punteggio {punteggio:g} cade in un buco tra due fasce di cut-off: "
                            f"nessuna fascia assegnata (controlla gli estremi degli intervalli).")
            return attivo, validi

        def _pe(dim_obj, esatto):
            """Ritorna (pe, soglie_usate, etichetta_set).
            Un set condizionale (es. eta' x scolarita') ha la precedenza sulle soglie generali;
            vince il primo set le cui condizioni sono tutte vere, altrimenti valgono le soglie generali."""
            nome = dim_obj.get('nome', dim_obj.get('id', ''))
            soglie = dim_obj.get('pe_soglie', [])
            confine = dim_obj.get('pe_confine', 'alto')
            usato = None
            sets = dim_obj.get('pe_set', [])
            if sets:
                trovati = []
                for idx, st in enumerate(sets):
                    conds = [c.strip() for c in st.get('condizioni', []) if c.strip()]
                    quiet = len(trovati) >= 1   # dopo il primo set valido gli altri servono solo a segnalare sovrapposizioni
                    if all(_valuta_espressione(c, nome, quiet) for c in conds):
                        trovati.append((idx, st))
                if trovati:
                    idx, st = trovati[0]
                    soglie = st.get('soglie', [])
                    confine = st.get('confine', confine)
                    usato = st.get('etichetta') or f"set {idx + 1}"
                    if len(trovati) > 1:
                        _avviso(f"«{nome}»: {len(trovati)} set di soglie PE sono applicabili ai dati inseriti; "
                                f"si usa il primo ({usato}). Controlla che le condizioni non si sovrappongano.")
                elif not soglie:
                    _avviso(f"«{nome}»: nessun set di soglie PE si applica ai dati anagrafici inseriti; PE non calcolato.")
                    return None, [], None
            if soglie:
                ok, msg = self.valida_soglie_pe(soglie)
                if not ok:
                    _avviso(f"«{nome}»: soglie PE non valide ({msg}); PE non calcolato.")
                    return None, soglie, usato
            return self._calcola_pe(esatto, soglie, confine), soglie, usato

        risultati = {}

        # FASE 1: Calcolo delle dimensioni standard (somma e media)
        for dim in self.dimensioni:
            if dim.get('tipo_scoring') == 'formula':
                continue
            sezione_id = dim.get('sezione_id')
            item_ids = dim.get('item_ids', [])
            reverse_ids = set(dim.get('item_ids_reverse', []))
            tipo_scoring = dim.get('tipo_scoring', 'somma')
            risposte_sez = risposte_per_sezione.get(sezione_id, {})
            sezione = next((s for s in self.sezioni if s['id'] == sezione_id), None)

            totale = 0.0
            max_possibile = 0.0
            if sezione:
                if sezione['tipo'] == 'likert':
                    valori_scala = sezione.get('opzioni_valori', [])
                    valori_reverse = list(reversed(valori_scala))
                    max_item = max(valori_scala) if valori_scala else 0
                    for iid in item_ids:
                        idx = risposte_sez.get(iid, 0)
                        if not isinstance(idx, int) or not (0 <= idx < len(valori_scala)):
                            idx = 0
                        val = valori_reverse[idx] if iid in reverse_ids else valori_scala[idx]
                        totale += val
                        max_possibile += max_item

                elif sezione['tipo'] == 'numerico':
                    max_item_num = float(sezione.get('max_numerico', 0) or 0)
                    min_item_num = float(sezione.get('min_numerico', 0) or 0)
                    for iid in item_ids:
                        val_raw = risposte_sez.get(iid, 0.0)
                        try:
                            val = float(val_raw)
                        except (ValueError, TypeError):
                            val = 0.0
                        if iid in reverse_ids and max_item_num > min_item_num:
                            val = (max_item_num + min_item_num) - val
                        totale += val
                        if max_item_num > 0:
                            max_possibile += max_item_num

                elif sezione['tipo'] == 'si_no':
                    for iid in item_ids:
                        risp_str = str(risposte_sez.get(iid, '')).strip().lower()
                        val = 1 if risp_str in ['sì', 'si', '1', 's', 'y', 'true'] else 0
                        if iid in reverse_ids:
                            val = 1 - val
                        totale += val
                        max_possibile += 1

            if tipo_scoring == 'media' and len(item_ids) > 0:
                grezzo_esatto = totale / len(item_ids)
                max_esatto = (max_possibile / len(item_ids)) if max_possibile > 0 else 0.0
            else:
                grezzo_esatto = totale
                max_esatto = max_possibile

            correzione_applicata = _calcola_correzione(dim)
            finale_esatto = grezzo_esatto + correzione_applicata

            punteggio_grezzo = self._format_num(grezzo_esatto)
            punteggio_finale = self._format_num(finale_esatto)
            max_finale = self._format_num(max_esatto)

            cutoff_attivo, cutoffs_validi = _seleziona_cutoff(dim, punteggio_finale)

            pe_val, pe_soglie, pe_set_usato = _pe(dim, finale_esatto)

            risultati[dim['id']] = {
                'nome': dim['nome'],
                'punteggio_grezzo': punteggio_grezzo,
                'punteggio_grezzo_esatto': grezzo_esatto,
                'correzione': correzione_applicata,
                'punteggio': punteggio_finale,
                'punteggio_esatto': finale_esatto,
                'pe': pe_val,
                'pe_soglie': pe_soglie,
                'pe_set': pe_set_usato,
                'max': max_finale,
                'cutoff': cutoff_attivo,
                'tutti_cutoffs': cutoffs_validi,
                'tipo_scoring': tipo_scoring,
                'n_items': len(item_ids),
                'reverse_ids': list(reverse_ids),
                'norma': dim.get('norma', {}),
                'tipo_grafico': dim.get('tipo_grafico', 'barre'),
                'mostra_cutoff': dim.get('mostra_cutoff', True),
            }

        # FASE 2: Calcolo delle dimensioni composite basate su Formule
        pendenti = [d for d in self.dimensioni if d.get('tipo_scoring') == 'formula']
        ids_pendenti = {d['id'] for d in pendenti}

        def _registra_formula(dim, grezzo_esatto):
            correzione_applicata = _calcola_correzione(dim)
            finale_esatto = grezzo_esatto + correzione_applicata

            punteggio_composto_grezzo = self._format_num(grezzo_esatto)
            punteggio_composto_finale = self._format_num(finale_esatto)

            cutoff_attivo, cutoffs_validi = _seleziona_cutoff(dim, punteggio_composto_finale)

            pe_val, pe_soglie, pe_set_usato = _pe(dim, finale_esatto)

            risultati[dim['id']] = {
                'nome': dim['nome'],
                'punteggio_grezzo': punteggio_composto_grezzo,
                'punteggio_grezzo_esatto': grezzo_esatto,
                'correzione': correzione_applicata,
                'punteggio': punteggio_composto_finale,
                'punteggio_esatto': finale_esatto,
                'pe': pe_val,
                'pe_soglie': pe_soglie,
                'pe_set': pe_set_usato,
                'max': 0,
                'cutoff': cutoff_attivo,
                'tutti_cutoffs': cutoffs_validi,
                'tipo_scoring': 'formula',
                'n_items': 0,
                'reverse_ids': [],
                'norma': dim.get('norma', {}),
                'tipo_grafico': dim.get('tipo_grafico', 'barre'),
                'mostra_cutoff': dim.get('mostra_cutoff', True),
            }

        # Le formule possono richiamare altre formule: si risolve per passate successive
        while pendenti:
            rimaste = []
            for dim in pendenti:
                nome = dim.get('nome', dim['id'])
                formula = dim.get('formula', '0')
                if not re.search(r'[A-Za-z_]\s*\(', formula):
                    # nessuna chiamata di funzione: la virgola tra cifre e' un separatore decimale
                    formula = re.sub(r'(?<=\d),(?=\d)', '.', formula)

                env_formule = {k: v['punteggio_esatto'] for k, v in risultati.items()}
                env_formule.update(env_anagrafica)
                nomi = [n for n in _identificatori(formula) if n not in FUNZIONI_FORMULE]

                if [n for n in nomi if n in ids_pendenti and n != dim['id'] and n not in risultati]:
                    rimaste.append(dim)
                    continue

                mancanti = [n for n in nomi if n not in env_formule]
                vuoti = [n for n in nomi if n in env_anagrafica and env_anagrafica[n] == ""]
                if mancanti or vuoti:
                    if vuoti:
                        _errore(f"«{nome}» (formula): il campo anagrafico '{vuoti[0]}' è vuoto")
                    if mancanti:
                        _errore(f"«{nome}» (formula): la variabile '{mancanti[0]}' non esiste")
                    _registra_formula(dim, 0.0)
                    continue

                try:
                    valore = float(eval(formula, {"__builtins__": None, **FUNZIONI_FORMULE}, env_formule))
                except Exception as e:
                    _errore(f"«{nome}» (formula '{formula}'): {e}")
                    valore = 0.0
                _registra_formula(dim, valore)

            if len(rimaste) == len(pendenti):
                for dim in rimaste:
                    _errore(f"«{dim.get('nome', dim['id'])}» (formula): dipendenza circolare o dimensione richiamata non calcolabile")
                    _registra_formula(dim, 0.0)
                break
            pendenti = rimaste
        return risultati


# ─────────────────────────────────────────────
#  MOTORE GRAFICO AVANZATO E IMPAGINAZIONE PDF
# ─────────────────────────────────────────────

def _esc(testo):
    """Esegue l'escape dei caratteri speciali XML (<, >, &) per evitare crash in ReportLab Paragraph."""
    if testo is None:
        return ""
    return xml_escape(str(testo))

MPL_COLOR_MAP = {
    'green': '#2ECC71', 'yellow': '#F1C40F',
    'orange': '#E67E22', 'red': '#E74C3C', 'gray': '#95A5A6',
}
# Colori più scuri/saturi per le linee di cut-off così da staccare rispetto al riempimento della barra
MPL_CUTOFF_LINE_MAP = {
    'green': '#117A65', 'yellow': '#B7950B',
    'orange': '#A04000', 'red': '#922B21', 'gray': '#566573',
}
COLOR_MAP = {
    'green':  colors.HexColor('#2ECC71'),
    'yellow': colors.HexColor('#F1C40F'),
    'orange': colors.HexColor('#E67E22'),
    'red':    colors.HexColor('#E74C3C'),
    'gray':   colors.HexColor('#95A5A6'),
}

def _bar_colors(risultati_dim):
    return [MPL_COLOR_MAP.get(r['cutoff']['colore'], '#3498DB') if r['cutoff'] else '#3498DB'
            for r in risultati_dim.values()]

def _img_proporzionale(img_path, max_w_cm=17.0, max_h_cm=21.0):
    """Crea un RLImage mantenendo il rapporto d'aspetto nativo del PNG senza mai schiacciarlo."""
    ir = ImageReader(img_path)
    iw, ih = ir.getSize()
    ratio = ih / float(iw)
    w = max_w_cm * cm
    h = w * ratio
    if h > max_h_cm * cm:
        h = max_h_cm * cm
        w = h / ratio
    return RLImage(img_path, width=w, height=h)

def genera_grafico_barre(risultati_dim, output_path, mostra_cutoff_linee=True):
    nomi_raw = [r['nome'] for r in risultati_dim.values()]
    punteggi = [r['punteggio'] for r in risultati_dim.values()]
    massimi  = [r['max'] if r['max'] > 0 else (max(punteggi) * 1.15 if punteggi and max(punteggi) > 0 else 10)
                for r in risultati_dim.values()]
    bcolors  = _bar_colors(risultati_dim)
    n_dim    = len(nomi_raw)
    max_ref  = max(max(massimi), max(punteggi)) if punteggi else 10
    if max_ref <= 0:
        max_ref = 10
    min_val  = min(punteggi) if punteggi else 0
    min_ref  = min(0, min_val * 1.15)

    # Usa il layout orizzontale se c'è 1 sola dimensione o più di 5 dimensioni
    if n_dim == 1 or n_dim > 5:
        nomi = [textwrap.fill(n, 26) for n in nomi_raw]
        altezza_dinamica = 1.45 if n_dim == 1 else max(3.2, n_dim * 0.62)
        fig, ax = plt.subplots(figsize=(8.5, altezza_dinamica))
        y_pos = np.arange(n_dim)
        bar_h = 0.42 if n_dim == 1 else 0.52

        bars = ax.barh(y_pos, punteggi, height=bar_h, color=bcolors, alpha=0.78,
                       edgecolor='#2C3E50', linewidth=0.7, zorder=3)
        if n_dim == 1:
            ax.set_ylim(-0.55, 0.55)

        legenda_elementi = {}
        if mostra_cutoff_linee:
            for i, r in enumerate(risultati_dim.values()):
                if r.get('mostra_cutoff', True):
                    for co in r.get('tutti_cutoffs', []):
                        soglia = co['da']
                        colore_fill = MPL_COLOR_MAP.get(co['colore'], 'gray')
                        colore_line = MPL_CUTOFF_LINE_MAP.get(co['colore'], '#2C3E50')
                        if co['etichetta'] and co['etichetta'] not in legenda_elementi:
                            legenda_elementi[co['etichetta']] = colore_fill
                        if soglia > 0:
                            y_low, y_high = i - bar_h * 0.65, i + bar_h * 0.65
                            ax.plot([soglia, soglia], [y_low, y_high],
                                    color=colore_line, linewidth=1.9, linestyle='--', zorder=5)

        for bar, val in zip(bars, punteggi):
            offset = (max_ref * 0.018) if val >= 0 else -(max_ref * 0.018)
            ha_pos = 'left' if val >= 0 else 'right'
            ax.text(val + offset, bar.get_y() + bar.get_height()/2,
                    f"{val:g}", ha=ha_pos, va='center', fontsize=9.5, fontweight='bold', color='#2C3E50')

        max_label_aggiunto = False
        for i, mx in enumerate(massimi):
            if list(risultati_dim.values())[i]['max'] > 0:
                lbl = f'Massimo ({mx:g})' if (n_dim == 1 and not max_label_aggiunto) else ('Massimo Teorico' if not max_label_aggiunto else '_nolegend_')
                ax.plot([mx, mx], [i - bar_h * 0.65, i + bar_h * 0.65], color='#2C3E50',
                        linewidth=1.4, linestyle=':', alpha=0.65, zorder=4, label=lbl)
                max_label_aggiunto = True

        handles_auto, _ = ax.get_legend_handles_labels()
        handles_patch = [mpatches.Patch(facecolor=c, alpha=0.78, edgecolor='#2C3E50', linewidth=0.5, label=l)
                         for l, c in legenda_elementi.items()]
        all_handles = handles_auto + handles_patch
        if all_handles:
            ax.legend(handles=all_handles, fontsize=8.5, ncol=min(4, len(all_handles)),
                      loc='lower center', bbox_to_anchor=(0.5, 1.02), frameon=False)

        ax.set_yticks(y_pos)
        ax.set_yticklabels(nomi, fontsize=9.5, fontweight='bold' if n_dim == 1 else 'normal')
        ax.set_xlabel('Punteggio', fontsize=9)
        ax.set_xlim(min_ref, max_ref * 1.16)
        ax.invert_yaxis()
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='x', linestyle='--', alpha=0.35, zorder=0)
    else:
        # Layout verticale per gruppi omogenei da 2 a 5 dimensioni
        wrap_chars = 14 if n_dim >= 4 else 20
        nomi = [textwrap.fill(n, wrap_chars) for n in nomi_raw]
        fig, ax = plt.subplots(figsize=(8.5, 3.4))
        x = np.arange(n_dim)
        bar_w = 0.38 if n_dim == 2 else (0.48 if n_dim <= 4 else 0.55)
        bars = ax.bar(x, punteggi, width=bar_w, color=bcolors, alpha=0.78,
                      edgecolor='#2C3E50', linewidth=0.7, zorder=3)

        if n_dim == 2:
            ax.set_xlim(-0.6, 1.6)

        max_label_aggiunto = False
        for i, mx in enumerate(massimi):
            if list(risultati_dim.values())[i]['max'] > 0:
                lbl = 'Massimo Teorico' if not max_label_aggiunto else '_nolegend_'
                ax.plot([i - bar_w * 0.62, i + bar_w * 0.62], [mx, mx], color='#2C3E50',
                        linewidth=1.4, linestyle=':', alpha=0.65, zorder=4, label=lbl)
                max_label_aggiunto = True

        legenda_elementi = {}
        if mostra_cutoff_linee:
            for i, r in enumerate(risultati_dim.values()):
                if r.get('mostra_cutoff', True):
                    for co in r.get('tutti_cutoffs', []):
                        soglia = co['da']
                        colore_fill = MPL_COLOR_MAP.get(co['colore'], 'gray')
                        colore_line = MPL_CUTOFF_LINE_MAP.get(co['colore'], '#2C3E50')
                        if co['etichetta'] and co['etichetta'] not in legenda_elementi:
                            legenda_elementi[co['etichetta']] = colore_fill
                        if soglia > 0:
                            x_low, x_high = i - bar_w * 0.62, i + bar_w * 0.62
                            ax.plot([x_low, x_high], [soglia, soglia],
                                    color=colore_line, linewidth=1.9, linestyle='--', zorder=5)

        for bar, val in zip(bars, punteggi):
            offset_y = (max_ref * 0.025) if val >= 0 else -(max_ref * 0.06)
            ax.text(bar.get_x() + bar.get_width() / 2, val + offset_y,
                    f"{val:g}", ha='center', va='bottom', fontsize=10, fontweight='bold', color='#2C3E50')

        handles_auto, _ = ax.get_legend_handles_labels()
        handles_patch = [mpatches.Patch(facecolor=c, alpha=0.78, edgecolor='#2C3E50', linewidth=0.5, label=l)
                         for l, c in legenda_elementi.items()]
        all_handles = handles_auto + handles_patch
        if all_handles:
            ax.legend(handles=all_handles, fontsize=8.5, ncol=min(4, len(all_handles)),
                      loc='lower center', bbox_to_anchor=(0.5, 1.02), frameon=False)

        ax.set_xticks(x)
        ax.set_xticklabels(nomi, fontsize=9.5)
        ax.set_ylabel('Punteggio', fontsize=9.5)
        ax.set_ylim(min_ref, max_ref * 1.18)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.grid(axis='y', linestyle='--', alpha=0.35, zorder=0)

    plt.tight_layout()
    plt.savefig(output_path, dpi=160, bbox_inches='tight', pad_inches=0.12)
    plt.close()

def genera_grafico_linea(risultati_dim, output_path, mostra_cutoff_linee=True):
    nomi_raw = [r['nome'] for r in risultati_dim.values()]
    nomi     = [textwrap.fill(n, 15) for n in nomi_raw]
    punteggi = [r['punteggio'] for r in risultati_dim.values()]
    massimi  = [r['max'] if r['max'] > 0 else (max(punteggi) * 1.15 if punteggi and max(punteggi) > 0 else 10)
                for r in risultati_dim.values()]
    max_ref  = max(max(massimi), max(punteggi)) if punteggi else 10
    if max_ref <= 0:
        max_ref = 10
    min_val  = min(punteggi) if punteggi else 0
    min_ref  = min(0, min_val * 1.15)

    fig, ax = plt.subplots(figsize=(8.5, 3.6))
    x = list(range(len(nomi)))

    ax.plot(x, punteggi, marker='o', color='#2980B9', linewidth=2.2,
            markersize=8, zorder=4, label='Punteggio Paziente')
    if any(r['max'] > 0 for r in risultati_dim.values()):
        ax.plot(x, massimi, marker='s', color='#2C3E50', linewidth=1.4,
                linestyle='--', markersize=5, alpha=0.5, zorder=3, label='Massimo Teorico')

    legenda_elementi = {}
    if mostra_cutoff_linee:
        for i, r in enumerate(risultati_dim.values()):
            if r.get('mostra_cutoff', True):
                for co in r.get('tutti_cutoffs', []):
                    soglia = co['da']
                    colore_hex = MPL_COLOR_MAP.get(co['colore'], 'gray')
                    if co['etichetta'] and co['etichetta'] not in legenda_elementi:
                        legenda_elementi[co['etichetta']] = colore_hex
                    if soglia > 0:
                        ax.plot([i - 0.35, i + 0.35], [soglia, soglia],
                                color=colore_hex, linewidth=2.2, linestyle=':', alpha=0.9, zorder=2)

    for xi, val in zip(x, punteggi):
        ax.text(xi, val + (max_ref * 0.03), f"{val:g}",
                ha='center', va='bottom', fontsize=10, fontweight='bold', color='#2C3E50')

    handles, _ = ax.get_legend_handles_labels()
    for l, c in legenda_elementi.items():
        handles.append(mpatches.Patch(color=c, label=l))

    if handles:
        ax.legend(handles=handles, fontsize=8.5, ncol=min(4, len(handles)),
                  loc='lower center', bbox_to_anchor=(0.5, 1.02), frameon=False)

    ax.set_xticks(x)
    ax.set_xticklabels(nomi, fontsize=9.5)
    ax.set_ylabel('Punteggio', fontsize=9.5)
    ax.set_ylim(min_ref, max_ref * 1.2)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='both', linestyle='--', alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=160, bbox_inches='tight', pad_inches=0.12)
    plt.close()

def genera_grafico_gaussiana(nome_dim, punteggio, media, ds, output_path, cutoffs=None):
    fig, ax = plt.subplots(figsize=(8.5, 3.3))

    x_min = min(media - 3.8 * ds, punteggio - 0.5 * ds)
    x_max = max(media + 3.8 * ds, punteggio + 0.5 * ds)
    xs    = np.linspace(x_min, x_max, 400)
    ys    = scipy_stats.norm.pdf(xs, media, ds)

    hatch_patterns = ['/', '\\', 'x', '-', '|', '+']

    if cutoffs:
        for i, co in enumerate(cutoffs):
            c_da = max(co['da'], x_min)
            c_a  = min(co['a'], x_max)
            if c_a > c_da:
                colore = MPL_COLOR_MAP.get(co['colore'], '#CCCCCC')
                hatch = hatch_patterns[i % len(hatch_patterns)]
                ax.axvspan(c_da, c_a, alpha=0.14, facecolor=colore, hatch=hatch,
                           edgecolor=colore, zorder=0, label=co['etichetta'])

    ax.plot(xs, ys, color='#2C3E50', linewidth=2.2, zorder=3)
    ax.fill_between(xs, ys, alpha=0.08, color='#2980B9', zorder=2)

    perc_colors = {'75°': '#27AE60', '90°': '#E67E22', '95°': '#E74C3C'}
    for pct, col in perc_colors.items():
        val = scipy_stats.norm.ppf(int(pct[:-1]) / 100, media, ds)
        ax.axvline(val, color=col, linestyle='--', linewidth=1.3, alpha=0.85, zorder=4)
        ax.text(val, max(ys) * 0.94, f' {pct}', color=col, fontsize=8,
                va='top', ha='left', fontweight='bold')

    y_sogg = scipy_stats.norm.pdf(punteggio, media, ds)
    ax.scatter([punteggio], [y_sogg], color='#C0392B', s=90, zorder=6)
    ax.axvline(punteggio, color='#C0392B', linewidth=2, alpha=0.8, zorder=5)
    perc_sogg = scipy_stats.norm.cdf(punteggio, media, ds) * 100
    ha_align = 'right' if punteggio > media + 1.5 * ds else 'left'
    offset_x = -0.08 * ds if ha_align == 'right' else 0.08 * ds
    ax.text(punteggio + offset_x, max(ys) * 0.58,
            f'Pz: {punteggio:g} ({perc_sogg:.1f}°pct)',
            color='#C0392B', fontsize=8.5, fontweight='bold', va='center', ha=ha_align,
            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', edgecolor='#C0392B', alpha=0.85))

    ax.axvline(media, color='#2980B9', linewidth=1.3, linestyle='-', alpha=0.5, zorder=4)
    ax.set_xlabel('Punteggio', fontsize=9.5)
    ax.set_ylabel('Densità', fontsize=9.5)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(0, max(ys) * 1.15)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(axis='x', linestyle='--', alpha=0.3)

    handles, labels = ax.get_legend_handles_labels()
    seen = set()
    unique_handles = []
    for h, l in zip(handles, labels):
        if l and l not in seen:
            seen.add(l)
            unique_handles.append(h)
    unique_handles.append(mpatches.Patch(color='#C0392B', label='Paziente'))

    ax.legend(handles=unique_handles, fontsize=8, ncol=min(5, len(unique_handles)),
              loc='lower center', bbox_to_anchor=(0.5, 1.02), frameon=False)

    plt.tight_layout()
    plt.savefig(output_path, dpi=160, bbox_inches='tight', pad_inches=0.1)
    plt.close()


# ─────────────────────────────────────────────
#  GENERAZIONE PDF E REPORTISTICA
# ─────────────────────────────────────────────

def draw_header_footer(canvas, doc, config):
    canvas.saveState()

    LOGO_W   = 4 * cm
    LOGO_H   = 1.4 * cm
    MARGIN_X = 2.0 * cm
    LOGO_Y   = A4[1] - LOGO_H - 0.5 * cm

    logo_path = config.get("logo_path", "")
    if logo_path and os.path.exists(logo_path):
        try:
            posizione = config.get("logo_position", "destra").lower()
            if posizione == "sinistra":
                logo_x = MARGIN_X
            elif posizione == "centro":
                logo_x = (A4[0] - LOGO_W) / 2
            else:
                logo_x = A4[0] - MARGIN_X - LOGO_W

            canvas.drawImage(logo_path, logo_x, LOGO_Y,
                             width=LOGO_W, height=LOGO_H,
                             preserveAspectRatio=True, mask='auto')
        except Exception as e:
            print(f"Errore rendering logo: {e}")

    footer_text = config.get("footer_text", "").strip()
    if not footer_text:
        footer_text = "Report generato automaticamente da PsychoScorer"

    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#7F8C8D'))

    # Limita a max 3 righe il footer per non invadere l'area del testo
    lines = [l.strip() for l in footer_text.split('\n') if l.strip()][:3]
    y_pos = 1.15 * cm + (len(lines) - 1) * 0.32 * cm
    for line in lines:
        canvas.drawCentredString(A4[0] / 2.0, y_pos, line)
        y_pos -= 0.32 * cm

    canvas.setFont('Helvetica', 8.5)
    canvas.drawRightString(A4[0] - MARGIN_X, 1.15 * cm, f"Pagina {doc.page}")
    canvas.restoreState()


PE_COLOR_MAP_PDF = {
    0: colors.HexColor('#E74C3C'),
    1: colors.HexColor('#E67E22'),
    2: colors.HexColor('#27AE60'),
    3: colors.HexColor('#2ECC71'),
    4: colors.HexColor('#16A085'),
}

def _build_pdf_story(engine, dati_paziente, risposte_per_sezione,
                     risultati_dim, tmp_dir, opzioni_grafico, osservazioni_cliniche=""):
    styles = getSampleStyleSheet()
    PAGE_W = 17.0 * cm

    TITLE_S = ParagraphStyle('T2', parent=styles['Title'], fontSize=18, leading=22,
                             spaceAfter=2, textColor=colors.HexColor('#2C3E50'), alignment=0)
    H1 = ParagraphStyle('H1', parent=styles['Heading1'], fontSize=12.5, leading=16,
                        textColor=colors.HexColor('#2980B9'), spaceBefore=12, spaceAfter=6,
                        keepWithNext=True)
    H1_ALERT = ParagraphStyle('H1Alert', parent=H1, textColor=colors.HexColor('#C0392B'))
    H2 = ParagraphStyle('H2', parent=styles['Heading2'], fontSize=10.5, leading=14,
                        textColor=colors.HexColor('#34495E'), spaceBefore=8, spaceAfter=4,
                        keepWithNext=True)
    BODY  = ParagraphStyle('BodyCompact', parent=styles['Normal'], fontSize=9.5, leading=12.5)
    SMALL = ParagraphStyle('Sm', parent=BODY, fontSize=8, leading=10,
                           textColor=colors.HexColor('#7F8C8D'))
    TH_STYLE = ParagraphStyle('TH', parent=BODY, fontName='Helvetica-Bold', textColor=colors.HexColor('#2C3E50'))

    story = []

    # Intestazione Test compatta
    story.append(Paragraph(_esc(engine.nome), TITLE_S))
    meta_info = f"Data stampa: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}"
    if engine.autore:
        meta_info = f"Riferimento: {_esc(engine.autore)}  |  {meta_info}"
    story.append(Paragraph(meta_info, SMALL))
    story.append(Spacer(1, 0.25 * cm))

    # --- DATI PAZIENTE (17.0 cm) ---
    if dati_paziente:
        story.append(Paragraph("Dati Identificativi", H1))
        items_anagrafica = list(dati_paziente.items())
        griglia_anagrafica = []

        for idx in range(0, len(items_anagrafica), 2):
            k1, v1 = _esc(items_anagrafica[idx][0]), _esc(items_anagrafica[idx][1]) or "—"
            riga = [Paragraph(f"<b>{k1}:</b>", BODY), Paragraph(v1, BODY)]
            if idx + 1 < len(items_anagrafica):
                k2, v2 = _esc(items_anagrafica[idx+1][0]), _esc(items_anagrafica[idx+1][1]) or "—"
                riga.append(Paragraph(f"<b>{k2}:</b>", BODY))
                riga.append(Paragraph(v2, BODY))
            else:
                riga.extend([Paragraph("", BODY), Paragraph("", BODY)])
            griglia_anagrafica.append(riga)

        t = Table(griglia_anagrafica, colWidths=[3.5*cm, 5.0*cm, 3.5*cm, 5.0*cm])
        t.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, colors.HexColor('#F8F9FA')]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#DEE2E6')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(t)

    # --- RIEPILOGO SCORING E GRAFICI ---
    if risultati_dim:
        story.append(Paragraph("Riepilogo Punteggi e Profilo Grafico", H1))

        has_corr = any(r.get('correzione', 0.0) != 0.0 for r in risultati_dim.values())
        has_pe   = any(r.get('pe') is not None for r in risultati_dim.values())

        if has_corr and has_pe:
            hdr_titles = ["Dimensione", "Metodo", "Grezzo", "Corr.", "Finale", "PE", "Max", "Fascia Clinica"]
            col_w = [4.4*cm, 1.8*cm, 1.4*cm, 1.3*cm, 1.5*cm, 1.4*cm, 1.4*cm, 3.8*cm]
            pe_col_idx, interp_col_idx = 5, 7
        elif has_corr:
            hdr_titles = ["Dimensione", "Metodo", "Grezzo", "Corr.", "Finale", "Max", "Fascia Clinica"]
            col_w = [5.0*cm, 2.0*cm, 1.6*cm, 1.5*cm, 1.7*cm, 1.4*cm, 3.8*cm]
            pe_col_idx, interp_col_idx = None, 6
        elif has_pe:
            hdr_titles = ["Dimensione", "Metodo", "Punteggio", "PE", "Max", "Fascia Clinica"]
            col_w = [5.4*cm, 2.1*cm, 2.1*cm, 1.6*cm, 1.6*cm, 4.2*cm]
            pe_col_idx, interp_col_idx = 3, 5
        else:
            hdr_titles = ["Dimensione", "Metodo", "Punteggio", "Max", "Fascia Clinica"]
            col_w = [6.2*cm, 2.3*cm, 2.3*cm, 1.8*cm, 4.4*cm]
            pe_col_idx, interp_col_idx = None, 4

        rows = [[Paragraph(h, TH_STYLE) for h in hdr_titles]]
        ts = [
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#EAEDED')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#DEE2E6')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F8F9FA')]),
        ]

        for i, r in enumerate(risultati_dim.values(), start=1):
            co = r['cutoff']
            pe_val = r.get('pe')
            pe_str = f"<b>PE {pe_val}</b>" if pe_val is not None else "—"
            label_sc = "Somma"
            if r['tipo_scoring'] == 'media': label_sc = "Media"
            elif r['tipo_scoring'] == 'formula': label_sc = "Formula"

            corr_val = r.get('correzione', 0.0)
            corr_str = f"{corr_val:+g}" if corr_val != 0 else "—"
            nome_esc = _esc(r['nome'])
            co_etich = _esc(co['etichetta']) if co else "—"

            if has_corr and has_pe:
                rows.append([
                    Paragraph(nome_esc, BODY), Paragraph(label_sc, BODY),
                    Paragraph(f"{r['punteggio_grezzo']:g}", BODY), Paragraph(corr_str, BODY),
                    Paragraph(f"<b>{r['punteggio']:g}</b>", BODY), Paragraph(pe_str, BODY),
                    Paragraph(f"{r['max']:g}" if r['max'] > 0 else "—", BODY),
                    Paragraph(co_etich, BODY),
                ])
            elif has_corr:
                rows.append([
                    Paragraph(nome_esc, BODY), Paragraph(label_sc, BODY),
                    Paragraph(f"{r['punteggio_grezzo']:g}", BODY), Paragraph(corr_str, BODY),
                    Paragraph(f"<b>{r['punteggio']:g}</b>", BODY),
                    Paragraph(f"{r['max']:g}" if r['max'] > 0 else "—", BODY),
                    Paragraph(co_etich, BODY),
                ])
            elif has_pe:
                rows.append([
                    Paragraph(nome_esc, BODY), Paragraph(label_sc, BODY),
                    Paragraph(f"<b>{r['punteggio']:g}</b>", BODY), Paragraph(pe_str, BODY),
                    Paragraph(f"{r['max']:g}" if r['max'] > 0 else "—", BODY),
                    Paragraph(co_etich, BODY),
                ])
            else:
                rows.append([
                    Paragraph(nome_esc, BODY), Paragraph(label_sc, BODY),
                    Paragraph(f"<b>{r['punteggio']:g}</b>", BODY),
                    Paragraph(f"{r['max']:g}" if r['max'] > 0 else "—", BODY),
                    Paragraph(co_etich, BODY),
                ])

            if pe_col_idx is not None and pe_val is not None:
                pe_bg = PE_COLOR_MAP_PDF.get(pe_val, colors.white)
                ts += [
                    ('BACKGROUND', (pe_col_idx, i), (pe_col_idx, i), pe_bg),
                    ('TEXTCOLOR', (pe_col_idx, i), (pe_col_idx, i), colors.white),
                ]

            if co:
                bg = COLOR_MAP.get(co['colore'], colors.white)
                ts += [
                    ('BACKGROUND', (interp_col_idx, i), (interp_col_idx, i), bg),
                    ('TEXTCOLOR', (interp_col_idx, i), (interp_col_idx, i), colors.white),
                ]

        t_sum = Table(rows, colWidths=col_w, repeatRows=1)
        t_sum.setStyle(TableStyle(ts))
        story.append(t_sum)
        story.append(Spacer(1, 0.3 * cm))

    # --- SEGNALAZIONE ITEM CRITICI (RED FLAGS) ---
    item_critici = engine.rileva_item_critici(risposte_per_sezione)
    if item_critici:
        TH_CRIT = ParagraphStyle('THCrit', parent=TH_STYLE, textColor=colors.HexColor('#7B241C'))
        rows_crit = [[
            Paragraph("#", TH_CRIT),
            Paragraph("Item Critico Rilevato", TH_CRIT),
            Paragraph("Risposta", TH_CRIT),
            Paragraph("Nota / Allerta Clinica", TH_CRIT)
        ]]
        for ic in item_critici:
            rows_crit.append([
                Paragraph(f"<b>{_esc(ic['id'])}</b>", BODY),
                Paragraph(_esc(ic['testo']), BODY),
                Paragraph(f"<b>{_esc(ic['risposta'])}</b>", BODY),
                Paragraph(_esc(ic['nota']), BODY)
            ])
        t_crit = Table(rows_crit, colWidths=[1.2*cm, 7.8*cm, 3.2*cm, 4.8*cm], repeatRows=1)
        t_crit.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#FADBD8')),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#FDEDEC'), colors.white]),
            ('GRID', (0,0), (-1,-1), 0.6, colors.HexColor('#E74C3C')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        story.append(Paragraph("Segnalazione Item Critici (Red Flags)", H1_ALERT))
        story.append(t_crit)
        story.append(Spacer(1, 0.25 * cm))

    if risultati_dim:
        # 2. Grafici con proporzioni native garantite
        dim_barre = {k: v for k, v in risultati_dim.items()
                     if opzioni_grafico.get(k, {}).get('tipo', 'barre') == 'barre'}
        dim_linea = {k: v for k, v in risultati_dim.items()
                     if opzioni_grafico.get(k, {}).get('tipo') == 'linea'}
        dim_gauss = {k: v for k, v in risultati_dim.items()
                     if opzioni_grafico.get(k, {}).get('tipo') == 'gaussiana'}

        if dim_barre:
            CHUNK_SIZE = 10
            gruppi_barre = {}
            for k, v in dim_barre.items():
                gruppi_barre.setdefault(v.get('max', 0), []).append((k, v))

            chart_idx = 0
            for max_val, items_gruppo in gruppi_barre.items():
                chunks = [items_gruppo[i:i + CHUNK_SIZE] for i in range(0, len(items_gruppo), CHUNK_SIZE)]
                for chunk in chunks:
                    chunk_dict = dict(chunk)
                    mostra_co = any(opzioni_grafico.get(k, {}).get('cutoff', True) for k in chunk_dict)
                    gp = os.path.join(tmp_dir, f'chart_barre_{chart_idx}.png')
                    chart_idx += 1
                    genera_grafico_barre(chunk_dict, gp, mostra_cutoff_linee=mostra_co)
                    story.append(KeepTogether([
                        _img_proporzionale(gp, max_w_cm=17.0, max_h_cm=11.5),
                        Spacer(1, 0.2 * cm)
                    ]))

        if dim_linea:
            CHUNK_SIZE_LINE = 10
            gruppi_linea = {}
            for k, v in dim_linea.items():
                gruppi_linea.setdefault(v.get('max', 0), []).append((k, v))

            chart_idx = 0
            for max_val, items_gruppo in gruppi_linea.items():
                chunks = [items_gruppo[i:i + CHUNK_SIZE_LINE] for i in range(0, len(items_gruppo), CHUNK_SIZE_LINE)]
                for chunk in chunks:
                    chunk_dict = dict(chunk)
                    mostra_co = any(opzioni_grafico.get(k, {}).get('cutoff', True) for k in chunk_dict)
                    gp = os.path.join(tmp_dir, f'chart_linea_{chart_idx}.png')
                    chart_idx += 1
                    genera_grafico_linea(chunk_dict, gp, mostra_cutoff_linee=mostra_co)
                    story.append(KeepTogether([
                        _img_proporzionale(gp, max_w_cm=17.0, max_h_cm=9.5),
                        Spacer(1, 0.2 * cm)
                    ]))

        for dim_id, r in dim_gauss.items():
            norma = r.get('norma', {})
            media_n = norma.get('media')
            ds_n    = norma.get('ds')
            if media_n is not None and ds_n and ds_n > 0:
                gp = os.path.join(tmp_dir, f'gauss_{dim_id}.png')
                # Usa tutti_cutoffs già filtrati per l'anagrafica del paziente
                cutoffs = r.get('tutti_cutoffs', []) if opzioni_grafico.get(dim_id, {}).get('cutoff', True) else []
                genera_grafico_gaussiana(r['nome'], r['punteggio'], media_n, ds_n, gp, cutoffs=cutoffs)
                story.append(KeepTogether([
                    Paragraph(f"Distribuzione Normativa — {_esc(r['nome'])}", H2),
                    _img_proporzionale(gp, max_w_cm=16.5, max_h_cm=7.5),
                    Spacer(1, 0.2 * cm)
                ]))
            else:
                story.append(Paragraph(
                    f"[Gaussiana non disponibile per '{_esc(r['nome'])}': media/DS non configurate]", SMALL))

        # 3. Tabella Dettaglio Valori Normativi, PE e Cut-off
        has_cutoffs = any(r.get('cutoff') for r in risultati_dim.values())
        has_norms   = any(r.get('norma', {}).get('media') is not None and r.get('norma', {}).get('ds', 0) > 0
                          for r in risultati_dim.values())

        if has_cutoffs or has_norms or has_pe:
            hdr_dettaglio = ["Dimensione", "Punteggio"]
            if has_pe: hdr_dettaglio.append("Punteggio Equiv.")
            if has_norms: hdr_dettaglio.append("Percentile")
            if has_cutoffs:
                hdr_dettaglio.extend(["Fascia Clinica", "Range Cut-off"])

            rows_dettaglio = [[Paragraph(h, TH_STYLE) for h in hdr_dettaglio]]
            pe_labels_desc = {0: "PE 0 (Deficitario)", 1: "PE 1 (Borderline)", 2: "PE 2 (Norma)", 3: "PE 3 (Norma)", 4: "PE 4 (Superiore)"}

            for dim_id, r in risultati_dim.items():
                norma = r.get('norma', {})
                media_n, ds_n = norma.get('media'), norma.get('ds')
                ha_norma_valida = (media_n is not None and ds_n and ds_n > 0)
                ha_cutoff = bool(r.get('cutoff'))
                ha_pe_dim = (r.get('pe') is not None)

                if not ha_norma_valida and not ha_cutoff and not ha_pe_dim:
                    continue

                row_data = [Paragraph(_esc(r['nome']), BODY), Paragraph(f"{r['punteggio']:g}", BODY)]
                if has_pe:
                    row_data.append(Paragraph(pe_labels_desc.get(r['pe'], "—") if ha_pe_dim else "—", BODY))
                if has_norms:
                    if ha_norma_valida:
                        perc = scipy_stats.norm.cdf(r['punteggio'], media_n, ds_n) * 100
                        row_data.append(Paragraph(f"{perc:.1f}°", BODY))
                    else:
                        row_data.append(Paragraph("—", BODY))
                if has_cutoffs:
                    if ha_cutoff:
                        co = r.get('cutoff')
                        row_data.append(Paragraph(_esc(co['etichetta']), BODY))
                        row_data.append(Paragraph(f"[{co['da']} – {co['a']}]", BODY))
                    else:
                        row_data.extend([Paragraph("—", BODY), Paragraph("—", BODY)])

                rows_dettaglio.append(row_data)

            if len(rows_dettaglio) > 1:
                n_extra = len(hdr_dettaglio) - 2
                w_dim = 5.0 * cm if n_extra >= 3 else (6.5 * cm if n_extra == 2 else 8.5 * cm)
                w_punt = 2.0 * cm
                w_rem = (17.0 * cm - w_dim - w_punt) / max(1, n_extra)
                cw = [w_dim, w_punt] + [w_rem] * n_extra

                t_det = Table(rows_dettaglio, colWidths=cw, repeatRows=1)
                t_det.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#EAEDED')),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#DEE2E6')),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F8F9FA')]),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('LEFTPADDING', (0,0), (-1,-1), 6),
                    ('RIGHTPADDING', (0,0), (-1,-1), 6),
                    ('TOPPADDING', (0,0), (-1,-1), 4),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ]))
                story.append(Paragraph("Dettaglio Valori Normativi, PE e Cut-off", H1))
                story.append(t_det)

        # 4. Note Interpretative Estese
        note_blocks = []
        for r in risultati_dim.values():
            co = r.get('cutoff')
            if co and co.get('descrizione_estesa'):
                note_blocks.append(Paragraph(f"<b>{_esc(r['nome'])}</b> — <i>{_esc(co['etichetta'])}</i>", H2))
                note_blocks.append(Paragraph(_esc(co['descrizione_estesa']).replace('\n', '<br/>'), BODY))
                note_blocks.append(Spacer(1, 0.15 * cm))
        if note_blocks:
            story.append(Paragraph("Note Interpretative", H1))
            story.extend(note_blocks)

    # --- 5. OSSERVAZIONI CLINICHE ---
    if osservazioni_cliniche and osservazioni_cliniche.strip():
        story.append(Paragraph("Osservazioni Cliniche", H1))
        paragrafi_oss = [
            Paragraph(_esc(p).replace('\n', '<br/>'), BODY)
            for p in osservazioni_cliniche.strip().split('\n\n') if p.strip()
        ]
        if not paragrafi_oss:
            paragrafi_oss = [Paragraph(_esc(osservazioni_cliniche.strip()).replace('\n', '<br/>'), BODY)]
        rows_oss = [[p] for p in paragrafi_oss]
        t_oss = Table(rows_oss, colWidths=[17.0 * cm])
        t_oss.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8F9FA')),
            ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#BDC3C7')),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(t_oss)
        story.append(Spacer(1, 0.2 * cm))

    # --- 6. FIRMA DEL PROFESSIONISTA (dalle Impostazioni Globali) ---
    config_curr = load_config()
    firma_text = config_curr.get("firma_text", "").strip()
    if firma_text:
        SIG_STYLE = ParagraphStyle('SigStyle', parent=BODY, alignment=1, fontSize=9.5, leading=13)
        firma_html = _esc(firma_text).replace('\n', '<br/>')
        t_firma = Table([
            [Paragraph("", BODY), Paragraph(f"<b>{firma_html}</b>", SIG_STYLE)],
            [Paragraph("", BODY), Paragraph("________________________________________", SIG_STYLE)]
        ], colWidths=[9.5 * cm, 7.5 * cm])
        t_firma.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('TOPPADDING', (1, 1), (1, 1), 18),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(KeepTogether([
            Spacer(1, 0.45 * cm),
            t_firma,
            Spacer(1, 0.2 * cm)
        ]))

    # --- DETTAGLIO RISPOSTE ---
    if engine.sezioni:
        story.append(CondPageBreak(5.0 * cm))
        story.append(Paragraph("Protocollo Risposte Somministrate", H1))

        crit_map = {(c['sezione_id'], c['id']): c for c in item_critici}

        for sez in engine.sezioni:
            story.append(Paragraph(_esc(sez['titolo']), H2))
            risposte_sez = risposte_per_sezione.get(sez['id'], {})
            tipo = sez['tipo']

            reverse_in_sez = set()
            for dim in engine.dimensioni:
                if dim.get('sezione_id') == sez['id']:
                    reverse_in_sez.update(dim.get('item_ids_reverse', []))

            if tipo == 'likert':
                etichette = sez.get('opzioni_etichette', [])
                valori = sez.get('opzioni_valori', [])
                hdr = [Paragraph(h, TH_STYLE) for h in ["#", "Item", "Risposta", "Punti", "Note"]]
                rows_sez = [hdr]
                for item in sez.get('items', []):
                    iid = item['id']
                    idx_risposta = risposte_sez.get(iid)
                    if isinstance(idx_risposta, int) and 0 <= idx_risposta < len(valori):
                        val_effettivo = list(reversed(valori))[idx_risposta] if iid in reverse_in_sez else valori[idx_risposta]
                        etich = etichette[idx_risposta] if idx_risposta < len(etichette) else "—"
                    else:
                        val_effettivo = idx_risposta if idx_risposta is not None else "—"
                        etich = "—"

                    flags = []
                    if iid in reverse_in_sez: flags.append("R")
                    if (sez['id'], iid) in crit_map: flags.append("CRIT")
                    flag_str = " / ".join(flags)

                    rows_sez.append([
                        Paragraph(_esc(iid), BODY),
                        Paragraph(_esc(item['testo']), BODY),
                        Paragraph(_esc(etich), BODY),
                        Paragraph(_esc(val_effettivo), BODY),
                        Paragraph(flag_str, ParagraphStyle('Rev', parent=BODY, fontSize=8,
                                                           textColor=colors.HexColor('#E74C3C'))),
                    ])
                t = Table(rows_sez, colWidths=[1.0 * cm, 9.4 * cm, 3.8 * cm, 1.4 * cm, 1.4 * cm], repeatRows=1)
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EAEDED')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
                    ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#DEE2E6')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 5),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))
                story.append(t)

            elif tipo == 'numerico':
                hdr = [Paragraph(h, TH_STYLE) for h in ["#", "Prova / Item Numerico", "Valore", "Note"]]
                rows_num = [hdr]
                for item in sez.get('items', []):
                    iid = item['id']
                    val_num = risposte_sez.get(iid)
                    val_str = f"{val_num:g}" if isinstance(val_num, (int, float)) else "—"
                    flags = []
                    if iid in reverse_in_sez: flags.append("R")
                    if (sez['id'], iid) in crit_map: flags.append("CRIT")
                    flag_str = " / ".join(flags)

                    rows_num.append([
                        Paragraph(_esc(iid), BODY),
                        Paragraph(_esc(item['testo']), BODY),
                        Paragraph(f"<b>{_esc(val_str)}</b>", BODY),
                        Paragraph(flag_str, ParagraphStyle('RevN', parent=BODY, fontSize=8,
                                                           textColor=colors.HexColor('#E74C3C'))),
                    ])
                t_num = Table(rows_num, colWidths=[1.0 * cm, 12.0 * cm, 2.5 * cm, 1.5 * cm], repeatRows=1)
                t_num.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EAEDED')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
                    ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#DEE2E6')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 5),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))
                story.append(t_num)

            elif tipo == 'aperta':
                for item in sez.get('items', []):
                    risposta = risposte_sez.get(item['id'], "")
                    risp_html = _esc(risposta).replace('\n', '<br/>') if risposta else "[Nessuna risposta]"
                    story.append(Paragraph(f"<b>{_esc(item['id'])}. {_esc(item['testo'])}</b>",
                                           ParagraphStyle('ApQ', parent=BODY, keepWithNext=True)))
                    story.append(Paragraph(risp_html, BODY))
                    story.append(Spacer(1, 0.15 * cm))

            elif tipo == 'si_no':
                rows_sn = [[Paragraph("#", TH_STYLE), Paragraph("Item", TH_STYLE), Paragraph("Risposta", TH_STYLE)]]
                for item in sez.get('items', []):
                    val = risposte_sez.get(item['id'], "—")
                    is_c = " [CRIT]" if (sez['id'], item['id']) in crit_map else ""
                    rows_sn.append([
                        Paragraph(_esc(item['id']), BODY),
                        Paragraph(_esc(item['testo']), BODY),
                        Paragraph(f"<b>{_esc(val)}{is_c}</b>", BODY)
                    ])
                t_sn = Table(rows_sn, colWidths=[1.0 * cm, 13.5 * cm, 2.5 * cm], repeatRows=1)
                t_sn.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EAEDED')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
                    ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#DEE2E6')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 5),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))
                story.append(t_sn)

            story.append(Spacer(1, 0.3 * cm))

    return story

def genera_pdf(engine, dati_paziente, risposte_per_sezione,
               risultati_dim, output_path, opzioni_grafico, osservazioni_cliniche=""):
    config = load_config()
    tmp_dir = tempfile.mkdtemp()

    try:
        doc = SimpleDocTemplate(output_path, pagesize=A4,
                                rightMargin=2.0*cm, leftMargin=2.0*cm,
                                topMargin=2.5*cm, bottomMargin=2.3*cm)
        story = _build_pdf_story(engine, dati_paziente, risposte_per_sezione,
                                 risultati_dim, tmp_dir, opzioni_grafico, osservazioni_cliniche)

        doc.build(story,
                  onFirstPage=lambda c, d: draw_header_footer(c, d, config),
                  onLaterPages=lambda c, d: draw_header_footer(c, d, config))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def stampa_pdf(engine, dati_paziente, risposte_per_sezione,
               risultati_dim, opzioni_grafico, osservazioni_cliniche=""):
    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp.close()

    genera_pdf(engine, dati_paziente, risposte_per_sezione,
               risultati_dim, tmp.name, opzioni_grafico, osservazioni_cliniche)

    if sys.platform.startswith('win'):
        os.startfile(tmp.name)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', tmp.name])
    else:
        subprocess.Popen(['xdg-open', tmp.name])


# ─────────────────────────────────────────────
#  FINESTRE COMPONENTI DI INTERFACCIA ED EDITOR
# ─────────────────────────────────────────────

class FormulaBuilderWindow(ctk.CTkToplevel):
    """ TASTIERINA VIRTUALE INTERATTIVA COMPOSIZIONE FORMULE """
    def __init__(self, master, entry_target, ids_disponibili):
        super().__init__(master)
        self.title("Componitore Guidato di Formule")
        self.geometry("640x480")
        self.transient(master)
        self.grab_set()

        self.entry_target = entry_target
        self.tokens = [t for t in entry_target.get().split(" ") if t]

        ctk.CTkLabel(self, text="Compositore di Formule Avanzate",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        # Monitor di visualizzazione formula corrente
        self.lbl_monitor = ctk.CTkLabel(self, text=self._render_formula(), font=ctk.CTkFont(size=14, family="Courier"),
                                        fg_color=("#E5E8E8","#2C3E50"), height=40, corner_radius=6, width=600)
        self.lbl_monitor.pack(padx=20, pady=10)

        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=20, pady=10)

        # Pannello Sinistro: Dimensioni Disponibili
        left_p = ctk.CTkFrame(main_frame)
        left_p.pack(side="left", fill="both", expand=True, padx=(0,5))
        ctk.CTkLabel(left_p, text="Dimensioni Esistenti", font=ctk.CTkFont(weight="bold")).pack(pady=5)

        scr_ids = ctk.CTkScrollableFrame(left_p)
        scr_ids.pack(fill="both", expand=True, padx=5, pady=5)

        for did in ids_disponibili:
            if did:
                ctk.CTkButton(scr_ids, text=did, fg_color="#34495E", hover_color="#2C3E50",
                              command=lambda d=did: self._inserisci_token(d)).pack(fill="x", pady=2, padx=2)

        # Pannello Destro: Tastierino Matematico/Numerico
        right_p = ctk.CTkFrame(main_frame, width=280)
        right_p.pack(side="right", fill="both", padx=(5,0))
        ctk.CTkLabel(right_p, text="Tastierino Calcolo", font=ctk.CTkFont(weight="bold")).pack(pady=5)

        pad_grid = ctk.CTkFrame(right_p, fg_color="transparent")
        pad_grid.pack(pady=5)

        tasti = [
            ('7', 0, 0), ('8', 0, 1), ('9', 0, 2), ('/', 0, 3),
            ('4', 1, 0), ('5', 1, 1), ('6', 1, 2), ('*', 1, 3),
            ('1', 2, 0), ('2', 2, 1), ('3', 2, 2), ('-', 2, 3),
            ('0', 3, 0), ('.', 3, 1), ('(', 3, 2), ('+', 3, 3),
        ]

        for (simbolo, r, c) in tasti:
            ctk.CTkButton(pad_grid, text=simbolo, width=50, height=38, font=ctk.CTkFont(size=13, weight="bold"),
                          fg_color=("#D5DBDB", "#566573") if simbolo.isdigit() or simbolo=='.' else "#E67E22",
                          text_color="white" if not (simbolo.isdigit() or simbolo=='.') else ("black","white"),
                          command=lambda s=simbolo: self._inserisci_token(s)).grid(row=r, column=c, padx=3, pady=3)

        # Bottoni di controllo Annulla ed Elimina
        ctrl_f = ctk.CTkFrame(right_p, fg_color="transparent")
        ctrl_f.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(ctrl_f, text="✕ Rimuovi Ultimo", fg_color="#C0392B", hover_color="#922B21",
                      command=self._cancella_ultimo).pack(fill="x", pady=2)
        ctk.CTkButton(ctrl_f, text="🗑 Svuota Tutto", fg_color="#7B241C", hover_color="#641E16",
                      command=self._svuota_tutto).pack(fill="x", pady=2)

        # Salvataggio
        ctk.CTkButton(self, text="💾 Conferma Formula", fg_color="#27AE60", hover_color="#1E8449",
                      height=40, font=ctk.CTkFont(weight="bold"), command=self._conferma).pack(pady=15)

    def _render_formula(self):
        if not self.tokens: return "[Formula Vuota]"
        return " ".join(self.tokens)

    def _inserisci_token(self, valore):
        self.tokens.append(valore)
        self.lbl_monitor.configure(text=self._render_formula())

    def _cancella_ultimo(self):
        if self.tokens:
            self.tokens.pop()
        self.lbl_monitor.configure(text=self._render_formula())

    def _svuota_tutto(self):
        self.tokens.clear()
        self.lbl_monitor.configure(text=self._render_formula())

    def _conferma(self):
        self.entry_target.delete(0, 'end')
        self.entry_target.insert(0, " ".join(self.tokens))
        self.destroy()


class ImpostazioniWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Impostazioni Globali Report")
        self.geometry("600x820")
        self.minsize(580, 760)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._chiudi_sicuro)

        self.config = load_config()
        ctk.CTkLabel(self, text="Carta Intestata e Firma PDF", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(14, 6))

        frame_logo = ctk.CTkFrame(self, fg_color="transparent")
        frame_logo.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(frame_logo, text="Logo Aziendale (JPG/PNG):", font=ctk.CTkFont(weight="bold")).pack(anchor="w")

        row_logo = ctk.CTkFrame(frame_logo, fg_color="transparent")
        row_logo.pack(fill="x", pady=3)
        self.lbl_logo_path = ctk.CTkLabel(row_logo, text=self.config.get("logo_path") or "Nessun logo selezionato",
                                          text_color="gray", width=350, anchor="w")
        self.lbl_logo_path.pack(side="left")
        ctk.CTkButton(row_logo, text="Sfoglia...", width=80, command=self._seleziona_logo).pack(side="left", padx=5)
        ctk.CTkButton(row_logo, text="Rimuovi", width=80, fg_color="#E74C3C", hover_color="#C0392B",
                      command=self._rimuovi_logo).pack(side="left", padx=5)

        row_pos = ctk.CTkFrame(frame_logo, fg_color="transparent")
        row_pos.pack(fill="x", pady=3)
        ctk.CTkLabel(row_pos, text="Posizione logo:", width=140).pack(side="left")
        self.seg_logo_pos = ctk.CTkSegmentedButton(row_pos, values=["sinistra", "centro", "destra"],
                                                   command=self._aggiorna_pos_logo_live)
        self.seg_logo_pos.set(self.config.get("logo_position", "destra"))
        self.seg_logo_pos.pack(side="left", padx=5)

        frame_tema = ctk.CTkFrame(self, fg_color="transparent")
        frame_tema.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(frame_tema, text="Tema Interfaccia:", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        row_tema = ctk.CTkFrame(frame_tema, fg_color="transparent")
        row_tema.pack(fill="x", pady=3)
        ctk.CTkLabel(row_tema, text="Modalità:", width=140).pack(side="left")
        self.seg_tema = ctk.CTkSegmentedButton(row_tema, values=["Light", "Dark", "System"],
                                               command=self._aggiorna_tema_live)
        self.seg_tema.set(self.config.get("tema", "System"))
        self.seg_tema.pack(side="left", padx=5)


        #----ZOOM----
        row_zoom = ctk.CTkFrame(frame_tema, fg_color="transparent")
        row_zoom.pack(fill="x", pady=3)
        ctk.CTkLabel(row_zoom, text="Scala Interfaccia (Zoom):", width=140).pack(side="left")
        self.seg_zoom = ctk.CTkSegmentedButton(row_zoom, values=["80%", "100%", "125%", "150%"],
                                               command=self._aggiorna_zoom_live)
        self.seg_zoom.set(self.config.get("zoom_ui", "100%"))
        self.seg_zoom.pack(side="left", padx=5)

        # --- CAMPO FIRMA DEL PROFESSIONISTA ---
        frame_firma = ctk.CTkFrame(self, fg_color="transparent")
        frame_firma.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(frame_firma, text="Firma del Professionista (es. Titolo, Nome, N. Iscrizione Albo):",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        self.text_firma = ctk.CTkTextbox(frame_firma, height=52)
        self.text_firma.pack(fill="x", pady=3)
        self.text_firma.insert("1.0", self.config.get("firma_text", ""))

        frame_footer = ctk.CTkFrame(self, fg_color="transparent")
        frame_footer.pack(fill="x", padx=20, pady=4)
        ctk.CTkLabel(frame_footer, text="Testo Piè di Pagina (Sede legale, Indirizzo, ecc.):",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        self.text_footer = ctk.CTkTextbox(frame_footer, height=55)
        self.text_footer.pack(fill="x", pady=3)
        self.text_footer.insert("1.0", self.config.get("footer_text", ""))

        # --- SEZIONE COLORI TAG CON LIVE UPDATE ---
        frame_tags = ctk.CTkFrame(self, fg_color="transparent")
        frame_tags.pack(fill="both", expand=True, padx=20, pady=4)
        ctk.CTkLabel(frame_tags, text="Colori Categorie (Salvataggio Automatico):",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w")

        self.scroll_tags = ctk.CTkScrollableFrame(frame_tags, height=110)
        self.scroll_tags.pack(fill="both", expand=True, pady=3)

        self.color_map = {
            "Smeraldo (Default)": "#16A085", "Azzurro": "#3498DB", "Blu Notte": "#2980B9",
            "Rosso": "#E74C3C", "Arancione": "#D35400", "Giallo": "#F39C12",
            "Viola": "#8E44AD", "Grigio Neutro": "#7F8C8D", "Rosa": "#E84393"
        }
        rev_color_map = {v: k for k, v in self.color_map.items()}
        colori_salvati = self.config.get("colori_tag", {})

        for cat in getattr(self.master, 'categorie_disponibili', []):
            row = ctk.CTkFrame(self.scroll_tags, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=cat, width=200, anchor="w").pack(side="left")

            saved_hex = colori_salvati.get(cat, "#16A085")
            ui_val = rev_color_map.get(saved_hex, "Smeraldo (Default)")

            menu = ctk.CTkOptionMenu(row, values=list(self.color_map.keys()), width=150,
                                     command=lambda val, c=cat: self._aggiorna_colore_live(val, c))
            menu.set(ui_val)
            menu.pack(side="right")

        if sys.platform.startswith('win'):
            ctk.CTkButton(
                self, text="🖼️ Associa Icone File (.psyt / .psyp) in Windows", height=34,
                fg_color="#34495E", hover_color="#2C3E50",
                command=self._associa_icone
            ).pack(pady=(6, 2), padx=20, fill="x")

        ctk.CTkButton(self, text="💾 Salva Impostazioni Report", height=44, fg_color="#28a745", hover_color="#218838",
                      font=ctk.CTkFont(weight="bold", size=14), command=self._salva_report).pack(pady=(4, 14), padx=20, fill="x")



    def _ripristina_finestra(self):
        if self.winfo_exists():
            self.deiconify()
            self.lift()
            self.focus_force()
            self.grab_set()

    def _chiudi_sicuro(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _aggiorna_tema_live(self, nuovo_tema):
        self.config = load_config()
        self.config["tema"] = nuovo_tema
        save_config(self.config)
        self.grab_release()
        self.transient(None)
        ctk.set_appearance_mode(nuovo_tema)
        self.after(150, self._ripristina_finestra)

    def _aggiorna_pos_logo_live(self, nuova_pos):
        self.config = load_config()
        self.config["logo_position"] = nuova_pos
        save_config(self.config)

    def _aggiorna_colore_live(self, selezione, categoria):
        hex_color = self.color_map.get(selezione, "#16A085")
        self.config = load_config()
        if "colori_tag" not in self.config:
            self.config["colori_tag"] = {}
        self.config["colori_tag"][categoria] = hex_color
        save_config(self.config)
        if hasattr(self.master, 'mostra_libreria'):
            self.master.mostra_libreria()
        self.after(50, self._ripristina_finestra)

    def _associa_icone(self):
        ok, msg = registra_estensioni_windows()
        if ok:
            messagebox.showinfo("Associazione Completata", msg, parent=self)
        else:
            messagebox.showerror("Errore", msg, parent=self)

    def _seleziona_logo(self):
        path = filedialog.askopenfilename(title="Seleziona Logo", filetypes=[("Immagini", "*.png;*.jpg;*.jpeg")])
        if path:
            self.lbl_logo_path.configure(text=path)
        self.after(50, self._ripristina_finestra)

    def _rimuovi_logo(self):
        self.lbl_logo_path.configure(text="Nessun logo selezionato")

    def _aggiorna_zoom_live(self, nuovo_zoom):
        self.config = load_config()
        self.config["zoom_ui"] = nuovo_zoom
        save_config(self.config)

        try:
            zoom_factor = float(nuovo_zoom.replace('%', '')) / 100.0
        except ValueError:
            zoom_factor = 1.0

        ctk.set_widget_scaling(zoom_factor)
        ctk.set_window_scaling(zoom_factor)
        self.after(150, self._ripristina_finestra)


    def _salva_report(self):
        self.config = load_config()
        nuovo_path = self.lbl_logo_path.cget("text")
        if nuovo_path == "Nessun logo selezionato":
            nuovo_path = ""

        self.config["logo_path"] = nuovo_path
        self.config["firma_text"] = self.text_firma.get("1.0", "end-1c").strip()
        self.config["footer_text"] = self.text_footer.get("1.0", "end-1c").strip()
        self.config["logo_position"] = self.seg_logo_pos.get()
        self.config["tema"] = self.seg_tema.get()
        self.config["zoom_ui"] = self.seg_zoom.get()

        save_config(self.config)

        messagebox.showinfo("Successo", "Impostazioni Report salvate correttamente.", parent=self)
        self._chiudi_sicuro()


class OpzioniGraficoWindow(ctk.CTkToplevel):
    def __init__(self, master, risultati_dim, engine, callback_stampa, callback_salva):
        super().__init__(master)
        self.title("Opzioni Grafico / Report")
        self.geometry("680x560")
        self.transient(master)
        self.grab_set()
        self.callback_stampa = callback_stampa
        self.callback_salva  = callback_salva
        self.risultati_dim   = risultati_dim
        self.engine          = engine

        ctk.CTkLabel(self, text="Opzioni Grafico per ogni Dimensione",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 6))

        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=20, pady=10)

        self.vars_tipo   = {}
        self.vars_cutoff = {}

        for dim_id, r in risultati_dim.items():
            dim_obj  = next((d for d in engine.dimensioni if d['id'] == dim_id), {})
            ha_norma = bool(dim_obj.get('norma', {}).get('media'))

            card = ctk.CTkFrame(scroll, corner_radius=8, border_width=1, border_color="gray")
            card.pack(fill="x", pady=5)
            ctk.CTkLabel(card, text=r['nome'], font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(8,4))

            row = ctk.CTkFrame(card, fg_color="transparent"); row.pack(fill="x", padx=12, pady=(0,8))
            ctk.CTkLabel(row, text="Tipo grafico:", width=110).pack(side="left")

            opzioni = ["barre", "linea", "gaussiana"] if ha_norma else ["barre", "linea"]
            v_tipo = ctk.StringVar(value=dim_obj.get('tipo_grafico', 'barre'))
            self.vars_tipo[dim_id] = v_tipo
            ctk.CTkOptionMenu(row, values=opzioni, variable=v_tipo, width=130).pack(side="left", padx=8)

            ctk.CTkLabel(row, text="Mostra cut-off:", width=115).pack(side="left", padx=(12,0))
            v_co = ctk.BooleanVar(value=dim_obj.get('mostra_cutoff', True))
            self.vars_cutoff[dim_id] = v_co
            ctk.CTkSwitch(row, text="", variable=v_co, width=50).pack(side="left")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=14, fill="x", padx=20)
        ctk.CTkButton(btn_frame, text="🖨  Stampa (senza salvare)", command=self._stampa,
                      height=40, font=ctk.CTkFont(size=14, weight="bold"), fg_color="#8E44AD", hover_color="#6C3483").pack(side="left", expand=True, padx=5)
        ctk.CTkButton(btn_frame, text="💾  Salva PDF", command=self._salva,
                      height=40, font=ctk.CTkFont(size=14, weight="bold"), fg_color="#C0392B", hover_color="#922B21").pack(side="right", expand=True, padx=5)

    def _get_opzioni(self):
        return {dim_id: {'tipo': self.vars_tipo[dim_id].get(), 'cutoff': self.vars_cutoff[dim_id].get()} for dim_id in self.vars_tipo}

    def _stampa(self): self.callback_stampa(self._get_opzioni())
    def _salva(self): self.callback_salva(self._get_opzioni())


class EsportaWindow(ctk.CTkToplevel):
    def __init__(self, master, test_data):
        super().__init__(master)
        self.title("Esporta Test e Pacchetti (.psyt / .psyp)")
        self.geometry("580x520")
        self.transient(master)
        self.grab_set()
        self.test_data = test_data
        self.vars_sel = {}

        ctk.CTkLabel(self, text="Esportazione Modelli e Pacchetti", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(20, 5))
        ctk.CTkLabel(self, text="• Seleziona 1 test per esportare un file singolo (.psyt)\n• Seleziona 2 o più test per creare un pacchetto multiplo (.psyp)", text_color="gray").pack(pady=(0, 15))

        btn_sel_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_sel_frame.pack(fill="x", padx=25)
        ctk.CTkButton(btn_sel_frame, text="Seleziona Tutti", width=110, height=28, fg_color="#34495E", command=self._sel_tutti).pack(side="left", padx=(0, 5))
        ctk.CTkButton(btn_sel_frame, text="Deseleziona Tutti", width=110, height=28, fg_color="#7F8C8D", command=self._desel_tutti).pack(side="left")

        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=25, pady=10)

        for tid, info in sorted(self.test_data.items(), key=lambda x: x[1]['nome']):
            v = ctk.BooleanVar(value=False)
            self.vars_sel[tid] = v
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=3)
            tipo_badge = "[.psyt]" if info['is_psyt'] else "[.json]"
            ctk.CTkCheckBox(row, text=f"{info['nome']}  {tipo_badge}", variable=v, font=ctk.CTkFont(size=13)).pack(side="left", padx=5)

        ctk.CTkButton(self, text="📤 Esporta Selezionati...", height=45, fg_color="#27AE60", hover_color="#1E8449",
                      font=ctk.CTkFont(weight="bold", size=14), command=self._esporta).pack(pady=15, padx=25, fill="x")

    def _sel_tutti(self):
        for v in self.vars_sel.values(): v.set(True)

    def _desel_tutti(self):
        for v in self.vars_sel.values(): v.set(False)

    def _crea_psyt_da_sorgente(self, tid, dest_psyt):
        info = self.test_data[tid]
        src = info['filepath']
        if src.endswith('.psyt'):
            shutil.copy2(src, dest_psyt)
        else:
            with zipfile.ZipFile(dest_psyt, 'w', zipfile.ZIP_DEFLATED) as z:
                z.write(src, 'test.json')

    def _esporta(self):
        selezionati = [tid for tid, v in self.vars_sel.items() if v.get()]
        if not selezionati:
            messagebox.showwarning("Attenzione", "Seleziona almeno un test da esportare.")
            return

        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.exists(desktop): desktop = os.path.expanduser("~")

        if len(selezionati) == 1:
            tid = selezionati[0]
            dest = filedialog.asksaveasfilename(
                initialdir=desktop,
                title="Esporta Test Singolo (.psyt)",
                defaultextension=".psyt",
                initialfile=f"{tid}.psyt",
                filetypes=[("PsychoScorer Test", "*.psyt"), ("JSON Puro (Senza PDF)", "*.json")]
            )
            if not dest: return
            try:
                if dest.endswith('.json'):
                    src = self.test_data[tid]['filepath']
                    if src.endswith('.psyt'):
                        with zipfile.ZipFile(src, 'r') as z:
                            with open(dest, 'wb') as f_out:
                                f_out.write(z.read('test.json'))
                    else:
                        shutil.copy2(src, dest)
                else:
                    self._crea_psyt_da_sorgente(tid, dest)
                messagebox.showinfo("Esportazione Completata", f"Test esportato con successo in:\n{dest}")
                self.destroy()
            except Exception as e:
                messagebox.showerror("Errore", str(e))
        else:
            dest = filedialog.asksaveasfilename(
                initialdir=desktop,
                title="Esporta Pacchetto Multi-Test (.psyp)",
                defaultextension=".psyp",
                initialfile="Pacchetto_Test.psyp",
                filetypes=[("PsychoScorer Package", "*.psyp")]
            )
            if not dest: return
            tmp_dir = tempfile.mkdtemp()
            try:
                with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z_pack:
                    for tid in selezionati:
                        tmp_psyt = os.path.join(tmp_dir, f"{tid}.psyt")
                        self._crea_psyt_da_sorgente(tid, tmp_psyt)
                        z_pack.write(tmp_psyt, f"{tid}.psyt")
                messagebox.showinfo("Esportazione Completata", f"Pacchetto di {len(selezionati)} test (.psyp) esportato con successo in:\n{dest}")
                self.destroy()
            except Exception as e:
                messagebox.showerror("Errore", str(e))
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
# ─────────────────────────────────────────────
#  TEST EDITOR ARCHITECTURE (V4)
# ─────────────────────────────────────────────

class EditorCondizioni:
    """Elenco di condizioni 'variabile operatore valore' unite da E (AND), con un numero libero di righe.
    Serve a correzioni e set di soglie PE: permette di incrociare quante variabili anagrafiche servono
    (eta', scolarita', sesso, ...). Le condizioni sono salvate come stringhe, es. "Eta >= 60"."""
    PY_TO_UI = {"==": "=", "!=": "≠", ">": ">", "<": "<", ">=": "≥", "<=": "≤"}
    UI_TO_PY = {v: k for k, v in PY_TO_UI.items()}

    def __init__(self, parent, vars_fn, condizioni=None):
        self.vars_fn = vars_fn
        self.righe = []
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.box = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.box.pack(anchor="w")
        self.lbl_vuoto = ctk.CTkLabel(self.box, text="sempre valida", text_color="gray", font=ctk.CTkFont(size=11))
        ctk.CTkButton(self.frame, text="➕ condizione", width=96, height=22,
                      command=self.aggiungi).pack(anchor="w", pady=(2, 0))
        for c in (condizioni or []):
            self.aggiungi(c)
        self._aggiorna_etichette()

    def aggiungi(self, condizione=None):
        var, op_ui, val = None, "=", ""
        if condizione:
            m = re.match(r"(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)", condizione.strip())
            if m:
                var = m.group(1).strip()
                op_ui = self.PY_TO_UI.get(m.group(2), "=")
                val = m.group(3).strip().strip("'\"")
        opzioni = list(self.vars_fn()) or ["—"]
        if var and var not in opzioni:
            opzioni.append(var)   # un campo non piu' in anagrafica resta visibile invece di sparire in silenzio
        riga = ctk.CTkFrame(self.box, fg_color="transparent")
        riga.pack(anchor="w", pady=1)
        lbl = ctk.CTkLabel(riga, text="", width=22, font=ctk.CTkFont(size=11, weight="bold"))
        lbl.pack(side="left")
        m_var = ctk.CTkOptionMenu(riga, values=opzioni, width=120)
        m_var.set(var or opzioni[0])
        m_var.pack(side="left", padx=2)
        m_op = ctk.CTkOptionMenu(riga, values=list(self.UI_TO_PY.keys()), width=54)
        m_op.set(op_ui)
        m_op.pack(side="left")
        e_val = ctk.CTkEntry(riga, width=64)
        e_val.insert(0, val)
        e_val.pack(side="left", padx=2)
        voce = {'frame': riga, 'lbl': lbl, 'var': m_var, 'op': m_op, 'val': e_val}
        ctk.CTkButton(riga, text="✕", width=24, height=24, fg_color="#E74C3C", hover_color="#C0392B",
                      command=lambda v=voce: self.rimuovi(v)).pack(side="left", padx=3)
        self.righe.append(voce)
        self._aggiorna_etichette()

    def rimuovi(self, voce):
        if voce in self.righe:
            self.righe.remove(voce)
        voce['frame'].destroy()
        self._aggiorna_etichette()

    def _aggiorna_etichette(self):
        for i, r in enumerate(self.righe):
            r['lbl'].configure(text="" if i == 0 else "E")
        if self.righe:
            self.lbl_vuoto.pack_forget()
        else:
            self.lbl_vuoto.pack(anchor="w", padx=4)

    def condizioni_stringhe(self, strict=True):
        """strict=True: ValueError se manca variabile o valore (usato al salvataggio).
        strict=False: tollerante, per sincronizzare la vista senza perdere righe."""
        out = []
        for r in self.righe:
            var = r['var'].get().strip()
            if not var or var == "—":
                if strict:
                    raise ValueError("condizione senza variabile")
                continue
            op = self.UI_TO_PY.get(r['op'].get(), "==")
            v = r['val'].get().strip()
            if v == "":
                if strict:
                    raise ValueError(f"manca il valore della condizione su '{var}'")
                lit = "''"
            else:
                num = v.replace(',', '.')
                try:
                    float(num)
                    lit = num
                except ValueError:
                    lit = "'" + v.replace("'", "").replace('"', "") + "'"
            out.append(f"{var} {op} {lit}")
        return out


class TestEditorWindow(ctk.CTkToplevel):
    def __init__(self, master, db_folder):
        super().__init__(master)
        self.title("Editor Test Avanzato — v4")
        self.geometry("1050x880" if sys.platform == 'darwin' else "1080x880")
        self.db_folder = db_folder
        self.transient(master)
        self.grab_set()

        # Legge direttamente i file json dalla cartella senza dipendere dalla Vetrina principale
        # Legge sia i file .json che i pacchetti .psyt dalla cartella
        self.test_disponibili = {}
        if os.path.exists(self.db_folder):
            for fn in os.listdir(self.db_folder):
                if (fn.endswith(".json") or fn.endswith(".psyt")) and not fn.endswith("_old.json") and not fn.endswith(
                        "_old.psyt"):
                    fp = os.path.join(self.db_folder, fn)
                    try:
                        if fn.endswith(".psyt"):
                            with zipfile.ZipFile(fp, 'r') as z:
                                with z.open('test.json') as f: data = json.load(f)
                        else:
                            with open(fp, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                        nome_test = data.get('info_generali', {}).get('nome', fn)
                        self.test_disponibili[nome_test] = fp
                    except Exception:
                        pass

        frame_top = ctk.CTkFrame(self, fg_color="transparent")
        frame_top.pack(fill="x", padx=20, pady=(15, 0))
        ctk.CTkLabel(frame_top, text="Modifica test esistente:", font=ctk.CTkFont(weight="bold")).pack(side="left")

        # Popola la tendina con i file trovati
        nomi_ordinati = ["-- Seleziona --"] + sorted(list(self.test_disponibili.keys()))
        self.menu_carica = ctk.CTkOptionMenu(frame_top, values=nomi_ordinati, width=280)
        self.menu_carica.pack(side="left", padx=10)
        ctk.CTkButton(frame_top, text="Carica Test", command=self.carica_test).pack(side="left")

        ctk.CTkFrame(self, height=2, fg_color="gray").pack(fill="x", padx=20, pady=8)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(0, 5))
        self.tab_info = self.tabview.add("1. Info")
        self.tab_sezioni = self.tabview.add("2. Sezioni & Items")
        self.tab_dim = self.tabview.add("3. Dimensioni")
        self.tab_correzioni = self.tabview.add("4. Correzioni Punteggio")
        self.tab_cutoff = self.tabview.add("5. Cut-off")

        self._build_tab_info()
        self._build_tab_sezioni()
        self._build_tab_dim()
        self._build_tab_correzioni()
        self._build_tab_cutoff()

        ctk.CTkButton(self, text="💾  Salva Configurazione nel Database", command=self.salva_test,
                      height=44, font=ctk.CTkFont(size=15, weight="bold"), fg_color="#28a745",
                      hover_color="#218838").pack(pady=12)

    def _build_tab_info(self):
        f = self.tab_info
        for r, (lbl, attr, w) in enumerate([
            ("ID (nome file):", "entry_id", 200),
            ("Nome completo:", "entry_nome", 420),
            ("Autore/Riferimento:", "entry_autore", 420),
            ("Tag (separati da virgola):", "entry_categorie", 420),
        ]):
            ctk.CTkLabel(f, text=lbl).grid(row=r, column=0, padx=10, pady=8, sticky="w")
            e = ctk.CTkEntry(f, width=w)
            e.grid(row=r, column=1, padx=10, pady=8, sticky="w")
            setattr(self, attr, e)

        ctk.CTkLabel(f, text="Istruzioni:").grid(row=4, column=0, padx=10, pady=8, sticky="nw")
        self.text_istruzioni = ctk.CTkTextbox(f, width=420, height=110)
        self.text_istruzioni.grid(row=4, column=1, padx=10, pady=8, sticky="w")

        ctk.CTkLabel(f, text="Anagrafica (virgola):").grid(row=5, column=0, padx=10, pady=8, sticky="w")
        self.entry_anagrafica = ctk.CTkEntry(f, width=420)
        self.entry_anagrafica.grid(row=5, column=1, padx=10, pady=8, sticky="w")
        self.entry_anagrafica.insert(0, "Nome, Cognome, Età, Genere, Data Somministrazione")

        # --- SEZIONE ALLEGATI PDF (.psyt) ---
        ctk.CTkLabel(f, text="Documenti PDF Allegati\n(Crea formato .psyt):", font=ctk.CTkFont(weight="bold")).grid(row=6, column=0, padx=10, pady=12, sticky="nw")
        frame_pdf = ctk.CTkFrame(f, corner_radius=8, border_width=1, border_color="gray")
        frame_pdf.grid(row=6, column=1, padx=10, pady=12, sticky="ew")

        self.pdf_attachments = {'protocollo': None, 'manuale': None, 'scoring': None}
        self.pdf_labels = {}

        for idx, (k, titolo) in enumerate([
            ('protocollo', '📄 Protocollo Somministrazione:'),
            ('manuale',    '📘 Manuale del Test:'),
            ('scoring',    '📊 Manuale di Scoring:')
        ]):
            row_p = ctk.CTkFrame(frame_pdf, fg_color="transparent")
            row_p.pack(fill="x", padx=10, pady=6)
            ctk.CTkLabel(row_p, text=titolo, width=210, anchor="w").pack(side="left")
            lbl_stato = ctk.CTkLabel(row_p, text="Nessun file", text_color="gray", width=180, anchor="w")
            lbl_stato.pack(side="left", padx=5)
            self.pdf_labels[k] = lbl_stato

            ctk.CTkButton(row_p, text="Rimuovi", width=70, height=26, fg_color="#E74C3C", hover_color="#C0392B",
                          command=lambda key=k: self._rimuovi_pdf_editor(key)).pack(side="right", padx=2)
            ctk.CTkButton(row_p, text="📎 Allega PDF", width=95, height=26, fg_color="#2980B9", hover_color="#21618C",
                          command=lambda key=k: self._seleziona_pdf_editor(key)).pack(side="right", padx=4)

    def _seleziona_pdf_editor(self, key):
        path = filedialog.askopenfilename(title=f"Seleziona PDF per {key.capitalize()}", filetypes=[("File PDF", "*.pdf")])
        if path:
            self.pdf_attachments[key] = path
            self.pdf_labels[key].configure(text=os.path.basename(path), text_color=("#27AE60", "#2ECC71"))

    def _rimuovi_pdf_editor(self, key):
        self.pdf_attachments[key] = None
        self.pdf_labels[key].configure(text="Nessun file", text_color="gray")


    def _build_tab_sezioni(self):
        self.sezioni_ui = []
        fc = ctk.CTkFrame(self.tab_sezioni, fg_color="transparent")
        fc.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(fc, text="Sezioni Strutturali Questionario", font=ctk.CTkFont(weight="bold", size=14)).pack(side="left")
        for tipo, lbl in [("likert","➕ Likert"), ("numerico","➕ Numerico"), ("aperta","➕ Aperta"), ("si_no","➕ Sì/No")]:
            ctk.CTkButton(fc, text=lbl, width=100, command=lambda t=tipo: self.aggiungi_sezione(t)).pack(side="right", padx=4)
        self.scroll_sezioni = ctk.CTkScrollableFrame(self.tab_sezioni)
        self.scroll_sezioni.pack(fill="both", expand=True, pady=5)

    def aggiungi_sezione(self, tipo, dati=None):
        idx    = len(self.sezioni_ui)
        sez_id = dati.get('id', f"sez{idx+1}") if dati else f"sez{idx+1}"
        colori = {"likert":"#2980B9", "numerico":"#16A085", "aperta":"#8E44AD", "si_no":"#27AE60"}
        nomi   = {"likert":"Scala Likert", "numerico":"Valore Numerico Diretto", "aperta":"Domanda Aperta", "si_no":"Sì / No"}

        card = ctk.CTkFrame(self.scroll_sezioni, corner_radius=8, border_width=1, border_color="gray")
        card.pack(fill="x", padx=5, pady=6)
        head = ctk.CTkFrame(card, fg_color=colori.get(tipo,"#555"), corner_radius=6)
        head.pack(fill="x", padx=4, pady=(4,0))
        ctk.CTkLabel(head, text=nomi.get(tipo,tipo), text_color="white", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=8, pady=4)
        ctk.CTkButton(head, text="✕ Rimuovi", width=80, height=24, fg_color="transparent", hover_color="#C0392B", text_color="white",
                      command=lambda c=card: self.rimuovi_sezione(c)).pack(side="right", padx=8)

        body = ctk.CTkFrame(card, fg_color="transparent"); body.pack(fill="x", padx=10, pady=6)
        row0 = ctk.CTkFrame(body, fg_color="transparent"); row0.pack(fill="x", pady=2)
        ctk.CTkLabel(row0, text="ID Sezione:", width=120).pack(side="left")
        e_id = ctk.CTkEntry(row0, width=120); e_id.pack(side="left", padx=5); e_id.insert(0, sez_id)
        ctk.CTkLabel(row0, text="  Titolo:", width=60).pack(side="left")
        e_titolo = ctk.CTkEntry(row0, width=280); e_titolo.pack(side="left", padx=5)
        if dati: e_titolo.insert(0, dati.get('titolo',''))

        e_etichette = e_valori = e_max_num = None
        if tipo == 'likert':
            row1 = ctk.CTkFrame(body, fg_color="transparent"); row1.pack(fill="x", pady=2)
            ctk.CTkLabel(row1, text="Etichette (virgola):", width=150).pack(side="left")
            e_etichette = ctk.CTkEntry(row1, width=380); e_etichette.pack(side="left", padx=5)
            e_etichette.insert(0, ", ".join(dati.get('opzioni_etichette',[])) if dati else "Per niente, Un po', Abbastanza, Moltissimo")
            row2 = ctk.CTkFrame(body, fg_color="transparent"); row2.pack(fill="x", pady=2)
            ctk.CTkLabel(row2, text="Valori (interi, virgola):", width=150).pack(side="left")
            e_valori = ctk.CTkEntry(row2, width=380); e_valori.pack(side="left", padx=5)
            e_valori.insert(0, ", ".join(map(str, dati.get('opzioni_valori',[]))) if dati else "0, 1, 2, 3")
        elif tipo == 'numerico':
            row1 = ctk.CTkFrame(body, fg_color="transparent"); row1.pack(fill="x", pady=2)
            ctk.CTkLabel(row1, text="Massimo teorico per item (opzionale, 0 = nessuno):", width=310, anchor="w").pack(side="left")
            e_max_num = ctk.CTkEntry(row1, width=90, placeholder_text="es. 15 o 0")
            e_max_num.pack(side="left", padx=5)
            e_max_num.insert(0, str(dati.get('max_numerico', 0)) if dati else "0")

        items_ui = []
        hdr = ctk.CTkFrame(body, fg_color="transparent"); hdr.pack(fill="x", pady=(6,2))
        ctk.CTkLabel(hdr, text="Items (e impostazione 🚩 Item Critico opzionale):", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(hdr, text="+ Aggiungi Item", width=100, height=24, command=lambda: _add_item()).pack(side="right")
        sc = ctk.CTkScrollableFrame(body, height=135); sc.pack(fill="x")

        def _aggiorna_numeri():
            for i, item_row in enumerate(items_ui):
                lbl = item_row['frame'].winfo_children()[0]
                if isinstance(lbl, ctk.CTkLabel): lbl.configure(text=f"{i + 1}.")

        def _remove_item(item_row):
            item_row['frame'].destroy()
            if item_row in items_ui: items_ui.remove(item_row)
            _aggiorna_numeri()

        def _add_item(item_data=None):
            testo = item_data.get('testo', '') if isinstance(item_data, dict) else (item_data or "")
            crit = item_data.get('critico', {}) if isinstance(item_data, dict) else {}

            r = ctk.CTkFrame(sc, fg_color="transparent"); r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text="", width=25).pack(side="left")
            e = ctk.CTkEntry(r, width=390, placeholder_text="Testo della domanda o prova..."); e.pack(side="left", padx=4)
            if testo: e.insert(0, testo)

            ctk.CTkLabel(r, text="🚩", width=18).pack(side="left", padx=(6, 2))
            op_crit = ctk.CTkOptionMenu(r, values=["No", "≥", "≤", "="], width=62)
            op_crit.set(crit.get('op', 'No') if crit else "No")
            op_crit.pack(side="left", padx=2)

            val_crit = ctk.CTkEntry(r, width=55, placeholder_text="Soglia")
            val_crit.pack(side="left", padx=2)
            if crit and crit.get('valore') is not None:
                val_crit.insert(0, str(crit.get('valore')))

            nota_crit = ctk.CTkEntry(r, width=165, placeholder_text="Nota allerta (es. Rischio)")
            nota_crit.pack(side="left", padx=2)
            if crit and crit.get('nota'):
                nota_crit.insert(0, crit.get('nota'))

            item_dict = {'frame': r, 'entry': e, 'op_crit': op_crit, 'val_crit': val_crit, 'nota_crit': nota_crit}
            ctk.CTkButton(r, text="✕", width=28, fg_color="#E74C3C", hover_color="#C0392B",
                          command=lambda ir=item_dict: _remove_item(ir)).pack(side="left", padx=3)
            items_ui.append(item_dict)
            _aggiorna_numeri()

        if dati:
            for item in dati.get('items', []): _add_item(item)
        else: _add_item()

        self.sezioni_ui.append({'card': card, 'tipo': tipo, 'entry_id': e_id, 'entry_titolo': e_titolo,
                                'entry_etichette': e_etichette, 'entry_valori': e_valori,
                                'entry_max_num': e_max_num, 'items_ui': items_ui})

    def rimuovi_sezione(self, card):
        for i, s in enumerate(self.sezioni_ui):
            if s['card'] == card:
                self.sezioni_ui.pop(i); card.destroy(); break

    def _build_tab_dim(self):
        self.dim_ui = []
        fc = ctk.CTkFrame(self.tab_dim, fg_color="transparent")
        fc.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(fc, text="Configurazione Dimensioni e Formule", font=ctk.CTkFont(weight="bold", size=14)).pack(side="left")
        ctk.CTkButton(fc, text="➕ Dimensione Standard", command=lambda: self.aggiungi_dimensione(is_formula=False)).pack(side="right", padx=2)
        ctk.CTkButton(fc, text="🧮 Calcolo Avanzato (Formula)", fg_color="#D35400", hover_color="#A04000",
                      command=lambda: self.aggiungi_dimensione(is_formula=True)).pack(side="right", padx=2)

        self.scroll_dim = ctk.CTkScrollableFrame(self.tab_dim)
        self.scroll_dim.pack(fill="both", expand=True, pady=5)

    def _build_tab_correzioni(self):
        self.correzioni_ui = {}
        fc = ctk.CTkFrame(self.tab_correzioni, fg_color="transparent")
        fc.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(fc, text="Tabella Piatta di Correzione Punteggio",
                     font=ctk.CTkFont(weight="bold", size=14)).pack(side="left")
        ctk.CTkButton(fc, text="🔄 Sincronizza Dimensioni", command=self._aggiorna_tab_correzioni).pack(side="right")
        self.scroll_correzioni = ctk.CTkScrollableFrame(self.tab_correzioni)
        self.scroll_correzioni.pack(fill="both", expand=True, pady=5)

    def _aggiorna_tab_correzioni(self):
        current_state = {}
        for did, info in self.correzioni_ui.items():
            if info.get('rows'):
                saved_rows = []
                for r in info['rows']:
                    try:
                        c_valore = r['valore'].get().strip().replace(',', '.')
                        if not c_valore: continue

                        condizioni = r['cond'].condizioni_stringhe(strict=False)
                        saved_rows.append({'condizioni': condizioni, 'valore': float(c_valore)})
                    except Exception:
                        pass
                current_state[did] = saved_rows
            else:
                current_state[did] = info.get('_raw', [])

        for w in self.scroll_correzioni.winfo_children(): w.destroy()
        self.correzioni_ui = {}

        anag_testo = self.entry_anagrafica.get()
        anag_vars = [re.sub(r'\[.*?\]', '', x).strip() for x in anag_testo.split(",") if x.strip()]
        opzioni_var = ["Nessuna"] + anag_vars

        for d in self.dim_ui:
            dim_id = d['e_id'].get().strip()
            dim_nome = d['e_nome'].get().strip()
            if not dim_id: continue

            frame_dim = ctk.CTkFrame(self.scroll_correzioni, corner_radius=8, border_width=1, border_color="gray")
            frame_dim.pack(fill="x", padx=5, pady=6)
            head = ctk.CTkFrame(frame_dim, fg_color="#8E44AD", corner_radius=6)
            head.pack(fill="x", padx=4, pady=(4, 0))
            ctk.CTkLabel(head, text=f"Correzioni: {dim_nome} [{dim_id}]", text_color="white",
                         font=ctk.CTkFont(weight="bold")).pack(side="left", padx=8, pady=4)

            rows_corr = []
            scroll_co = ctk.CTkScrollableFrame(frame_dim, height=140)
            scroll_co.pack(fill="x", padx=8, pady=4)

            def _remove_corr_row(container, r_list, r_dict):
                container.destroy()
                if r_dict in r_list: r_list.remove(r_dict)

            def _add_corr_row(parent, rows, condizioni=None, valore=""):
                if condizioni is None: condizioni = []
                riga_container = ctk.CTkFrame(parent, border_width=1, border_color="#e0e0e0")
                riga_container.pack(fill="x", pady=2, padx=2)

                riga = ctk.CTkFrame(riga_container, fg_color="transparent")
                riga.pack(fill="x", pady=4, padx=4)

                # Numero libero di condizioni in AND (es. Età, Scolarità, Genere...)
                cb = EditorCondizioni(riga, lambda: anag_vars, condizioni)
                cb.frame.pack(side="left", padx=2)

                ctk.CTkLabel(riga, text=" ➔ Aggiungi: ", text_color="#27AE60",
                             font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(10, 0))
                e_valore = ctk.CTkEntry(riga, width=70, placeholder_text="es. +1.5")
                e_valore.insert(0, str(valore))
                e_valore.pack(side="left")

                btn_del = ctk.CTkButton(riga, text="✕", width=30, fg_color="#E74C3C", hover_color="#C0392B")
                btn_del.pack(side="right", padx=5)

                row_dict = {'cond': cb, 'valore': e_valore}
                rows.append(row_dict)
                btn_del.configure(command=lambda: _remove_corr_row(riga_container, rows, row_dict))

            bf = ctk.CTkFrame(frame_dim, fg_color="transparent")
            bf.pack(anchor="w", padx=8, pady=(0, 6))
            ctk.CTkButton(bf, text="➕ Aggiungi Riga di Correzione",
                          command=lambda p=scroll_co, r=rows_corr: _add_corr_row(p, r), width=180, height=26,
                          fg_color="#9B59B6", hover_color="#8E44AD").pack(side="left")

            raw = current_state.get(dim_id, [])
            if raw:
                for rd in raw: _add_corr_row(scroll_co, rows_corr, condizioni=rd.get('condizioni', []),
                                             valore=rd.get('valore', ''))
            else:
                _add_corr_row(scroll_co, rows_corr)

            self.correzioni_ui[dim_id] = {'rows': rows_corr, '_raw': raw}

    def _vars_anagrafica(self):
        testo = self.entry_anagrafica.get() if hasattr(self, 'entry_anagrafica') else ""
        return [re.sub(r'\[.*?\]', '', x).strip() for x in testo.split(",") if x.strip()]

    def aggiungi_dimensione(self, dati=None, is_formula=False):
        idx    = len(self.dim_ui)
        dim_id = dati.get('id', f"dim{idx+1}") if dati else f"dim{idx+1}"

        if dati and dati.get('tipo_scoring') == 'formula':
            is_formula = True

        card = ctk.CTkFrame(self.scroll_dim, corner_radius=8, border_width=1, border_color="gray")
        card.pack(fill="x", padx=5, pady=6)

        colore_testata = "#E67E22" if not is_formula else "#D35400"
        titolo_testata = "Dimensione Basata su Item" if not is_formula else "Calcolo Composito Avanzato"

        head = ctk.CTkFrame(card, fg_color=colore_testata, corner_radius=6)
        head.pack(fill="x", padx=4, pady=(4,0))
        ctk.CTkLabel(head, text=titolo_testata, text_color="white", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=8, pady=4)
        ctk.CTkButton(head, text="✕", width=40, height=24, fg_color="transparent", text_color="white",
                      command=lambda c=card: self._rimuovi_card(c, self.dim_ui)).pack(side="right", padx=8)

        body = ctk.CTkFrame(card, fg_color="transparent"); body.pack(fill="x", padx=10, pady=6)

        row0 = ctk.CTkFrame(body, fg_color="transparent"); row0.pack(fill="x", pady=2)
        ctk.CTkLabel(row0, text="ID:", width=40).pack(side="left")
        e_id = ctk.CTkEntry(row0, width=100); e_id.pack(side="left", padx=4); e_id.insert(0, dim_id)
        ctk.CTkLabel(row0, text="  Nome:", width=55).pack(side="left")
        e_nome = ctk.CTkEntry(row0, width=260); e_nome.pack(side="left", padx=4)
        if dati: e_nome.insert(0, dati.get('nome',''))

        e_sez = e_items = e_scoring = e_reverse = e_formula = None

        if not is_formula:
            row1 = ctk.CTkFrame(body, fg_color="transparent"); row1.pack(fill="x", pady=2)
            ctk.CTkLabel(row1, text="ID Sezione:", width=80).pack(side="left")
            e_sez = ctk.CTkEntry(row1, width=90); e_sez.pack(side="left", padx=4)
            if dati: e_sez.insert(0, dati.get('sezione_id',''))
            ctk.CTkLabel(row1, text="  IDs item:", width=75).pack(side="left")
            e_items = ctk.CTkEntry(row1, width=160); e_items.pack(side="left", padx=4)
            if dati: e_items.insert(0, ", ".join(map(str, dati.get('item_ids',[]))))
            ctk.CTkLabel(row1, text="  Scoring:", width=65).pack(side="left")
            e_scoring = ctk.CTkOptionMenu(row1, values=["somma", "media"], width=100)
            e_scoring.set(dati.get('tipo_scoring','somma') if dati else 'somma')
            e_scoring.pack(side="left", padx=4)

            row2 = ctk.CTkFrame(body, fg_color="transparent"); row2.pack(fill="x", pady=2)
            ctk.CTkLabel(row2, text="IDs reverse (es. 3,7):", width=160).pack(side="left")
            e_reverse = ctk.CTkEntry(row2, width=200); e_reverse.pack(side="left", padx=4)
            if dati and dati.get('item_ids_reverse'): e_reverse.insert(0, ", ".join(map(str, dati['item_ids_reverse'])))
        else:
            row1 = ctk.CTkFrame(body, fg_color="transparent"); row1.pack(fill="x", pady=2)
            ctk.CTkLabel(row1, text="Formula Matematica:", width=130).pack(side="left")
            e_formula = ctk.CTkEntry(row1, width=320)
            e_formula.pack(side="left", padx=4)
            if dati: e_formula.insert(0, dati.get('formula',''))

            ctk.CTkButton(row1, text="🧮 Componi Formula", fg_color="#2980B9", hover_color="#21618C", width=120,
                          command=lambda: self._apri_builder(e_formula)).pack(side="left", padx=4)

        row3 = ctk.CTkFrame(body, fg_color="transparent"); row3.pack(fill="x", pady=2)
        ctk.CTkLabel(row3, text="Grafico default:", width=120).pack(side="left")
        e_tgraf = ctk.CTkOptionMenu(row3, values=["barre","linea","gaussiana"], width=110)
        e_tgraf.set(dati.get('tipo_grafico','barre') if dati else 'barre')
        e_tgraf.pack(side="left", padx=4)
        ctk.CTkLabel(row3, text="  Mostra cutoff:", width=110).pack(side="left")
        v_co = ctk.BooleanVar(value=dati.get('mostra_cutoff', True) if dati else True)
        ctk.CTkSwitch(row3, text="", variable=v_co, width=50).pack(side="left")

        row4 = ctk.CTkFrame(body, fg_color="transparent"); row4.pack(fill="x", pady=2)
        ctk.CTkLabel(row4, text="Norma — Media:", width=130).pack(side="left")
        norma = dati.get('norma', {}) if dati else {}
        e_media = ctk.CTkEntry(row4, width=80); e_media.pack(side="left", padx=4)
        if norma.get('media') is not None: e_media.insert(0, str(norma['media']))
        ctk.CTkLabel(row4, text="  DS:", width=40).pack(side="left")
        e_ds = ctk.CTkEntry(row4, width=80); e_ds.pack(side="left", padx=4)
        if norma.get('ds') is not None: e_ds.insert(0, str(norma['ds']))

        # --- RIGA 5: PUNTEGGI EQUIVALENTI (PE 0-4) ---
        row5 = ctk.CTkFrame(body, fg_color="transparent"); row5.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(row5, text="Punteggi Equivalenti (Soglie):", width=195, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold"), text_color=("#16A085", "#1ABC9C")).pack(side="left")
        pe_saved = dati.get('pe_soglie', []) if dati else []
        pe_entries = []
        for idx_pe, lbl_pe in enumerate(["PE 0→1:", "PE 1→2:", "PE 2→3:", "PE 3→4:"]):
            ctk.CTkLabel(row5, text=lbl_pe, font=ctk.CTkFont(size=11)).pack(side="left", padx=(6, 2))
            ep = ctk.CTkEntry(row5, width=60, placeholder_text="soglia")
            ep.pack(side="left", padx=2)
            if len(pe_saved) == 4 and pe_saved[idx_pe] is not None:
                ep.insert(0, str(pe_saved[idx_pe]))
            pe_entries.append(ep)

        # --- RIGA 6: CONVENZIONI DI CALCOLO (confine PE e modalita correzioni) ---
        row6 = ctk.CTkFrame(body, fg_color="transparent"); row6.pack(fill="x", pady=(2, 2))
        PE_CONF_LBL = {"alto": "PE superiore", "basso": "PE inferiore"}
        CORR_MOD_LBL = {"prima": "Solo la prima regola valida", "somma": "Somma tutte le regole valide"}
        ctk.CTkLabel(row6, text="Se punteggio = soglia PE →", anchor="w", font=ctk.CTkFont(size=11)).pack(side="left")
        v_peconf = ctk.StringVar(value=PE_CONF_LBL.get((dati or {}).get('pe_confine', 'alto'), "PE superiore"))
        ctk.CTkOptionMenu(row6, values=list(PE_CONF_LBL.values()), variable=v_peconf, width=130).pack(side="left", padx=(4, 18))
        ctk.CTkLabel(row6, text="Correzioni:", anchor="w", font=ctk.CTkFont(size=11)).pack(side="left")
        v_cormod = ctk.StringVar(value=CORR_MOD_LBL.get((dati or {}).get('correzioni_modalita', 'prima'), CORR_MOD_LBL["prima"]))
        ctk.CTkOptionMenu(row6, values=list(CORR_MOD_LBL.values()), variable=v_cormod, width=210).pack(side="left", padx=4)

        # --- RIGA 7: SET DI SOGLIE PE PER SOTTOGRUPPO (es. età × scolarità) ---
        frame_peset = ctk.CTkFrame(body, fg_color="transparent"); frame_peset.pack(fill="x", pady=(6, 2))
        head_peset = ctk.CTkFrame(frame_peset, fg_color="transparent"); head_peset.pack(fill="x")
        ctk.CTkLabel(head_peset, text="Soglie PE per sottogruppo (opzionale)", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold"), text_color=("#16A085", "#1ABC9C")).pack(side="left")
        ctk.CTkLabel(head_peset, text="  vale il primo set con condizioni vere; altrimenti le soglie generali sopra",
                     text_color="gray", font=ctk.CTkFont(size=11)).pack(side="left")
        box_peset = ctk.CTkFrame(frame_peset, fg_color="transparent"); box_peset.pack(fill="x")
        pe_set_rows = []

        def _add_pe_set(condizioni=None, soglie=None, etichetta=""):
            fr = ctk.CTkFrame(box_peset, border_width=1, border_color="#c8c8c8")
            fr.pack(fill="x", pady=2)
            ctk.CTkLabel(fr, text="SE", font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=(8, 2))
            cb = EditorCondizioni(fr, self._vars_anagrafica, condizioni or [])
            cb.frame.pack(side="left", padx=4, pady=4)
            dx = ctk.CTkFrame(fr, fg_color="transparent"); dx.pack(side="left", padx=(10, 4))
            r1 = ctk.CTkFrame(dx, fg_color="transparent"); r1.pack(anchor="w")
            ents = []
            for i, lbl_s in enumerate(["➔ PE 0→1:", "1→2:", "2→3:", "3→4:"]):
                ctk.CTkLabel(r1, text=lbl_s, font=ctk.CTkFont(size=11)).pack(side="left", padx=(6, 2))
                ep_s = ctk.CTkEntry(r1, width=58)
                ep_s.pack(side="left", padx=2)
                if soglie and i < len(soglie) and soglie[i] is not None:
                    ep_s.insert(0, str(soglie[i]))
                ents.append(ep_s)
            r2 = ctk.CTkFrame(dx, fg_color="transparent"); r2.pack(anchor="w", pady=(3, 0))
            ctk.CTkLabel(r2, text="Etichetta:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(6, 2))
            e_lbl = ctk.CTkEntry(r2, width=190, placeholder_text="es. 60-69 anni, 5-8 anni di studio")
            e_lbl.pack(side="left", padx=2)
            if etichetta:
                e_lbl.insert(0, etichetta)
            riga_set = {'frame': fr, 'cond': cb, 'soglie': ents, 'etichetta': e_lbl}
            ctk.CTkButton(fr, text="✕", width=28, fg_color="#E74C3C", hover_color="#C0392B",
                          command=lambda rs=riga_set: (rs['frame'].destroy(),
                                                       pe_set_rows.remove(rs) if rs in pe_set_rows else None)
                          ).pack(side="right", padx=6)
            pe_set_rows.append(riga_set)

        ctk.CTkButton(head_peset, text="➕ Set di soglie", width=110, height=24,
                      command=lambda: _add_pe_set()).pack(side="right")
        for st in ((dati or {}).get('pe_set', []) or []):
            _add_pe_set(st.get('condizioni', []), st.get('soglie', []), st.get('etichetta', ''))

        self.dim_ui.append({
            'card': card, 'is_formula': is_formula, 'e_id': e_id, 'e_nome': e_nome,
            'e_sez': e_sez, 'e_items': e_items, 'e_scoring': e_scoring, 'e_reverse': e_reverse,
            'e_formula': e_formula, 'e_tgraf': e_tgraf, 'v_co': v_co, 'e_media': e_media, 'e_ds': e_ds,
            'pe_entries': pe_entries, 'v_peconf': v_peconf, 'v_cormod': v_cormod,
            'pe_set_rows': pe_set_rows
        })

    def _apri_builder(self, target_entry):
        ids_standard = []
        for d in self.dim_ui:
            if not d['is_formula']:
                uid = d['e_id'].get().strip()
                if uid: ids_standard.append(uid)

        if not ids_standard:
            messagebox.showwarning("Informazione", "Crea e assegna un ID ad almeno una dimensione standard nella Tab 3 prima di comporre formule.")
            return

        FormulaBuilderWindow(self, target_entry, ids_standard)

    def _rimuovi_card(self, card, lista):
        for i, d in enumerate(lista):
            if d['card'] == card:
                lista.pop(i); card.destroy(); break

    def _build_tab_cutoff(self):
        self.cutoff_ui = {}
        fc = ctk.CTkFrame(self.tab_cutoff, fg_color="transparent")
        fc.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(fc, text="Soglie di Rischio Clinico (Cut-off)", font=ctk.CTkFont(weight="bold", size=14)).pack(side="left")
        ctk.CTkButton(fc, text="🔄 Sincronizza Dimensioni", command=self._aggiorna_tab_cutoff).pack(side="right")
        self.scroll_cutoff = ctk.CTkScrollableFrame(self.tab_cutoff)
        self.scroll_cutoff.pack(fill="both", expand=True, pady=5)

    def _aggiorna_tab_cutoff(self):
        current_state = {}
        for did, info in self.cutoff_ui.items():
            if info.get('rows'):
                saved_rows = []
                for r in info['rows']:
                    try:
                        c_var = r['cond_var'].get()
                        cond_str = ""
                        if c_var != "Nessuna":
                            c_val = r['cond_val'].get().strip()
                            # Traduce i simboli belli (UI) in simboli macchina (Python)
                            op_map = {"=": "==", "≠": "!=", ">": ">", "<": "<", "≥": ">=", "≤": "<="}
                            py_op = op_map.get(r['cond_op'].get(), "==")

                            if not c_val.replace('.', '', 1).isdigit():
                                cond_str = f"{c_var} {py_op} '{c_val}'"
                            else:
                                cond_str = f"{c_var} {py_op} {c_val}"

                        saved_rows.append({
                            'da': r['da'].get(), 'a': r['a'].get(), 'etichetta': r['etichetta'].get(),
                            'colore': r['colore'].get(), 'descrizione_estesa': r['descrizione_estesa'].get(),
                            'condizione': cond_str
                        })
                    except Exception:
                        pass
                current_state[did] = saved_rows
            else:
                current_state[did] = info.get('_raw', [])

        for w in self.scroll_cutoff.winfo_children(): w.destroy()
        self.cutoff_ui = {}

        anag_testo = self.entry_anagrafica.get()
        anag_vars = [re.sub(r'\[.*?\]', '', x).strip() for x in anag_testo.split(",") if x.strip()]
        opzioni_var = ["Nessuna"] + anag_vars

        for d in self.dim_ui:
            dim_id = d['e_id'].get().strip()
            dim_nome = d['e_nome'].get().strip()
            if not dim_id: continue

            frame_dim = ctk.CTkFrame(self.scroll_cutoff, corner_radius=8, border_width=1, border_color="gray")
            frame_dim.pack(fill="x", padx=5, pady=6)
            head = ctk.CTkFrame(frame_dim, fg_color="#2C3E50", corner_radius=6)
            head.pack(fill="x", padx=4, pady=(4, 0))
            ctk.CTkLabel(head, text=f"Fasce Cliniche: {dim_nome} [{dim_id}]", text_color="white",
                         font=ctk.CTkFont(weight="bold")).pack(side="left", padx=8, pady=4)

            rows_cutoff = []
            scroll_co = ctk.CTkScrollableFrame(frame_dim, height=180)
            scroll_co.pack(fill="x", padx=8, pady=4)

            def _remove_co_row(container, r_list, r_dict):
                container.destroy()
                if r_dict in r_list: r_list.remove(r_dict)

            def _add_co_row(parent, rows, da="", a="", etichetta="", colore="green", descrizione="", condizione=""):
                riga_container = ctk.CTkFrame(parent, border_width=1, border_color="#e0e0e0")
                riga_container.pack(fill="x", pady=4, padx=2)

                riga1 = ctk.CTkFrame(riga_container, fg_color="transparent")
                riga1.pack(fill="x", pady=2, padx=4)
                ctk.CTkLabel(riga1, text="Da:", width=25).pack(side="left")
                e_da = ctk.CTkEntry(riga1, width=50);
                e_da.pack(side="left", padx=2);
                e_da.insert(0, str(da))
                ctk.CTkLabel(riga1, text="A:", width=20).pack(side="left")
                e_a = ctk.CTkEntry(riga1, width=50);
                e_a.pack(side="left", padx=2);
                e_a.insert(0, str(a))
                ctk.CTkLabel(riga1, text="Etichetta:", width=60).pack(side="left", padx=(5, 0))
                e_et = ctk.CTkEntry(riga1, width=140);
                e_et.pack(side="left", padx=2);
                e_et.insert(0, etichetta)
                e_col = ctk.CTkOptionMenu(riga1, values=["green", "yellow", "orange", "red", "gray"], width=90)
                e_col.set(colore);
                e_col.pack(side="left", padx=5)

                btn_del = ctk.CTkButton(riga1, text="✕", width=30, fg_color="#E74C3C", hover_color="#C0392B")
                btn_del.pack(side="right", padx=5)

                riga2 = ctk.CTkFrame(riga_container, fg_color="transparent")
                riga2.pack(fill="x", pady=2, padx=4)
                ctk.CTkLabel(riga2, text="Interpretazione:", width=90, text_color="gray").pack(side="left")
                e_desc = ctk.CTkEntry(riga2, placeholder_text="Descrizione estesa facoltativa nel referto PDF...",
                                      width=380)
                e_desc.pack(side="left", fill="x", expand=True, padx=2)
                if descrizione: e_desc.insert(0, descrizione)

                # --- MAPPING INVERSO: DA PYTHON (JSON) A INTERFACCIA VISIVA ---
                match = re.match(r"(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)", condizione)
                c_var = match.group(1).strip() if match else "Nessuna"
                c_op_py = match.group(2).strip() if match else "=="
                c_val = match.group(3).strip().strip("'\"") if match else ""

                py_to_ui = {"==": "=", "!=": "≠", ">": ">", "<": "<", ">=": "≥", "<=": "≤"}
                c_op_ui = py_to_ui.get(c_op_py, "=")

                riga3 = ctk.CTkFrame(riga_container, fg_color="transparent")
                riga3.pack(fill="x", pady=2, padx=4)
                ctk.CTkLabel(riga3, text="Condizione:", width=70, text_color="#E67E22").pack(side="left")

                e_cond_var = ctk.CTkOptionMenu(riga3, values=opzioni_var, width=120)
                if c_var in opzioni_var:
                    e_cond_var.set(c_var)
                else:
                    e_cond_var.set("Nessuna")
                e_cond_var.pack(side="left", padx=2)

                # Mostra solo i simboli puliti
                e_cond_op = ctk.CTkOptionMenu(riga3, values=["=", "≠", ">", "<", "≥", "≤"], width=60)
                e_cond_op.set(c_op_ui)
                e_cond_op.pack(side="left", padx=2)

                e_cond_val = ctk.CTkEntry(riga3, placeholder_text="Valore di Riferimento", width=140)
                e_cond_val.insert(0, c_val)
                e_cond_val.pack(side="left", padx=2)

                row_dict = {'da': e_da, 'a': e_a, 'etichetta': e_et, 'colore': e_col, 'descrizione_estesa': e_desc,
                            'cond_var': e_cond_var, 'cond_op': e_cond_op, 'cond_val': e_cond_val}
                rows.append(row_dict)
                btn_del.configure(command=lambda: _remove_co_row(riga_container, rows, row_dict))

            bf = ctk.CTkFrame(frame_dim, fg_color="transparent")
            bf.pack(anchor="w", padx=8, pady=(0, 6))
            ctk.CTkButton(bf, text="➕ Aggiungi Range Punteggio",
                          command=lambda p=scroll_co, r=rows_cutoff: _add_co_row(p, r), width=160, height=26).pack(
                side="left")

            raw = current_state.get(dim_id, [])
            if raw:
                for rd in raw: _add_co_row(scroll_co, rows_cutoff, da=rd.get('da', ''), a=rd.get('a', ''),
                                           etichetta=rd.get('etichetta', ''), colore=rd.get('colore', 'green'),
                                           descrizione=rd.get('descrizione_estesa', ''),
                                           condizione=rd.get('condizione', ''))
            else:
                _add_co_row(scroll_co, rows_cutoff)

            self.cutoff_ui[dim_id] = {'rows': rows_cutoff, '_raw': raw}

    def carica_test(self):
        sel = self.menu_carica.get()
        if sel == "-- Seleziona --": return
        percorso = self.test_disponibili.get(sel)
        if not percorso: return

        # Reset allegati PDF
        for k in ['protocollo', 'manuale', 'scoring']:
            self.pdf_attachments[k] = None
            self.pdf_labels[k].configure(text="Nessun file", text_color="gray")

        if percorso.endswith('.psyt'):
            with zipfile.ZipFile(percorso, 'r') as z:
                with z.open('test.json') as f: data = json.load(f)
                namelist = z.namelist()
                for k in ['protocollo', 'manuale', 'scoring']:
                    if f"{k}.pdf" in namelist:
                        self.pdf_attachments[k] = f"EXISTING::{percorso}::{k}.pdf"
                        self.pdf_labels[k].configure(text=f"{k}.pdf (Nel pacchetto)", text_color=("#2980B9", "#3498DB"))
        else:
            with open(percorso, 'r', encoding='utf-8') as f: data = json.load(f)

        self.entry_id.delete(0,'end'); self.entry_nome.delete(0,'end'); self.entry_autore.delete(0,'end'); self.entry_categorie.delete(0,'end')
        self.text_istruzioni.delete("1.0","end"); self.entry_anagrafica.delete(0,'end')
        for s in self.sezioni_ui: s['card'].destroy()
        self.sezioni_ui.clear()
        for d in self.dim_ui: d['card'].destroy()
        self.dim_ui.clear()

        info = data.get('info_generali', {})
        self.entry_id.insert(0, info.get('id',''))
        self.entry_nome.insert(0, info.get('nome',''))
        self.entry_autore.insert(0, info.get('autore',''))
        self.entry_categorie.insert(0, ", ".join(info.get('categorie', [])))
        self.text_istruzioni.insert("1.0", info.get('istruzioni',''))
        self.entry_anagrafica.insert(0, ", ".join(data.get('dati_richiesti',{}).get('anagrafica',[])))

        for sez in data.get('sezioni', []): self.aggiungi_sezione(sez['tipo'], dati=sez)
        for dim in data.get('dimensioni', []): self.aggiungi_dimensione(dati=dim)

        self.cutoff_ui = {}
        for dim in data.get('dimensioni', []): self.cutoff_ui[dim['id']] = {'_raw': dim.get('cutoffs', []), 'rows': []}

        self.correzioni_ui = {}
        for dim in data.get('dimensioni', []): self.correzioni_ui[dim['id']] = {'_raw': dim.get('correzioni', []), 'rows': []}

        self._aggiorna_tab_correzioni()
        self._aggiorna_tab_cutoff()
        messagebox.showinfo("Caricato", f"Test '{info.get('nome')}' caricato nell'editor.")

    def salva_test(self):
        test_id = self.entry_id.get().strip()
        if not test_id:
            messagebox.showerror("Errore", "L'ID del test è obbligatorio.")
            return

        sezioni_json = []
        for s in self.sezioni_ui:
            tipo = s['tipo']
            items = []
            for idx_it, ir in enumerate(s['items_ui']):
                txt_it = ir['entry'].get().strip()
                if not txt_it: continue
                it_obj = {"id": len(items) + 1, "testo": txt_it}
                if ir['op_crit'].get() != "No" and ir['val_crit'].get().strip():
                    it_obj['critico'] = {
                        'op': ir['op_crit'].get(),
                        'valore': ir['val_crit'].get().strip(),
                        'nota': ir['nota_crit'].get().strip()
                    }
                items.append(it_obj)

            sez = {"id": s['entry_id'].get().strip(), "titolo": s['entry_titolo'].get().strip(), "tipo": tipo,
                   "items": items}
            if tipo == 'likert':
                try:
                    sez['opzioni_etichette'] = [x.strip() for x in s['entry_etichette'].get().split(",")]
                    sez['opzioni_valori'] = [int(x.strip()) for x in s['entry_valori'].get().split(",")]
                except Exception:
                    messagebox.showerror("Errore", f"Sintassi opzioni non valida nella sezione: {sez['titolo']}")
                    return
            elif tipo == 'numerico' and s.get('entry_max_num'):
                try:
                    sez['max_numerico'] = float(s['entry_max_num'].get().strip().replace(',', '.') or 0)
                except ValueError:
                    sez['max_numerico'] = 0
            sezioni_json.append(sez)

        dimensioni_json = []
        for d in self.dim_ui:
            dim_id = d['e_id'].get().strip()
            is_f = d['is_formula']

            item_ids = []
            rev_ids = []
            formula_str = ""
            t_scoring = d['e_scoring'].get() if not is_f else "formula"

            if not is_f:
                try:
                    item_ids = [int(x.strip()) for x in d['e_items'].get().split(",") if x.strip()]
                    if d['e_reverse'].get().strip():
                        rev_ids = [int(x.strip()) for x in d['e_reverse'].get().split(",") if x.strip()]
                except ValueError:
                    messagebox.showerror("Errore", f"ID item/reverse non validi nella dimensione: {dim_id}")
                    return
            else:
                formula_str = d['e_formula'].get().strip()
                if not formula_str:
                    messagebox.showerror("Errore",
                                         f"La formula non può essere vuota per il calcolo composito: {dim_id}")
                    return

            cutoffs = []
            co_data = self.cutoff_ui.get(dim_id, {})
            rows = co_data.get('rows', [])

            if not rows and co_data.get('_raw'):
                cutoffs = co_data['_raw']
            else:
                for row in rows:
                    da_val = row['da'].get().strip().replace(',', '.')
                    a_val = row['a'].get().strip().replace(',', '.')
                    if not da_val or not a_val: continue
                    try:
                        da_num = float(da_val)
                        a_num = float(a_val)

                        c_var = row['cond_var'].get()
                        cond_str = ""
                        if c_var != "Nessuna":
                            c_val = row['cond_val'].get().strip()

                            op_map = {"=": "==", "≠": "!=", ">": ">", "<": "<", "≥": ">=", "≤": "<="}
                            py_op = op_map.get(row['cond_op'].get(), "==")

                            if not c_val.replace('.', '', 1).isdigit():
                                cond_str = f"{c_var} {py_op} '{c_val}'"
                            else:
                                cond_str = f"{c_var} {py_op} {c_val}"

                        cutoffs.append({
                            'etichetta': row['etichetta'].get().strip(),
                            'da': int(da_num) if da_num.is_integer() else da_num,
                            'a': int(a_num) if a_num.is_integer() else a_num,
                            'colore': row['colore'].get(),
                            'descrizione_estesa': row['descrizione_estesa'].get().strip(),
                            'condizione': cond_str
                        })
                    except ValueError:
                        pass

            norma = {}
            try:
                if d['e_media'].get().strip(): norma['media'] = float(d['e_media'].get().strip().replace(',', '.'))
                if d['e_ds'].get().strip(): norma['ds'] = float(d['e_ds'].get().strip().replace(',', '.'))
            except ValueError:
                messagebox.showerror("Errore", f"Valori di norma (media/DS) non numerici in: {dim_id}")
                return

            pe_soglie = []
            pe_vals_raw = [ep.get().strip().replace(',', '.') for ep in d.get('pe_entries', [])]
            if any(pe_vals_raw):
                if not all(pe_vals_raw):
                    messagebox.showerror("Errore",
                                         f"Inserisci tutte e 4 le soglie dei Punteggi Equivalenti (oppure lasciale tutte vuote) in: {dim_id}")
                    return
                try:
                    pe_soglie = [float(x) for x in pe_vals_raw]
                except ValueError:
                    messagebox.showerror("Errore", f"Soglie dei Punteggi Equivalenti non numeriche in: {dim_id}")
                    return
                ok_pe, msg_pe = TestEngine.valida_soglie_pe(pe_soglie)
                if not ok_pe:
                    messagebox.showerror("Errore", f"Soglie PE non valide in {dim_id}: {msg_pe}.")
                    return


            # --- SALVATAGGIO SET DI SOGLIE PE PER SOTTOGRUPPO ---
            pe_set = []
            for rs in d.get('pe_set_rows', []):
                try:
                    conds_pe = rs['cond'].condizioni_stringhe(strict=True)
                except ValueError as ex:
                    messagebox.showerror("Errore", f"Set di soglie PE in {dim_id}: {ex}.")
                    return
                raw_sg = [ep_s.get().strip().replace(',', '.') for ep_s in rs['soglie']]
                if not all(raw_sg):
                    messagebox.showerror("Errore", f"Set di soglie PE incompleto in {dim_id}: servono tutte e 4 le soglie.")
                    return
                try:
                    sg = [float(x) for x in raw_sg]
                except ValueError:
                    messagebox.showerror("Errore", f"Soglie PE non numeriche in un set di {dim_id}.")
                    return
                ok_sg, msg_sg = TestEngine.valida_soglie_pe(sg)
                if not ok_sg:
                    messagebox.showerror("Errore", f"Set di soglie PE non valido in {dim_id}: {msg_sg}.")
                    return
                voce_pe = {'condizioni': conds_pe, 'soglie': sg}
                lbl_pe = rs['etichetta'].get().strip()
                if lbl_pe:
                    voce_pe['etichetta'] = lbl_pe
                pe_set.append(voce_pe)

            # --- SALVATAGGIO CORREZIONI ---
            correzioni = []
            co_corr = self.correzioni_ui.get(dim_id, {})
            rows_c = co_corr.get('rows', [])

            if not rows_c and co_corr.get('_raw'):
                correzioni = co_corr['_raw']
            else:
                for r in rows_c:
                    c_valore = r['valore'].get().strip().replace(',', '.')
                    if not c_valore: continue
                    try:
                        condizioni = r['cond'].condizioni_stringhe(strict=True)
                    except ValueError as ex:
                        messagebox.showerror("Errore", f"Correzione in {dim_id}: {ex}.")
                        return
                    try:
                        correzioni.append({'condizioni': condizioni, 'valore': float(c_valore)})
                    except ValueError:
                        pass

            dim_payload = {
                'id': dim_id, 'nome': d['e_nome'].get().strip(), 'tipo_scoring': t_scoring,
                'tipo_grafico': d['e_tgraf'].get(), 'mostra_cutoff': d['v_co'].get(), 'norma': norma,
                'pe_soglie': pe_soglie, 'pe_set': pe_set, 'cutoffs': cutoffs, 'correzioni': correzioni,
                'pe_confine': 'basso' if d['v_peconf'].get() == "PE inferiore" else 'alto',
                'correzioni_modalita': 'somma' if d['v_cormod'].get().startswith("Somma") else 'prima'
            }
            if not is_f:
                dim_payload.update(
                    {'sezione_id': d['e_sez'].get().strip(), 'item_ids': item_ids, 'item_ids_reverse': rev_ids})
            else:
                dim_payload.update({'formula': formula_str})

            dimensioni_json.append(dim_payload)

        nuovo_test = {
            "info_generali": {
                "id": test_id,
                "nome": self.entry_nome.get().strip(),
                "autore": self.entry_autore.get().strip(),
                "categorie": [x.strip() for x in self.entry_categorie.get().split(",") if x.strip()],
                "istruzioni": self.text_istruzioni.get("1.0", "end-1c").strip()
            },
            "dati_richiesti": {"anagrafica": [x.strip() for x in self.entry_anagrafica.get().split(",")]},
            "sezioni": sezioni_json, "dimensioni": dimensioni_json
        }

        ha_pdf = any(v is not None for v in self.pdf_attachments.values())
        path_psyt = os.path.join(self.db_folder, f"{test_id}.psyt")
        path_json = os.path.join(self.db_folder, f"{test_id}.json")

        # Se ci sono PDF allegati, salviamo come pacchetto .psyt
        if ha_pdf:
            if os.path.exists(path_psyt) or os.path.exists(path_json):
                risposta = messagebox.askyesnocancel("File esistente",
                                                     "Vuoi creare una copia di backup della versione precedente?")
                if risposta is None: return
                if risposta:
                    if os.path.exists(path_psyt):
                        old = os.path.join(self.db_folder, f"{test_id}_old.psyt")
                        if os.path.exists(old): os.remove(old)
                        shutil.copy2(path_psyt, old)
                    elif os.path.exists(path_json):
                        old = os.path.join(self.db_folder, f"{test_id}_old.json")
                        if os.path.exists(old): os.remove(old)
                        shutil.copy2(path_json, old)

            # Estrae in memoria eventuali PDF già presenti prima di sovrascrivere lo zip
            existing_bytes = {}
            for k, val in self.pdf_attachments.items():
                if val and val.startswith("EXISTING::"):
                    _, src_zip, internal_name = val.split("::")
                    with zipfile.ZipFile(src_zip, 'r') as z_in:
                        existing_bytes[k] = z_in.read(internal_name)

            with zipfile.ZipFile(path_psyt, 'w', zipfile.ZIP_DEFLATED) as z_out:
                z_out.writestr('test.json', json.dumps(nuovo_test, indent=4, ensure_ascii=False))
                for k, val in self.pdf_attachments.items():
                    if not val: continue
                    if k in existing_bytes:
                        z_out.writestr(f"{k}.pdf", existing_bytes[k])
                    elif os.path.exists(val):
                        z_out.write(val, f"{k}.pdf")

            # Se prima era un .json singolo, lo rimuove per evitare duplicati in libreria
            if os.path.exists(path_json):
                os.remove(path_json)

            messagebox.showinfo("Salvato",
                                f"Pacchetto Test '{nuovo_test['info_generali']['nome']}' (.psyt) archiviato con successo.")
        else:
            if os.path.exists(path_json) or os.path.exists(path_psyt):
                risposta = messagebox.askyesnocancel("File esistente",
                                                     "Vuoi creare una copia di backup della versione precedente?")
                if risposta is None: return
                if risposta:
                    if os.path.exists(path_json):
                        old = os.path.join(self.db_folder, f"{test_id}_old.json")
                        if os.path.exists(old): os.remove(old)
                        os.rename(path_json, old)
                    if os.path.exists(path_psyt):
                        old = os.path.join(self.db_folder, f"{test_id}_old.psyt")
                        if os.path.exists(old): os.remove(old)
                        os.rename(path_psyt, old)

            with open(path_json, 'w', encoding='utf-8') as f:
                json.dump(nuovo_test, f, indent=4, ensure_ascii=False)
            if os.path.exists(path_psyt):
                os.remove(path_psyt)

            messagebox.showinfo("Salvato",
                                f"Test '{nuovo_test['info_generali']['nome']}' (.json) archiviato con successo.")

        self.destroy()
        self.master.mostra_libreria()


# ─────────────────────────────────────────────
#  APPLICAZIONE PRINCIPALE INTERFACCIA
# ─────────────────────────────────────────────

class PsychoScorerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        ctk.set_appearance_mode(self.config.get("tema", "System"))

        # --- APPLICAZIONE ZOOM UI ---
        zoom_str = self.config.get("zoom_ui", "100%")
        try:
            zoom_factor = float(zoom_str.replace('%', '')) / 100.0
        except ValueError:
            zoom_factor = 1.0
        ctk.set_widget_scaling(zoom_factor)
        ctk.set_window_scaling(zoom_factor)
        # ----------------------------

        self.title("PsychoScorer 4")
        ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icona.ico")
        if os.path.exists(ico):
            self.iconbitmap(ico)
        self.geometry("1150x800")
        self.db_folder = os.path.join(BASE_DIR, "Database_Test")

        self.schermata_corrente = None
        self.categoria_attiva = "Tutti i Test"
        self.test_data = {}
        self.categorie_disponibili = []

        self.mostra_libreria()

        # Se il programma viene aperto facendo doppio clic su un file .psyt / .psyp
        args = [a for a in sys.argv[1:] if a.lower().endswith(('.psyt', '.psyp', '.json')) and os.path.exists(a)]
        if args:
            self.after(200, lambda: self.importa_files_da_percorsi(args))

    def _scansiona_database(self):
        self.config = load_config()
        tag_custom = self.config.get("tag_personalizzati", {})
        self.test_data = {}
        tutte_categorie = set()

        if not os.path.exists(self.db_folder): os.makedirs(self.db_folder)
        for fn in os.listdir(self.db_folder):
            if (fn.endswith(".json") or fn.endswith(".psyt")) and not fn.endswith("_old.json") and not fn.endswith("_old.psyt"):
                fp = os.path.join(self.db_folder, fn)
                try:
                    pdfs_presenti = []
                    is_psyt = fn.endswith(".psyt")
                    if is_psyt:
                        with zipfile.ZipFile(fp, 'r') as z:
                            with z.open('test.json') as f:
                                data = json.load(f)
                            namelist = z.namelist()
                            for k in ['protocollo', 'manuale', 'scoring']:
                                if f"{k}.pdf" in namelist:
                                    pdfs_presenti.append(k)
                    else:
                        with open(fp, 'r', encoding='utf-8') as f:
                            data = json.load(f)

                    info = data.get('info_generali', {})
                    base_id = os.path.splitext(fn)[0]
                    test_id = info.get('id', base_id)

                    native_tags = info.get('categorie', [])
                    tags = tag_custom[test_id] if tag_custom.get(test_id) else native_tags

                    self.test_data[test_id] = {
                        'filepath': fp,
                        'nome': info.get('nome', fn),
                        'autore': info.get('autore', ''),
                        'tags': tags,
                        'native_tags': native_tags,
                        'is_psyt': is_psyt,
                        'pdfs': pdfs_presenti
                    }
                    for t in tags: tutte_categorie.add(t)
                except Exception as e:
                    print(f"Errore caricamento {fn}: {e}")

        self.categorie_disponibili = sorted(list(tutte_categorie))

    def pulisci_schermata(self):
        if self.schermata_corrente: self.schermata_corrente.destroy()
        self.schermata_corrente = ctk.CTkFrame(self, fg_color="transparent")
        self.schermata_corrente.pack(fill="both", expand=True)

    def _crea_btn_categoria(self, parent, nome_cat):
        colore = "#2C3E50" if self.categoria_attiva == nome_cat else "transparent"
        text_col = "white" if self.categoria_attiva == nome_cat else ("gray10", "gray90")
        btn = ctk.CTkButton(parent, text=nome_cat, fg_color=colore, text_color=text_col, anchor="w",
                            hover_color="#34495E", height=36, font=ctk.CTkFont(size=13),
                            command=lambda c=nome_cat: self._cambia_categoria(c))
        btn.pack(fill="x", pady=2, padx=10)

    def _cambia_categoria(self, nuova_cat):
        self.categoria_attiva = nuova_cat
        self.mostra_libreria()

    def apri_gestione_tag(self, test_id):
        dati = self.test_data[test_id]

        win = ctk.CTkToplevel(self)
        win.title(f"Organizza: {dati['nome']}")
        win.geometry("520x330")
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="Categorie Personalizzate", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(25, 5))
        ctk.CTkLabel(win,
                     text="Adatta l'organizzazione di questo test al tuo ambulatorio.\nPiù categorie separate da virgola (es: Memoria, Screening).",
                     text_color="gray").pack(pady=(0, 15))

        e_tags = ctk.CTkEntry(win, width=420, height=45, font=ctk.CTkFont(size=14))
        e_tags.pack(pady=10)

        tag_attuali = dati['tags']
        if not tag_attuali and dati['native_tags']: tag_attuali = dati['native_tags']
        e_tags.insert(0, ", ".join(tag_attuali))

        def _salva_tag_locali():
            nuovi_tag = [x.strip() for x in e_tags.get().split(",") if x.strip()]
            self.config = load_config()
            if "tag_personalizzati" not in self.config:
                self.config["tag_personalizzati"] = {}
            self.config["tag_personalizzati"][test_id] = nuovi_tag
            save_config(self.config)
            win.destroy()
            self.mostra_libreria()

        ctk.CTkButton(win, text="💾 Salva Organizzazione", height=42, font=ctk.CTkFont(weight="bold"),
                      fg_color="#2980B9", command=_salva_tag_locali).pack(pady=20)

        if dati['native_tags']:
            lbl_nat = f"Tag originali predefiniti dall'autore: {', '.join(dati['native_tags'])}"
            ctk.CTkLabel(win, text=lbl_nat, text_color="gray", font=ctk.CTkFont(size=10)).pack()

    def apri_editor(self):
        TestEditorWindow(self, self.db_folder)

    def apri_impostazioni(self):
        ImpostazioniWindow(self)



    def mostra_libreria(self):
        self.pulisci_schermata()
        self._scansiona_database()

        self.schermata_corrente.grid_rowconfigure(0, weight=1)
        self.schermata_corrente.grid_columnconfigure(1, weight=1)

        # === 1. BARRA LATERALE ===
        sidebar = ctk.CTkFrame(self.schermata_corrente, width=240, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(sidebar, text="PsychoScorer", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(25, 5), padx=20, anchor="w")
        ctk.CTkLabel(sidebar, text="Libreria Test", font=ctk.CTkFont(size=13), text_color="gray").pack(pady=(0, 20), padx=20, anchor="w")

        self._crea_btn_categoria(sidebar, "Tutti i Test")
        self._crea_btn_categoria(sidebar, "Senza Categoria")

        ctk.CTkFrame(sidebar, height=1, fg_color="gray").pack(fill="x", padx=20, pady=15)
        ctk.CTkLabel(sidebar, text="I TUOI TAG", font=ctk.CTkFont(size=11, weight="bold"), text_color="gray").pack(padx=20, anchor="w", pady=(0, 5))

        scroll_cat = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        scroll_cat.pack(fill="both", expand=True, padx=10, pady=5)
        for cat in self.categorie_disponibili:
            self._crea_btn_categoria(scroll_cat, cat)

        # === 2. AREA CENTRALE ===
        main_area = ctk.CTkFrame(self.schermata_corrente, fg_color="transparent")
        main_area.grid(row=0, column=1, sticky="nsew")
        main_area.grid_rowconfigure(1, weight=1)
        main_area.grid_columnconfigure(0, weight=1)

        topbar = ctk.CTkFrame(main_area, fg_color="transparent")
        topbar.grid(row=0, column=0, sticky="ew", padx=30, pady=(25, 10))

        self.entry_ricerca = ctk.CTkEntry(topbar, placeholder_text="🔍 Cerca per nome o autore...", width=320, height=40)
        self.entry_ricerca.pack(side="left")
        self.entry_ricerca.bind("<KeyRelease>", lambda e: self._aggiorna_vetrina())

        ctk.CTkButton(topbar, text="📤 Esporta", command=self.apri_esporta, width=90, height=40, fg_color="#16A085", hover_color="#117A65").pack(side="right", padx=4)
        ctk.CTkButton(topbar, text="📥 Importa", command=self.importa_json, width=90, height=40, fg_color="#2980B9", hover_color="#21618C").pack(side="right", padx=4)
        ctk.CTkButton(topbar, text="🛠 Editor", command=self.apri_editor, width=90, height=40, fg_color="#8E44AD", hover_color="#732D91").pack(side="right", padx=4)
        ctk.CTkButton(topbar, text="⚙️ Setup", command=self.apri_impostazioni, width=90, height=40, fg_color="transparent", border_width=1, text_color=("gray10", "gray90")).pack(side="right", padx=4)

        self.scroll_vetrina = ctk.CTkScrollableFrame(main_area, fg_color="transparent")
        self.scroll_vetrina.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)

        self._aggiorna_vetrina()

    def _aggiorna_vetrina(self):
        for w in self.scroll_vetrina.winfo_children():
            w.destroy()

        testo_ricerca = self.entry_ricerca.get().lower().strip()
        test_mostrati = 0

        for t_id, t_dati in self.test_data.items():
            tags = t_dati['tags']
            if self.categoria_attiva == "Senza Categoria" and len(tags) > 0: continue
            if self.categoria_attiva != "Tutti i Test" and self.categoria_attiva != "Senza Categoria" and self.categoria_attiva not in tags: continue
            if testo_ricerca and (testo_ricerca not in t_dati['nome'].lower() and testo_ricerca not in t_dati['autore'].lower()): continue

            test_mostrati += 1

            card = ctk.CTkFrame(self.scroll_vetrina, corner_radius=10, fg_color=("gray90", "gray16"))
            card.pack(fill="x", pady=8, padx=10)
            card.grid_columnconfigure(0, weight=1)

            # Riga 0: Titolo
            ctk.CTkLabel(
                card, text=t_dati['nome'],
                font=ctk.CTkFont(size=17, weight="bold"), anchor="w"
            ).grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 2))

            # Riga 1: Autore (se presente)
            if t_dati['autore']:
                ctk.CTkLabel(
                    card, text=t_dati['autore'],
                    font=ctk.CTkFont(size=12), text_color="gray", anchor="w"
                ).grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 4))

            # Riga 2: Tag (separati in una riga dedicata della griglia)
            pdfs = t_dati.get('pdfs', [])
            if tags:
                tag_frame = ctk.CTkFrame(card, fg_color="transparent", height=28)
                tag_frame.grid(row=2, column=0, sticky="w", padx=20, pady=(4, 4 if pdfs else 14))
                colori_salvati = self.config.get("colori_tag", {})
                for idx_t, tg in enumerate(tags):
                    bg_color = colori_salvati.get(tg, "#16A085")
                    ctk.CTkLabel(
                        tag_frame, text=f"  {tg}  ", fg_color=bg_color, text_color="white",
                        corner_radius=6, height=24, font=ctk.CTkFont(size=11, weight="bold")
                    ).grid(row=0, column=idx_t, padx=(0, 6), pady=2)

            # Riga 3: Barra Documenti PDF Allegati (.psyt)
            if pdfs:
                doc_frame = ctk.CTkFrame(card, fg_color="transparent", height=32)
                doc_frame.grid(row=3, column=0, sticky="w", padx=20, pady=(4, 14))
                labels_doc = {
                    'protocollo': '📄 Protocollo',
                    'manuale':    '📘 Manuale',
                    'scoring':    '📊 Scoring'
                }
                for idx_d, doc_key in enumerate(pdfs):
                    ctk.CTkButton(
                        doc_frame, text=labels_doc.get(doc_key, doc_key), height=26, width=105,
                        font=ctk.CTkFont(size=11, weight="bold"), fg_color=("#D5D8DC", "#2C3E50"),
                        text_color=("gray10", "white"), hover_color=("#ABB2B9", "#34495E"),
                        command=lambda fp=t_dati['filepath'], dk=doc_key: self._apri_pdf_allegato(fp, dk)
                    ).grid(row=0, column=idx_d, padx=(0, 6), pady=2)

            # Se non ci sono né tag né pdf, aggiungiamo un piccolo margine inferiore
            if not tags and not pdfs:
                ctk.CTkFrame(card, fg_color="transparent", height=10).grid(row=2, column=0)

            # Colonna 1 (Destra): Pulsanti Azione centrati verticalmente
            btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            btn_frame.grid(row=0, column=1, rowspan=4, sticky="e", padx=20, pady=15)

            ctk.CTkButton(
                btn_frame, text="🏷️ Organizza", width=100, height=38, fg_color="transparent", border_width=1,
                text_color=("gray10", "gray90"), hover_color=("gray80", "gray25"),
                command=lambda i=t_id: self.apri_gestione_tag(i)
            ).pack(side="left", padx=6)

            ctk.CTkButton(
                btn_frame, text="▶ Somministra", width=130, height=38, font=ctk.CTkFont(weight="bold"),
                fg_color="#27AE60", hover_color="#1E8449",
                command=lambda fp=t_dati['filepath']: self.avvia_test(fp)
            ).pack(side="left", padx=6)

        if test_mostrati == 0:
            ctk.CTkLabel(
                self.scroll_vetrina, text="Nessun test trovato con questi filtri.",
                text_color="gray", font=ctk.CTkFont(size=15)
            ).pack(pady=60)

    def _apri_pdf_allegato(self, psyt_path, doc_key):
        try:
            with zipfile.ZipFile(psyt_path, 'r') as z:
                pdf_bytes = z.read(f"{doc_key}.pdf")
            tmp = tempfile.NamedTemporaryFile(suffix=f"_{doc_key}.pdf", delete=False)
            tmp.write(pdf_bytes)
            tmp.close()
            if sys.platform.startswith('win'):
                os.startfile(tmp.name)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', tmp.name])
            else:
                subprocess.Popen(['xdg-open', tmp.name])
        except Exception as e:
            messagebox.showerror("Errore apertura PDF", f"Impossibile aprire il documento allegato:\n{e}")

    def apri_esporta(self):
        if not self.test_data:
            messagebox.showinfo("Libreria Vuota", "Non ci sono test nel database da esportare.")
            return
        EsportaWindow(self, self.test_data)

    def importa_json(self):
        files = filedialog.askopenfilenames(
            title="Importa Test o Pacchetti (.psyt, .psyp, .json)",
            filetypes=[("Tutti i formati supportati", "*.psyt;*.psyp;*.json"),
                       ("Test Singolo PsychoScorer", "*.psyt"),
                       ("Pacchetto Multi-Test PsychoScorer", "*.psyp"),
                       ("Modello JSON", "*.json")]
        )
        if files:
            self.importa_files_da_percorsi(files)

    def importa_files_da_percorsi(self, files):
        importati, errori = [], []
        for src in files:
            if not os.path.exists(src): continue
            fn = os.path.basename(src)
            ext = os.path.splitext(fn)[1].lower()
            try:
                if ext == '.json':
                    with open(src, 'r', encoding='utf-8') as f: data = json.load(f)
                    if 'info_generali' not in data:
                        errori.append(f"{fn}: campo 'info_generali' mancante"); continue
                    test_id = data.get('info_generali', {}).get('id', os.path.splitext(fn)[0])
                    dest = os.path.join(self.db_folder, f"{test_id}.json")
                    if os.path.exists(dest) and os.path.abspath(src) != os.path.abspath(dest):
                        if not messagebox.askyesno("File esistente", f"Il test '{data['info_generali'].get('nome', test_id)}' è già presente.\nSovrascriverlo?"): continue
                    if os.path.abspath(src) != os.path.abspath(dest):
                        shutil.copy2(src, dest)
                    importati.append(f"{data['info_generali'].get('nome', test_id)} (.json)")

                elif ext == '.psyt':
                    with zipfile.ZipFile(src, 'r') as z:
                        with z.open('test.json') as f: data = json.load(f)
                    test_id = data.get('info_generali', {}).get('id', os.path.splitext(fn)[0])
                    dest = os.path.join(self.db_folder, f"{test_id}.psyt")
                    if os.path.exists(dest) and os.path.abspath(src) != os.path.abspath(dest):
                        if not messagebox.askyesno("File esistente", f"Il test '{data['info_generali'].get('nome', test_id)}' è già presente.\nSovrascriverlo?"): continue
                    if os.path.abspath(src) != os.path.abspath(dest):
                        shutil.copy2(src, dest)
                    importati.append(f"{data['info_generali'].get('nome', test_id)} (.psyt)")

                elif ext == '.psyp':
                    with zipfile.ZipFile(src, 'r') as z_pack:
                        for member in z_pack.namelist():
                            if member.endswith('.psyt'):
                                raw_bytes = z_pack.read(member)
                                tmp_psyt = tempfile.NamedTemporaryFile(suffix='.psyt', delete=False)
                                tmp_psyt.write(raw_bytes)
                                tmp_psyt.close()
                                try:
                                    with zipfile.ZipFile(tmp_psyt.name, 'r') as z_inner:
                                        with z_inner.open('test.json') as f: data = json.load(f)
                                    test_id = data.get('info_generali', {}).get('id', os.path.splitext(os.path.basename(member))[0])
                                    dest = os.path.join(self.db_folder, f"{test_id}.psyt")
                                    shutil.copy2(tmp_psyt.name, dest)
                                    importati.append(f"{data['info_generali'].get('nome', test_id)} (da .psyp)")
                                finally:
                                    os.remove(tmp_psyt.name)
            except Exception as e:
                errori.append(f"{fn}: {e}")

        msg = ""
        if importati: msg += f"✅ Importati ({len(importati)}):\n" + "\n".join(f"  • {n}" for n in importati)
        if errori:    msg += f"\n\n⚠️ Errori ({len(errori)}):\n" + "\n".join(f"  • {e}" for e in errori)
        if msg: messagebox.showinfo("Importazione completata", msg.strip())
        self.mostra_libreria()

    def avvia_test(self, percorso_file):
        self.engine = TestEngine(percorso_file)
        self.title(f"PsychoScorer 4 — Somministrazione: {self.engine.nome}")
        self.mostra_interfaccia_test()

    def mostra_interfaccia_test(self):
        self.pulisci_schermata()
        self.var_risposte_per_sezione = {}

        # Lista invisibile per gestire l'Auto-Avanzamento e il focus
        self.lista_focus_entry = []
        index_entry = 0

        header = ctk.CTkFrame(self.schermata_corrente, fg_color="transparent")
        header.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(header, text="← Annulla ed Esci", width=120, command=self.mostra_libreria).pack(side="left", padx=20)
        ctk.CTkLabel(header, text=self.engine.nome, font=ctk.CTkFont(size=20, weight="bold")).pack(side="left")

        # Box delle istruzioni rimosso: il professionista consulta il protocollo PDF allegato.

        scroll = ctk.CTkScrollableFrame(self.schermata_corrente)
        scroll.pack(fill="both", expand=True, padx=10, pady=6)

        # --- ANAGRAFICA ---
        if self.engine.anagrafica:
            ctk.CTkLabel(scroll, text="Dati Identificativi Anagrafica", font=ctk.CTkFont(weight="bold", size=13)).pack(
                anchor="w", padx=10, pady=(6, 4))
            self.var_anagrafica = {}
            f_ana = ctk.CTkFrame(scroll, fg_color="transparent")
            f_ana.pack(fill="x", padx=10)

            opzioni_estratte = {}
            for dim in self.engine.dimensioni:
                for co in dim.get('cutoffs', []):
                    cond = co.get('condizione', '')
                    if cond:
                        matches = re.findall(r"([A-Za-zÀ-ÿ0-9_ ]+?)\s*(?:==|!=)\s*['\"](.*?)['\"]", cond)
                        for var_name, var_value in matches:
                            var_name = var_name.strip()
                            if var_name not in opzioni_estratte: opzioni_estratte[var_name] = set()
                            opzioni_estratte[var_name].add(var_value.strip())

                for corr in dim.get('correzioni', []):
                    for cond in corr.get('condizioni', []):
                        if cond:
                            matches = re.findall(r"([A-Za-zÀ-ÿ0-9_ ]+?)\s*(?:==|!=)\s*['\"](.*?)['\"]", cond)
                            for var_name, var_value in matches:
                                var_name = var_name.strip()
                                if var_name not in opzioni_estratte: opzioni_estratte[var_name] = set()
                                opzioni_estratte[var_name].add(var_value.strip())

            for campo_raw in self.engine.anagrafica:
                match_quadre = re.search(r"(.+?)\[(.*?)\]", campo_raw)
                if match_quadre:
                    campo = match_quadre.group(1).strip()
                    opzioni = [o.strip() for o in match_quadre.group(2).split(",")]
                else:
                    campo = campo_raw.strip()
                    opzioni = list(opzioni_estratte.get(campo, []))

                r = ctk.CTkFrame(f_ana, fg_color="transparent")
                r.pack(fill="x", pady=2)
                ctk.CTkLabel(r, text=campo, width=180, anchor="w").pack(side="left")

                if opzioni:
                    opzioni.sort()
                    var = ctk.StringVar(value="-- Seleziona --")
                    e = ctk.CTkOptionMenu(
                        r, values=["-- Seleziona --"] + opzioni, variable=var, width=280,
                        fg_color=("#95A5A6", "#4D5656"), button_color=("#7F8C8D", "#34495E"),
                        button_hover_color=("#bdc3c7", "#2C3E50")
                    )
                    e.pack(side="left")
                else:
                    e = ctk.CTkEntry(r, width=280)
                    e.pack(side="left")
                    # Pre-compila con la data di oggi i campi come "Data Somministrazione" (escludendo "Data di nascita")
                    if "data" in campo.lower() and "nascita" not in campo.lower():
                        e.insert(0, datetime.datetime.now().strftime("%d/%m/%Y"))

                self.var_anagrafica[campo] = e

        reverse_map = {}
        for dim in self.engine.dimensioni:
            sid = dim.get('sezione_id')
            for iid in dim.get('item_ids_reverse', []): reverse_map.setdefault(sid, set()).add(iid)

        # --- SEZIONI QUESTIONARIO ---
        for sez in self.engine.sezioni:
            ctk.CTkFrame(scroll, height=1, fg_color="gray").pack(fill="x", padx=10, pady=(10, 6))

            head_frm = ctk.CTkFrame(scroll, fg_color="transparent")
            head_frm.pack(fill="x", padx=10, pady=(0, 4))
            ctk.CTkLabel(head_frm, text=sez['titolo'], font=ctk.CTkFont(weight="bold", size=13)).pack(side="left")

            tipo, sez_id, rev_set = sez['tipo'], sez['id'], reverse_map.get(sez['id'], set())
            self.var_risposte_per_sezione[sez_id] = {}

            if tipo == 'likert':
                etichette_base, valori = sez.get('opzioni_etichette', []), sez.get('opzioni_valori', [])
                etichette_visive = [f"[{v}] {e}" for v, e in zip(valori, etichette_base)]

                caratteri_opzioni = sum(len(x) for x in etichette_visive)
                usa_layout_impilato = (caratteri_opzioni > 72 or len(etichette_visive) > 6)

                for row_idx, item in enumerate(sez.get('items', [])):
                    iid = item['id']
                    # Fascia compatta con alternanza chiaro/scuro
                    bg_card = ("#F4F6F7", "#1C2026") if row_idx % 2 == 0 else ("#E5E8E8", "#252A32")
                    frm = ctk.CTkFrame(scroll, corner_radius=4, fg_color=bg_card)
                    frm.pack(fill="x", padx=10, pady=1)
                    colore_lbl = ("gray10", "gray90")

                    var = ctk.StringVar(value="")

                    if usa_layout_impilato:
                        lbl_domanda = ctk.CTkLabel(
                            frm, text=f"{iid}. {item['testo']}", wraplength=900,
                            justify="left", anchor="w", text_color=colore_lbl,
                            font=ctk.CTkFont(size=12)
                        )
                        lbl_domanda.pack(fill="x", padx=10, pady=(4, 1))

                        ctrl_frm = ctk.CTkFrame(frm, fg_color="transparent")
                        ctrl_frm.pack(fill="x", padx=8, pady=(1, 4))

                        seg_btn = ctk.CTkSegmentedButton(
                            ctrl_frm, values=etichette_visive, variable=var,
                            height=26, font=ctk.CTkFont(size=11)
                        )
                        seg_btn.pack(side="right", padx=4)

                        e_fast = ctk.CTkEntry(
                            ctrl_frm, width=36, height=26, justify="center",
                            font=ctk.CTkFont(size=12, weight="bold")
                        )
                        e_fast.pack(side="right", padx=6)

                        frm.bind("<Configure>", lambda ev, l=lbl_domanda: l.configure(wraplength=max(300, ev.width - 25)))
                    else:
                        ctrl_frm = ctk.CTkFrame(frm, fg_color="transparent")
                        ctrl_frm.pack(side="right", padx=6, pady=3)

                        seg_btn = ctk.CTkSegmentedButton(
                            ctrl_frm, values=etichette_visive, variable=var,
                            height=26, font=ctk.CTkFont(size=11)
                        )
                        seg_btn.pack(side="right", padx=4)

                        e_fast = ctk.CTkEntry(
                            ctrl_frm, width=36, height=26, justify="center",
                            font=ctk.CTkFont(size=12, weight="bold")
                        )
                        e_fast.pack(side="right", padx=6)

                        lbl_domanda = ctk.CTkLabel(
                            frm, text=f"{iid}. {item['testo']}", wraplength=420,
                            justify="left", anchor="w", text_color=colore_lbl,
                            font=ctk.CTkFont(size=12)
                        )
                        lbl_domanda.pack(side="left", fill="x", expand=True, padx=10, pady=3)

                        def _adatta_wrap(ev, l=lbl_domanda, cf=ctrl_frm):
                            spazio_libero = ev.width - cf.winfo_reqwidth() - 30
                            l.configure(wraplength=max(220, spazio_libero))
                        frm.bind("<Configure>", _adatta_wrap)

                    def bind_likert(idx, w_e, w_var, w_etich_visive, w_val):
                        def on_var_change(*args):
                            v_corr = w_var.get()
                            if v_corr in w_etich_visive:
                                num = w_val[w_etich_visive.index(v_corr)]
                                if w_e.get() != str(num):
                                    w_e.delete(0, 'end')
                                    w_e.insert(0, str(num))

                        w_var.trace_add("write", on_var_change)

                        def on_key(event):
                            if event.keysym in ['Tab', 'BackSpace', 'Delete', 'Shift_L', 'Shift_R']: return
                            val_txt = w_e.get().strip()
                            if not val_txt: return
                            try:
                                v_num = int(val_txt)
                                if v_num in w_val:
                                    w_var.set(w_etich_visive[w_val.index(v_num)])
                                    if idx + 1 < len(self.lista_focus_entry):
                                        self.lista_focus_entry[idx + 1].focus_set()
                            except ValueError:
                                pass

                        w_e.bind("<KeyRelease>", on_key)

                    bind_likert(index_entry, e_fast, var, etichette_visive, valori)
                    self.lista_focus_entry.append(e_fast)
                    index_entry += 1

                    self.var_risposte_per_sezione[sez_id][iid] = (var, etichette_visive, valori)

            elif tipo == 'numerico':
                ctk.CTkLabel(head_frm, text="Inserisci il valore numerico e premi [Invio] per avanzare",
                             text_color="gray", font=ctk.CTkFont(size=11)).pack(side="right")

                for row_idx, item in enumerate(sez.get('items', [])):
                    iid = item['id']
                    bg_card = ("#F4F6F7", "#1C2026") if row_idx % 2 == 0 else ("#E5E8E8", "#252A32")
                    frm = ctk.CTkFrame(scroll, corner_radius=4, fg_color=bg_card)
                    frm.pack(fill="x", padx=10, pady=1)

                    e_num = ctk.CTkEntry(
                        frm, width=100, height=26, justify="center",
                        placeholder_text="0.0", font=ctk.CTkFont(size=12, weight="bold")
                    )
                    e_num.pack(side="right", padx=12, pady=3)

                    lbl_domanda = ctk.CTkLabel(
                        frm, text=f"{iid}. {item['testo']}", wraplength=520,
                        justify="left", anchor="w", font=ctk.CTkFont(size=12)
                    )
                    lbl_domanda.pack(side="left", fill="x", expand=True, padx=10, pady=3)

                    frm.bind("<Configure>", lambda ev, l=lbl_domanda: l.configure(wraplength=max(250, ev.width - 150)))

                    def bind_num_enter(idx, w_e):
                        def on_enter(event):
                            if idx + 1 < len(self.lista_focus_entry):
                                self.lista_focus_entry[idx + 1].focus_set()

                        w_e.bind("<Return>", on_enter)

                    bind_num_enter(index_entry, e_num)
                    self.lista_focus_entry.append(e_num)
                    index_entry += 1

                    self.var_risposte_per_sezione[sez_id][iid] = e_num

            elif tipo == 'aperta':
                for item in sez.get('items', []):
                    iid = item['id']
                    ctk.CTkLabel(scroll, text=f"  {iid}. {item['testo']}", anchor="w").pack(anchor="w", padx=14)
                    box = ctk.CTkTextbox(scroll, height=65)
                    box.pack(fill="x", padx=14, pady=3)

                    self.lista_focus_entry.append(box)
                    index_entry += 1
                    self.var_risposte_per_sezione[sez_id][iid] = box

            elif tipo == 'si_no':
                ctk.CTkLabel(head_frm, text="Tastiera: [1] o [S]=Sì  |  [0] o [N]=No", text_color="gray",
                             font=ctk.CTkFont(size=11)).pack(side="right")

                for row_idx, item in enumerate(sez.get('items', [])):
                    iid = item['id']
                    bg_card = ("#F4F6F7", "#1C2026") if row_idx % 2 == 0 else ("#E5E8E8", "#252A32")
                    frm = ctk.CTkFrame(scroll, corner_radius=4, fg_color=bg_card)
                    frm.pack(fill="x", padx=10, pady=1)

                    ctrl_frm = ctk.CTkFrame(frm, fg_color="transparent")
                    ctrl_frm.pack(side="right", padx=6, pady=3)

                    var = ctk.StringVar(value="")
                    seg_btn = ctk.CTkSegmentedButton(
                        ctrl_frm, values=["Sì", "No"], variable=var,
                        height=26, font=ctk.CTkFont(size=11)
                    )
                    seg_btn.pack(side="right", padx=4)

                    e_fast = ctk.CTkEntry(
                        ctrl_frm, width=36, height=26, justify="center",
                        font=ctk.CTkFont(size=12, weight="bold")
                    )
                    e_fast.pack(side="right", padx=6)

                    lbl_domanda = ctk.CTkLabel(
                        frm, text=f"{iid}. {item['testo']}", wraplength=460,
                        justify="left", anchor="w", font=ctk.CTkFont(size=12)
                    )
                    lbl_domanda.pack(side="left", fill="x", expand=True, padx=10, pady=3)

                    def _adatta_wrap_sn(ev, l=lbl_domanda, cf=ctrl_frm):
                        spazio_libero = ev.width - cf.winfo_reqwidth() - 30
                        l.configure(wraplength=max(250, spazio_libero))
                    frm.bind("<Configure>", _adatta_wrap_sn)

                    def bind_sino(idx, w_e, w_var):
                        def on_var_change(*args):
                            if w_e.get() != w_var.get():
                                w_e.delete(0, 'end')
                                w_e.insert(0, w_var.get())

                        w_var.trace_add("write", on_var_change)

                        def on_key(event):
                            if event.keysym in ['Tab', 'BackSpace', 'Delete', 'Shift_L', 'Shift_R']: return
                            char = getattr(event, 'char', '').lower()
                            if not char: return

                            if char in ['1', 's', 'y']:
                                w_var.set("Sì")
                                if idx + 1 < len(self.lista_focus_entry): self.lista_focus_entry[idx + 1].focus_set()
                            elif char in ['0', 'n']:
                                w_var.set("No")
                                if idx + 1 < len(self.lista_focus_entry): self.lista_focus_entry[idx + 1].focus_set()

                        w_e.bind("<KeyRelease>", on_key)

                    bind_sino(index_entry, e_fast, var)
                    self.lista_focus_entry.append(e_fast)
                    index_entry += 1

                    self.var_risposte_per_sezione[sez_id][iid] = var

        ctk.CTkButton(self.schermata_corrente, text="📊  Elabora Risposte e Calcola Risultati",
                      command=self.elabora_results, height=44, font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)


    def elabora_results(self):
        dati_paziente = {}
        for c, w in getattr(self, 'var_anagrafica', {}).items():
            val = w.get().strip()
            dati_paziente[c] = "" if val == "-- Seleziona --" else val
        risposte_per_sezione = {}

        for sez_id, items_vars in self.var_risposte_per_sezione.items():
            sez = next((s for s in self.engine.sezioni if s['id'] == sez_id), None)
            tipo = sez['tipo'] if sez else 'likert'
            risposte_per_sezione[sez_id] = {}
            for iid, widget in items_vars.items():
                if tipo == 'likert':
                    var, etichette_visive, valori = widget
                    sel = var.get()
                    if sel == "":
                        messagebox.showwarning("Dato Mancante",
                                               f"L'item {iid} nella sezione '{sez['titolo']}' richiede una risposta prima di continuare.")
                        return
                    risposte_per_sezione[sez_id][iid] = etichette_visive.index(sel)
                elif tipo == 'aperta':
                    risposte_per_sezione[sez_id][iid] = widget.get("1.0", "end-1c").strip()
                elif tipo == 'si_no':
                    val = widget.get().strip()
                    if val == "":
                        messagebox.showwarning("Dato Mancante",
                                               f"L'item {iid} nella sezione '{sez['titolo']}' richiede una risposta (Sì/No).")
                        return
                    risposte_per_sezione[sez_id][iid] = val
                elif tipo == 'numerico':
                    raw_txt = widget.get().strip().replace(',', '.')
                    if raw_txt == "":
                        messagebox.showwarning("Dato Mancante",
                                               f"L'item {iid} nella sezione '{sez['titolo']}' richiede un valore numerico.")
                        return
                    try:
                        num_f = float(raw_txt)
                        risposte_per_sezione[sez_id][iid] = int(num_f) if num_f.is_integer() else num_f
                    except ValueError:
                        messagebox.showerror("Valore Non Valido",
                                             f"Il valore '{widget.get()}' nell'item {iid} ('{sez['titolo']}') non è un numero valido.")
                        return

        risultati_dim = self.engine.calcola_punteggi(risposte_per_sezione, dati_paziente)
        if self.engine.ultimi_errori:
            messagebox.showerror(
                "Calcolo non affidabile",
                "I punteggi non possono essere calcolati correttamente:\n\n• " +
                "\n• ".join(self.engine.ultimi_errori[:8]) +
                "\n\nCompleta i dati anagrafici richiesti (o correggi il test) e riprova.")
            return
        if self.engine.ultimi_avvisi:
            messagebox.showwarning(
                "Attenzione ai calcoli",
                "• " + "\n• ".join(self.engine.ultimi_avvisi[:8]))
        self._mostra_risultati(risultati_dim, dati_paziente, risposte_per_sezione)

    def _mostra_risultati(self, risultati_dim, dati_paziente, risposte_per_sezione):
        win = ctk.CTkToplevel(self)
        win.title("Report Calcolo e Osservazioni Cliniche")
        win.geometry("800x700")
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="Profili Clinici e Punteggi Calcolati", font=ctk.CTkFont(size=20, weight="bold")).pack(
            pady=(12, 6))
        scroll = ctk.CTkScrollableFrame(win)
        scroll.pack(fill="both", expand=True, padx=20, pady=4)

        COLOR_CTK = {'green': '#2ECC71', 'yellow': '#F1C40F', 'orange': '#E67E22', 'red': '#E74C3C', 'gray': '#95A5A6'}
        PE_COLOR_CTK = {0: '#E74C3C', 1: '#E67E22', 2: '#27AE60', 3: '#2ECC71', 4: '#16A085'}
        PE_DESC = {0: "Deficitario", 1: "Ai limiti di norma", 2: "Nella norma", 3: "Nella norma", 4: "Superiore"}

        # --- AVVISO ITEM CRITICI (RED FLAGS) ---
        item_critici = self.engine.rileva_item_critici(risposte_per_sezione)
        if item_critici:
            alert_frm = ctk.CTkFrame(scroll, corner_radius=8, fg_color=("#FDEDEC", "#3B1A1A"),
                                     border_width=2, border_color="#E74C3C")
            alert_frm.pack(fill="x", pady=(4, 10))
            ctk.CTkLabel(alert_frm, text=f"⚠️  ATTENZIONE: Rilevati {len(item_critici)} Item Critici (Red Flags)",
                         font=ctk.CTkFont(size=14, weight="bold"), text_color=("#C0392B", "#FF6B6B")).pack(anchor="w", padx=12, pady=(8, 4))
            for ic in item_critici:
                testo_ic = f"• Item {ic['id']} ({ic['testo']})  ➔  Risposta: {ic['risposta']}   [{ic['nota']}]"
                ctk.CTkLabel(alert_frm, text=testo_ic, wraplength=700, justify="left",
                             font=ctk.CTkFont(size=12, weight="bold"), text_color=("#7B241C", "#FADBD8")).pack(anchor="w", padx=16, pady=2)
            ctk.CTkFrame(alert_frm, height=4, fg_color="transparent").pack()

        # --- CARD PUNTEGGI E PUNTEGGI EQUIVALENTI ---
        for r in risultati_dim.values():
            frm = ctk.CTkFrame(scroll, corner_radius=8)
            frm.pack(fill="x", pady=4)
            co = r.get('cutoff')
            pe_val = r.get('pe')
            bg = COLOR_CTK.get(co['colore'], '#3498DB') if co else '#3498DB'

            label_sc = "Somma"
            if r['tipo_scoring'] == 'media': label_sc = "Media"
            elif r['tipo_scoring'] == 'formula': label_sc = "Composito Avanzato"

            ctk.CTkLabel(frm, text=r['nome'], font=ctk.CTkFont(weight="bold", size=14)).pack(anchor="w", padx=12, pady=(8, 2))

            if r['correzione'] != 0.0:
                stringa_punti = f"Punteggio ({label_sc}): {r['punteggio_grezzo']:g}  (Corretto a {r['punteggio']:g})"
            else:
                stringa_punti = f"Punteggio ({label_sc}): {r['punteggio']:g}"

            if r['max'] > 0: stringa_punti += f" / {r['max']:g}"
            ctk.CTkLabel(frm, text=stringa_punti).pack(anchor="w", padx=12)

            if co or pe_val is not None:
                badge_row = ctk.CTkFrame(frm, fg_color="transparent")
                badge_row.pack(anchor="w", padx=12, pady=(4, 8))
                if pe_val is not None:
                    pe_bg = PE_COLOR_CTK.get(pe_val, '#3498DB')
                    ctk.CTkLabel(badge_row, text=f"  PE {pe_val} — {PE_DESC.get(pe_val, '')}  ",
                                 fg_color=pe_bg, corner_radius=6, text_color="white",
                                 font=ctk.CTkFont(size=12, weight="bold")).pack(side="left", padx=(0, 8))
                if co:
                    ctk.CTkLabel(badge_row, text=f"  {co['etichetta']}  ",
                                 fg_color=bg, corner_radius=6, text_color="white",
                                 font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")

        # --- BOX OSSERVAZIONI CLINICHE ---
        obs_frame = ctk.CTkFrame(win, fg_color="transparent")
        obs_frame.pack(fill="x", padx=20, pady=(6, 2))
        ctk.CTkLabel(obs_frame, text="📝 Osservazioni Cliniche e Note Comportamentali (incluse nel Referto PDF):",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", pady=(0, 4))
        txt_osservazioni = ctk.CTkTextbox(obs_frame, height=80)
        txt_osservazioni.pack(fill="x")

        btn_frame = ctk.CTkFrame(win, fg_color="transparent")
        btn_frame.pack(pady=12, fill="x", padx=20)
        ctk.CTkButton(
            btn_frame, text="🖨  Esporta ed Apri PDF", height=42, font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#8E44AD", hover_color="#6C3483",
            command=lambda: OpzioniGraficoWindow(
                win, risultati_dim, self.engine,
                lambda opt: self._do_stampa(opt, dati_paziente, risposte_per_sezione, risultati_dim,
                                            txt_osservazioni.get("1.0", "end-1c").strip()),
                lambda opt: self._do_salva(opt, dati_paziente, risposte_per_sezione, risultati_dim,
                                           txt_osservazioni.get("1.0", "end-1c").strip())
            )
        ).pack(fill="x", padx=5)

    def _do_stampa(self, opzioni_grafico, dati_paziente, risposte_per_sezione, risultati_dim, osservazioni=""):
        try:
            stampa_pdf(self.engine, dati_paziente, risposte_per_sezione, risultati_dim, opzioni_grafico, osservazioni)
        except Exception as e:
            messagebox.showerror("Errore", str(e))

    def _do_salva(self, opzioni_grafico, dati_paziente, risposte_per_sezione, risultati_dim, osservazioni=""):
        fp = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
                                          initialfile=f"Report_{dati_paziente.get('Cognome', 'Paziente')}.pdf")
        if fp:
            try:
                genera_pdf(self.engine, dati_paziente, risposte_per_sezione, risultati_dim, fp, opzioni_grafico, osservazioni)
                messagebox.showinfo("Salvato", "Il referto PDF è stato generato e salvato correttamente.")
            except Exception as e:
                messagebox.showerror("Errore", str(e))


if __name__ == "__main__":
    app = PsychoScorerApp()
    app.mainloop()