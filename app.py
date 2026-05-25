from flask import Flask, render_template, request, redirect, session
import requests, random, os, re, sys
import pandas as pd
import random
import time
import json
import uuid
import math
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import subprocess
import tempfile
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "genetic-secret-key"

UPLOAD_FOLDER = "uploads"
DATA_FOLDER = "data"
TERMINAL_LOG_FOLDER = os.path.join(DATA_FOLDER, "terminal_logs")
ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATA_FOLDER, exist_ok=True)
os.makedirs(TERMINAL_LOG_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ASSIGNMENT_STORE = os.path.join(DATA_FOLDER, "courier_assignments.json")
GEOCODE_CACHE_FILE = os.path.join(DATA_FOLDER, "geocode_cache.json")
MATRIX_CACHE_FILE = os.path.join(DATA_FOLDER, "matrix_cache.json")
ROUTE_GEOMETRY_CACHE_FILE = os.path.join(DATA_FOLDER, "route_geometry_cache.json")
GA_DEFAULTS_FILE = os.path.join(DATA_FOLDER, "ga_defaults.json")
TERMINAL_LOG_FILE = os.path.join(
    TERMINAL_LOG_FOLDER,
    f"terminal_{datetime.now().strftime('%Y-%m-%d')}.log"
)


class TimestampedTerminalTee:
    def __init__(self, terminal_stream, log_file_path, stream_name):
        self.terminal_stream = terminal_stream
        self.log_file_path = log_file_path
        self.stream_name = stream_name
        self.buffer = ""
        self.lock = Lock()
        self.encoding = getattr(terminal_stream, "encoding", "utf-8")

    def write(self, message):
        self.terminal_stream.write(message)
        self.terminal_stream.flush()
        if not message:
            return

        with self.lock:
            self.buffer += str(message)
            while "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                self.write_log_line(line)

    def flush(self):
        self.terminal_stream.flush()
        with self.lock:
            if self.buffer:
                self.write_log_line(self.buffer)
                self.buffer = ""

    def isatty(self):
        return self.terminal_stream.isatty()

    def write_log_line(self, line):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(self.log_file_path, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] [{self.stream_name}] {line}\n")


def setup_terminal_file_logging():
    if not isinstance(sys.stdout, TimestampedTerminalTee):
        sys.stdout = TimestampedTerminalTee(
            sys.stdout,
            TERMINAL_LOG_FILE,
            "STDOUT"
        )
    if not isinstance(sys.stderr, TimestampedTerminalTee):
        sys.stderr = TimestampedTerminalTee(
            sys.stderr,
            TERMINAL_LOG_FILE,
            "STDERR"
        )
    print(f"Log terminal disimpan di: {TERMINAL_LOG_FILE}")


setup_terminal_file_logging()

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "AIzaSyAUjqeqEuEi2A2x6litKyxjA0QKhyac5lo").strip()
GEOCODE_CACHE = {}
MATRIX_CACHE = {}
ROUTE_GEOMETRY_CACHE = {}
OPTIMIZATION_RESULTS_CACHE = {}
CLUSTER_OPTIMIZATION_RESULTS_CACHE = {}
CACHE_LOCK = Lock()
MAX_ROUTE_POINTS = 21
MAX_POINTS_PER_COURIER = MAX_ROUTE_POINTS - 1
GA_POP_SIZE = 18
GA_GENERATIONS = 55
GA_CROSSOVER_RATE = 0.8
GA_MUTATION_RATE = 0.2
GOOGLE_MATRIX_BATCH_SIZE = 10
GOOGLE_DIRECTIONS_MAX_COORDS = 25
GENERATION_LOG_INTERVAL = 10
GEOCODE_WORKERS = 8
GEOCODE_CACHE_VERSION = "google-v10-places-address-first-geocode"
OPTIMIZATION_CONFIG_VERSION = (
    "ga-v2",
    MAX_ROUTE_POINTS,
    MAX_POINTS_PER_COURIER,
)
LEGACY_RESULT_SESSION_KEYS = (
    "optimization_results",
    "cluster_optimization_results",
)
MALANG_WILAYAH = [
    "KOTA MALANG, BLIMBING, BLIMBING",
    "KOTA MALANG, BLIMBING, POLEHAN",
    "KOTA MALANG, BLIMBING, PANDANWANGI",
    "KOTA MALANG, BLIMBING, ARJOSARI",
    "KOTA MALANG, BLIMBING, PURWODADI",
    "KOTA MALANG, BLIMBING, PURWANTORO",
    "KOTA MALANG, BLIMBING, KESATRIAN",
    "KOTA MALANG, BLIMBING, BUNULREJO",
    "KOTA MALANG, BLIMBING, BALEARJOSARI",
    "KOTA MALANG, BLIMBING, POLOWIJEN",
    "KOTA MALANG, BLIMBING, JODIPAN",

    "KOTA MALANG, KLOJEN, KLOJEN",
    "KOTA MALANG, KLOJEN, GADING KASRI",
    "KOTA MALANG, KLOJEN, PENANGGUNGAN",
    "KOTA MALANG, KLOJEN, KAUMAN",
    "KOTA MALANG, KLOJEN, SAMAAN",
    "KOTA MALANG, KLOJEN, KIDULDALEM",

    "KOTA MALANG, LOWOKWARU, TUNGGULWULUNG",
    "KOTA MALANG, LOWOKWARU, TUNJUNGSEKAR",
    "KOTA MALANG, LOWOKWARU, MERJOSARI",
    "KOTA MALANG, LOWOKWARU, SUMBERSARI",
    "KOTA MALANG, LOWOKWARU, DINOYO",
    "KOTA MALANG, LOWOKWARU, MOJOLANGU",
    "KOTA MALANG, LOWOKWARU, TLOGOMAS",
    "KOTA MALANG, LOWOKWARU, JATIMULYO",

    "KOTA MALANG, SUKUN, SUKUN",
    "KOTA MALANG, SUKUN, CIPTOMULYO",
    "KOTA MALANG, SUKUN, PISANGCANDI",
    "KOTA MALANG, SUKUN, BANDULAN",
    "KOTA MALANG, SUKUN, GADANG",

    "KOTA MALANG, KEDUNGKANDANG, SAWOJAJAR",
    "KOTA MALANG, KEDUNGKANDANG, BUMIAYU",
    "KOTA MALANG, KEDUNGKANDANG, KOTALAMA",
    "KOTA MALANG, KEDUNGKANDANG, MERGOSONO",
    "KOTA MALANG, KEDUNGKANDANG, LESANPURO",
    "KOTA MALANG, KEDUNGKANDANG, ARJOWINANGUN",
    "KOTA MALANG, KEDUNGKANDANG, BURING",
    "KOTA MALANG, KEDUNGKANDANG, MADYOPURO",
]

# Alias for backward compatibility
MALANG_KECAMATAN = MALANG_WILAYAH


# Memecah teks wilayah menjadi bagian kota, kecamatan, dan kelurahan yang sudah dinormalisasi.
def split_wilayah_parts(wilayah):
    return [
        normalize_text(part)
        for part in normalize_text(wilayah).split(",")
        if normalize_text(part)
    ]


# Mengambil daftar kecamatan unik dari master wilayah Malang untuk pilihan form.
def get_kecamatan_options():
    options = []
    seen = set()
    for wilayah in MALANG_WILAYAH:
        parts = split_wilayah_parts(wilayah)
        if len(parts) < 2:
            continue

        kecamatan = f"{parts[0]}, {parts[1]}"
        key = normalize_key(kecamatan)
        if key not in seen:
            seen.add(key)
            options.append(kecamatan)

    return options


# Mengambil semua kelurahan yang berada di bawah kecamatan tertentu.
def get_kelurahan_by_kecamatan(kecamatan):
    kecamatan_key = normalize_key(kecamatan)
    return [
        wilayah
        for wilayah in MALANG_WILAYAH
        if normalize_key(", ".join(split_wilayah_parts(wilayah)[:2])) == kecamatan_key
    ]


# Mengubah pilihan penugasan kecamatan menjadi daftar kelurahan, atau menjaga pilihan spesifik apa adanya.
def expand_penugasan_selection(penugasan):
    text = normalize_text(penugasan)
    if not text:
        return []

    kecamatan_values = get_kelurahan_by_kecamatan(text)
    if kecamatan_values:
        return kecamatan_values

    return [text]


# Mengambil ekstensi file dalam format huruf kecil.
def get_file_extension(filename):
    return os.path.splitext(filename)[1].lower()


# Memvalidasi apakah file upload memiliki ekstensi yang didukung.
def allowed_file(filename):
    return get_file_extension(filename) in ALLOWED_EXTENSIONS


# Menormalisasi nomor resi agar duplikasi dapat dibandingkan secara konsisten.
def normalize_resi_key(value):
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)

    text = normalize_text(value)
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]

    return normalize_key(text)


# Menghapus baris dengan nomor resi duplikat agar paket tidak diproses dua kali.
def remove_duplicate_nosi_rows(df):
    resi_column = safe_find_column(
        df,
        ["Nosi", "No_Resi", "No Resi", "Nomor Resi"]
    )
    if resi_column is None:
        return df

    prepared = df.copy()
    resi_keys = prepared[resi_column].apply(normalize_resi_key)
    duplicate_mask = resi_keys.ne("") & resi_keys.duplicated(keep="first")
    if not duplicate_mask.any():
        return df

    return prepared[~duplicate_mask].copy()


# Membaca file upload CSV atau Excel lalu membersihkan duplikasi nomor resi.
def load_uploaded_dataframe(filepath):
    ext = get_file_extension(filepath)

    if ext == ".csv":
        try:
            # dtype=str menghindari inferensi tipe yang mahal (terutama untuk file besar).
            # low_memory=False membantu parsing yang lebih stabil.
            df = pd.read_csv(filepath, dtype=str, low_memory=False)
        except UnicodeDecodeError:
            df = pd.read_csv(filepath, dtype=str, low_memory=False, encoding="latin1")
        return remove_duplicate_nosi_rows(df)

    if ext in {".xlsx", ".xls"}:
        # dtype=str mempercepat parsing dan menjaga konsistensi nilai (mis. resi tidak jadi float).
        # engine untuk xlsx biasanya openpyxl; untuk xls biarkan pandas memilih engine yang tersedia.
        read_kwargs = {"dtype": str}
        if ext == ".xlsx":
            try:
                df = pd.read_excel(filepath, engine="openpyxl", **read_kwargs)
            except Exception:
                df = pd.read_excel(filepath, **read_kwargs)
        else:
            df = pd.read_excel(filepath, **read_kwargs)
        return remove_duplicate_nosi_rows(df)

    raise ValueError("Format file tidak didukung. Gunakan CSV atau Excel.")


# Menghapus file upload lama yang tersimpan pada session tertentu.
def remove_uploaded_file(session_key):
    path = session.pop(session_key, None)
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


# Menyimpan file upload baru dan mencatat path-nya ke session.
def save_uploaded_file(file_storage, session_key, filename_prefix):
    original_filename = secure_filename(file_storage.filename)

    if not allowed_file(original_filename):
        raise ValueError("File harus berformat CSV, XLSX, atau XLS")

    remove_uploaded_file(session_key)

    extension = get_file_extension(original_filename)
    filename = original_filename or f"{filename_prefix}{extension}"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if os.path.exists(filepath):
        base_name = os.path.splitext(filename)[0]
        filename = f"{base_name}_{uuid.uuid4().hex[:8]}{extension}"
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    file_storage.save(filepath)
    session[session_key] = filepath
    return filepath


# Membaca data penugasan kurir manual dari file JSON.
def load_manual_assignments():
    if not os.path.exists(ASSIGNMENT_STORE):
        return []

    try:
        with open(ASSIGNMENT_STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except Exception:
        pass

    return []


# Menyimpan data penugasan kurir manual ke file JSON.
def save_manual_assignments(assignments):
    with open(ASSIGNMENT_STORE, "w", encoding="utf-8") as fh:
        json.dump(assignments, fh, ensure_ascii=False, indent=2)


# Membuat ringkasan wilayah penugasan untuk setiap kurir.
def get_manual_assignment_summary():
    summary = {}
    for item in load_manual_assignments():
        petugas = normalize_text(item.get("petugas"))
        penugasan = normalize_text(item.get("penugasan"))
        if not petugas or not penugasan:
            continue
        summary.setdefault(petugas, set()).add(penugasan)

    return {
        petugas: sorted(values)
        for petugas, values in sorted(summary.items())
    }


# Mengubah penugasan manual JSON menjadi DataFrame agar mudah diproses.
def build_assignment_dataframe_from_manual():
    assignments = load_manual_assignments()
    if not assignments:
        return pd.DataFrame(columns=["Petugas", "Penugasan"])

    rows = []
    for item in assignments:
        petugas = normalize_text(item.get("petugas"))
        penugasan = normalize_text(item.get("penugasan"))
        if petugas and penugasan:
            rows.append({
                "Petugas": petugas,
                "Penugasan": penugasan
            })

    return pd.DataFrame(rows)


# Membersihkan nilai menjadi teks aman tanpa spasi di awal atau akhir.
def normalize_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_delivery_date(value):
    if pd.isna(value):
        return ""

    if isinstance(value, pd.Timestamp):
        return value.strftime("%d/%m/%Y")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            parsed = pd.to_datetime(value, unit="D", origin="1899-12-30")
            if not pd.isna(parsed):
                return parsed.strftime("%d/%m/%Y")
        except Exception:
            pass

    text = normalize_text(value)
    if not text:
        return ""

    try:
        numeric_text = float(text)
        parsed = pd.to_datetime(numeric_text, unit="D", origin="1899-12-30")
        if not pd.isna(parsed):
            return parsed.strftime("%d/%m/%Y")
    except Exception:
        pass

    try:
        parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
        if not pd.isna(parsed):
            return parsed.strftime("%d/%m/%Y")
    except Exception:
        pass

    return text.split()[0]


# Menormalisasi teks menjadi key alfanumerik untuk pencocokan yang tahan variasi format.
def normalize_key(value):
    return "".join(ch for ch in normalize_text(value).lower() if ch.isalnum())


# Membuat beberapa variasi key dari wilayah penugasan untuk membantu pencocokan alamat.
def build_penugasan_match_keys(penugasan):
    """
    Return a list of normalized keys that may appear in alamat strings.
    Supports both legacy values (e.g. "Blimbing") and new format
    "KOTA MALANG, KECAMATAN, KELURAHAN".
    """
    text = normalize_text(penugasan)
    if not text:
        return []

    parts = [p.strip() for p in text.split(",") if p.strip()]
    candidates = [text]
    # Prefer more specific components (kelurahan, kecamatan) to increase match chance.
    if len(parts) >= 3:
        candidates.append(parts[2])
        # Only include kecamatan-level key when it is explicitly modeled
        # (e.g. "... , SUKUN, SUKUN") to avoid ambiguous matches.
        if normalize_key(parts[2]) == normalize_key(parts[1]):
            candidates.append(parts[1])
    elif len(parts) == 2:
        candidates.append(parts[1])

    keys = []
    seen = set()
    for item in candidates:
        key = normalize_key(item)
        # Ignore tiny keys that would over-match common words.
        if len(key) < 4:
            continue
        if key not in seen:
            seen.add(key)
            keys.append(key)

    return keys


# Mencari kolom secara aman dan mengembalikan None jika tidak ditemukan.
def safe_find_column(df, candidates):
    try:
        return find_column(df, candidates, candidates[0])
    except ValueError:
        return None


# Mencari kolom berdasarkan beberapa kemungkinan nama dengan normalisasi.
def find_column(df, candidates, label):
    normalized_columns = {
        normalize_key(col): col
        for col in df.columns
    }

    for candidate in candidates:
        key = normalize_key(candidate)
        if key in normalized_columns:
            return normalized_columns[key]

    raise ValueError(
        f"Kolom {label} tidak ditemukan. Pastikan file memiliki salah satu kolom: {', '.join(candidates)}"
    )


# Menentukan kolom-kolom penting pada data paket seperti resi, nama, alamat, tanggal, dan kota.
def get_package_columns(df, require_city=True):
    columns = {
        "resi": safe_find_column(
            df,
            ["Nosi", "No_Resi", "No Resi", "Nomor Resi"]
        ),
        "nama": safe_find_column(df, ["Nama_Penerima", "Nama Penerima", "Penerima"]),
        "alamat": find_column(df, ["Alamat"], "alamat"),
        "petugas": safe_find_column(df, ["Petugas", "Kurir", "Nama Kurir", "Nama Petugas"]),
        "tanggal": safe_find_column(
            df,
            ["Tgl_Antaran_Pertama", "Tanggal Antaran Pertama"]
        ),
    }

    if require_city:
        columns["kota"] = find_column(df, ["Kota", "Kecamatan"], "kota/kecamatan")
    else:
        try:
            columns["kota"] = find_column(df, ["Kota", "Kecamatan"], "kota/kecamatan")
        except ValueError:
            columns["kota"] = None

    return columns


# Menentukan kolom-kolom penting pada data penugasan kurir.
def get_assignment_columns(df):
    return {
        "petugas": find_column(df, ["Petugas"], "nama kurir"),
        "penugasan": find_column(
            df,
            ["Penugasan", "Kecamatan", "Kota", "Area", "Wilayah"],
            "penugasan/kecamatan"
        ),
    }


# Menyiapkan DataFrame paket dengan kolom internal yang sudah dinormalisasi.
def prepare_package_dataframe(df, require_city=True):
    columns = get_package_columns(df, require_city=require_city)
    prepared = df.copy()
    if columns["resi"] is None:
        prepared["__resi"] = ""
    else:
        prepared["__resi"] = prepared[columns["resi"]].apply(normalize_text)
    if columns["nama"] is None:
        prepared["__nama"] = ""
    else:
        prepared["__nama"] = prepared[columns["nama"]].apply(normalize_text)
    if columns["petugas"] is None:
        prepared["__petugas"] = ""
    else:
        prepared["__petugas"] = prepared[columns["petugas"]].apply(normalize_text)
    prepared["__petugas_key"] = prepared["__petugas"].apply(normalize_key)
    prepared["__alamat"] = prepared[columns["alamat"]].apply(normalize_text)
    if columns["kota"] is None:
        prepared["__kota"] = ""
    else:
        prepared["__kota"] = prepared[columns["kota"]].apply(normalize_text)
    prepared["__kota_key"] = prepared["__kota"].apply(normalize_key)
    if columns["tanggal"] is None:
        prepared["__tanggal"] = ""
    else:
        prepared["__tanggal"] = prepared[columns["tanggal"]].apply(normalize_delivery_date)

    filters = prepared["__alamat"].ne("")
    if columns["tanggal"] is not None:
        filters = filters & prepared["__tanggal"].ne("")
    if require_city:
        filters = filters & prepared["__kota"].ne("")

    prepared = prepared[filters].copy()

    return prepared


# Menyiapkan DataFrame penugasan dengan key pencocokan wilayah.
def prepare_assignment_dataframe(df):
    columns = get_assignment_columns(df)
    prepared = df.copy()
    prepared["__petugas"] = prepared[columns["petugas"]].apply(normalize_text)
    prepared["__petugas_key"] = prepared["__petugas"].apply(normalize_key)
    prepared["__penugasan"] = prepared[columns["penugasan"]].apply(normalize_text)
    prepared["__penugasan_key"] = prepared["__penugasan"].apply(normalize_key)
    prepared["__match_keys"] = prepared["__penugasan"].apply(build_penugasan_match_keys)

    prepared = prepared[
        prepared["__petugas"].ne("") &
        prepared["__penugasan"].ne("")
    ].copy()

    return prepared


# Mengambil daftar tanggal antaran yang tersedia dari data paket.
def get_available_dates(package_df):
    prepared = prepare_package_dataframe(package_df, require_city=False)
    return sorted(prepared["__tanggal"].dropna().unique().tolist())


# Membuat ringkasan penugasan dari DataFrame penugasan.
def get_assignment_summary(assignment_df):
    prepared = prepare_assignment_dataframe(assignment_df)
    grouped = prepared.groupby("__petugas")["__penugasan"].apply(
        lambda values: sorted(set(v for v in values if v))
    )
    return grouped.to_dict()


# Mengambil daftar kurir yang memiliki wilayah cocok pada tanggal tertentu.
def get_available_petugas_for_date(package_df, assignment_df, selected_tgl):
    prepared_package = prepare_package_dataframe(package_df, require_city=True)
    prepared_assignment = prepare_assignment_dataframe(assignment_df)

    filtered_package = prepared_package[prepared_package["__tanggal"] == str(selected_tgl)]
    available_city_keys = set(filtered_package["__kota_key"].dropna().tolist())

    if not available_city_keys:
        return []

    matched_assignment = prepared_assignment[
        prepared_assignment["__penugasan_key"].isin(available_city_keys)
    ]

    return sorted(matched_assignment["__petugas"].dropna().unique().tolist())


# Mencocokkan alamat dan kolom kota ke wilayah penugasan kurir.
def detect_assignment_from_address(address, prepared_assignment, area=""):
    normalized_area = normalize_key(area)
    normalized_address_only = normalize_key(address)
    normalized_address = normalize_key(f"{address} {area}")

    def find_best_match(search_text, include_self_named_area=False):
        matched_row = None
        matched_length = -1
        for _, row in prepared_assignment.iterrows():
            parts = split_wilayah_parts(row.get("__penugasan", ""))
            district_key = normalize_key(parts[1]) if len(parts) >= 2 else ""
            village_key = normalize_key(parts[2]) if len(parts) >= 3 else ""
            is_self_named_area = village_key and village_key == district_key

            if is_self_named_area and not include_self_named_area:
                continue

            if village_key:
                match_keys = [village_key]
            else:
                match_keys = row.get("__match_keys") or [row.get("__penugasan_key", "")]

            for key in match_keys:
                if key and key in search_text and len(key) > matched_length:
                    matched_row = row
                    matched_length = len(key)
        return matched_row, matched_length

    # Teks alamat lebih dipercaya karena kolom Kota pada file aktual kadang
    # berisi wilayah yang tidak sama dengan kelurahan/kecamatan di alamat.
    if normalized_address_only:
        best_row, best_length = find_best_match(
            normalized_address_only,
            include_self_named_area=False
        )
        if best_row is not None:
            return best_row

    if normalized_area:
        exact_area = prepared_assignment[
            prepared_assignment["__penugasan_key"] == normalized_area
        ]
        if not exact_area.empty:
            return exact_area.iloc[0]

    best_row, _ = find_best_match(
        normalized_address,
        include_self_named_area=True
    )

    return best_row


# Mengambil daftar kurir yang ditugaskan pada wilayah tertentu.
def get_couriers_for_assignment(prepared_assignment, assignment_key):
    matched_rows = prepared_assignment[
        prepared_assignment["__penugasan_key"] == assignment_key
    ]
    courier_names = sorted(matched_rows["__petugas"].dropna().unique().tolist())
    assignment_name = ""
    if not matched_rows.empty:
        assignment_name = matched_rows.iloc[0]["__penugasan"]
    return courier_names, assignment_name


# Memastikan wilayah pada kolom kota ada di master penugasan kurir.
def get_valid_assignment_rows_for_package(row, prepared_assignment):
    matched_row = detect_assignment_from_address(
        row.get("__alamat", ""),
        prepared_assignment,
        row.get("__kota", "")
    )
    if matched_row is None:
        return prepared_assignment.iloc[0:0]

    area_key = matched_row.get("__penugasan_key", "")
    return prepared_assignment[
        prepared_assignment["__penugasan_key"] == area_key
    ]


# Menormalisasi alamat untuk kebutuhan cache geocoding.
def normalize_address(address):
    return str(address).strip().lower()


# Mengosongkan cache hasil optimasi historis.
def clear_optimization_cache():
    OPTIMIZATION_RESULTS_CACHE.clear()


# Mengosongkan cache hasil pemetaan aktual.
def clear_pemetaan_cache():
    CLUSTER_OPTIMIZATION_RESULTS_CACHE.clear()


# Mengosongkan cache routing, matrix, dan geometri rute.
def clear_routing_cache():
    MATRIX_CACHE.clear()
    ROUTE_GEOMETRY_CACHE.clear()
    for cache_file in (MATRIX_CACHE_FILE, ROUTE_GEOMETRY_CACHE_FILE):
        if os.path.exists(cache_file):
            try:
                os.remove(cache_file)
            except Exception:
                pass


# Menghapus payload session lama yang besar agar session tetap ringan.
def purge_legacy_result_session_keys():
    removed = False
    for key in LEGACY_RESULT_SESSION_KEYS:
        if key in session:
            session.pop(key, None)
            removed = True
    if removed:
        session.modified = True


# Membulatkan pasangan koordinat agar stabil saat dipakai sebagai cache key.
def normalize_coord_pair(coord):
    return [round(float(coord[0]), 6), round(float(coord[1]), 6)]


# Membuat key cache berdasarkan daftar koordinat rute.
def make_coords_cache_key(coords):
    return json.dumps(
        {
            "provider": GEOCODE_CACHE_VERSION,
            "coords": [normalize_coord_pair(coord) for coord in coords],
        },
        separators=(",", ":")
    )


# Membaca cache JSON dari disk dengan fallback kosong jika gagal.
def load_json_cache(path):
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return {}


# Menyimpan cache JSON ke disk tanpa menghentikan aplikasi jika gagal.
def save_json_cache(path, data):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    except Exception:
        pass


# Memuat cache geocoding, matrix, dan geometri rute saat aplikasi dimulai.
def load_persistent_routing_caches():
    GEOCODE_CACHE.update(load_json_cache(GEOCODE_CACHE_FILE))
    MATRIX_CACHE.update(load_json_cache(MATRIX_CACHE_FILE))
    ROUTE_GEOMETRY_CACHE.update(load_json_cache(ROUTE_GEOMETRY_CACHE_FILE))


# Membuat key cache optimasi historis berdasarkan file, tanggal, dan kurir.
def get_optimization_cache_key(filepath, tgl, petugas):
    try:
        file_mtime = os.path.getmtime(filepath)
    except OSError:
        file_mtime = 0
    return (
        GEOCODE_CACHE_VERSION,
        OPTIMIZATION_CONFIG_VERSION,
        get_ga_signature(),
        filepath,
        file_mtime,
        str(tgl),
        normalize_text(petugas),
    )


# Membuat key cache pemetaan berdasarkan file upload dan data penugasan.
def get_pemetaan_cache_key(filepath, fast_mode=False):
    try:
        file_mtime = os.path.getmtime(filepath)
    except OSError:
        file_mtime = 0
    try:
        assignment_mtime = os.path.getmtime(ASSIGNMENT_STORE)
    except OSError:
        assignment_mtime = 0
    return (
        GEOCODE_CACHE_VERSION,
        OPTIMIZATION_CONFIG_VERSION,
        bool(fast_mode),
        filepath,
        file_mtime,
        assignment_mtime,
    )


def get_ga_defaults():
    defaults = {
        "pop_size": int(GA_POP_SIZE),
        "generations": int(GA_GENERATIONS),
        "crossover_rate": float(GA_CROSSOVER_RATE),
        "mutation_rate": float(GA_MUTATION_RATE),
    }

    # Opsional: override default dari file JSON (agar bisa disimpan dari UI).
    persisted = load_json_cache(GA_DEFAULTS_FILE)
    if isinstance(persisted, dict):
        for key in defaults:
            if key in persisted:
                defaults[key] = persisted[key]

    try:
        defaults["pop_size"] = int(defaults["pop_size"])
        defaults["generations"] = int(defaults["generations"])
        defaults["crossover_rate"] = float(defaults["crossover_rate"])
        defaults["mutation_rate"] = float(defaults["mutation_rate"])
    except Exception:
        return {
            "pop_size": int(GA_POP_SIZE),
            "generations": int(GA_GENERATIONS),
            "crossover_rate": float(GA_CROSSOVER_RATE),
            "mutation_rate": float(GA_MUTATION_RATE),
        }

    defaults["pop_size"] = clamp(defaults["pop_size"], 2, 5000)
    defaults["generations"] = clamp(defaults["generations"], 1, 20000)
    defaults["crossover_rate"] = float(clamp(defaults["crossover_rate"], 0.0, 1.0))
    defaults["mutation_rate"] = float(clamp(defaults["mutation_rate"], 0.0, 1.0))
    return defaults


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def parse_ga_params(args):
    defaults = get_ga_defaults()

    def parse_int(name, min_value, max_value):
        raw = args.get(name)
        if raw is None or str(raw).strip() == "":
            return defaults[name]
        try:
            parsed = int(float(raw))
        except Exception:
            return defaults[name]
        return clamp(parsed, min_value, max_value)

    def parse_float(name, min_value, max_value):
        raw = args.get(name)
        if raw is None or str(raw).strip() == "":
            return defaults[name]
        try:
            parsed = float(raw)
        except Exception:
            return defaults[name]
        return float(clamp(parsed, min_value, max_value))

    return {
        "pop_size": parse_int("pop_size", 2, 5000),
        "generations": parse_int("generations", 1, 20000),
        "crossover_rate": parse_float("cr", 0.0, 1.0),
        "mutation_rate": parse_float("mr", 0.0, 1.0),
    }


def get_ga_params():
    params = session.get("ga_params")
    defaults = get_ga_defaults()
    if not isinstance(params, dict):
        return dict(defaults)

    merged = dict(defaults)
    for key in defaults:
        if key in params:
            merged[key] = params[key]
    try:
        merged["pop_size"] = int(merged["pop_size"])
        merged["generations"] = int(merged["generations"])
        merged["crossover_rate"] = float(merged["crossover_rate"])
        merged["mutation_rate"] = float(merged["mutation_rate"])
    except Exception:
        return dict(defaults)

    merged["pop_size"] = clamp(merged["pop_size"], 2, 5000)
    merged["generations"] = clamp(merged["generations"], 1, 20000)
    merged["crossover_rate"] = float(clamp(merged["crossover_rate"], 0.0, 1.0))
    merged["mutation_rate"] = float(clamp(merged["mutation_rate"], 0.0, 1.0))
    return merged


def get_ga_signature(params=None):
    params = params or get_ga_params()
    # Bulatkan supaya signature stabil ketika dikirim via query string.
    return (
        int(params["pop_size"]),
        int(params["generations"]),
        round(float(params["crossover_rate"]), 4),
        round(float(params["mutation_rate"]), 4),
    )


load_persistent_routing_caches()

# GEOCODING
# Memastikan API key Google Maps tersedia sebelum memanggil layanan Google.
def require_google_api_key():
    if not GOOGLE_MAPS_API_KEY:
        raise ValueError(
            "GOOGLE_MAPS_API_KEY belum diatur. Set environment variable GOOGLE_MAPS_API_KEY dengan API key Google Maps."
        )


MALANG_BOUNDS = {
    "min_lat": -8.10,
    "max_lat": -7.85,
    "min_lng": 112.55,
    "max_lng": 112.75,
}


# Membaca cakupan dari kolom Kota: kota, kecamatan, dan kelurahan.
def get_area_context(area):
    parts = split_wilayah_parts(area)
    city = parts[0] if len(parts) >= 1 else "KOTA MALANG"
    district = parts[1] if len(parts) >= 2 else ""
    village = parts[2] if len(parts) >= 3 else ""
    return city, district, village


# Membersihkan alamat dari wilayah berulang agar Google mencari alamatnya, bukan pusat wilayahnya.
def clean_address_for_geocode(address, area=""):
    cleaned = normalize_text(address)
    _, district, village = get_area_context(area)
    removable_terms = ["KOTA MALANG", "KABUPATEN MALANG", "MALANG", "JAWA TIMUR", "JATIM"]

    for term in (district, village):
        if term and normalize_key(term) not in {"malang", "kotamalang"}:
            removable_terms.append(term)

    for term in sorted(set(removable_terms), key=len, reverse=True):
        cleaned = re.sub(rf"\b{re.escape(term)}\b", " ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"[,;]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,-")
    return cleaned


# Membuat variasi query geocoding: kolom Kota dibaca dulu, lalu alamat dicari di cakupan itu.
def build_geocode_queries(address, area=""):
    address_text = normalize_text(address)
    area_text = normalize_text(area)
    city, district, village = get_area_context(area_text)
    cleaned_address = clean_address_for_geocode(address_text, area_text)
    candidates = []

    area_parts = []
    if village:
        area_parts.append(f"Kelurahan {village}")
    if district:
        area_parts.append(f"Kecamatan {district}")
    area_parts.append(city or "KOTA MALANG")
    area_parts.extend(["Jawa Timur", "Indonesia"])
    area_scope = ", ".join(area_parts)

    if cleaned_address and area_text:
        candidates.append(f"{address_text}, Kota Malang, Jawa Timur, Indonesia")
        candidates.append(f"{cleaned_address}, Kota Malang, Jawa Timur, Indonesia")
        candidates.append(f"{cleaned_address}, {area_scope}")
        candidates.append(f"{address_text}, {area_scope}")
        if village and district and normalize_key(village) != normalize_key(district):
            candidates.append(f"{cleaned_address}, {village}, {district}, Kota Malang, Jawa Timur, Indonesia")
        elif district:
            candidates.append(f"{cleaned_address}, {district}, Kota Malang, Jawa Timur, Indonesia")
    elif cleaned_address:
        candidates.append(f"{cleaned_address}, Kota Malang, Jawa Timur, Indonesia")
    elif area_text:
        candidates.append(area_scope)

    queries = []
    seen = set()
    for base in candidates:
        key = normalize_key(base)
        if key not in seen:
            seen.add(key)
            queries.append(base)

    return queries


def build_place_search_queries(address, area=""):
    address_text = normalize_text(address)
    area_text = normalize_text(area)
    cleaned_address = clean_address_for_geocode(address_text, area_text)
    _, district, village = get_area_context(area_text)
    area_parts = [
        part
        for part in (village, district, "Kota Malang", "Jawa Timur", "Indonesia")
        if normalize_text(part)
    ]
    area_scope = ", ".join(area_parts)
    candidates = []

    if address_text:
        candidates.append(f"{address_text}, Kota Malang, Jawa Timur, Indonesia")
        if area_scope:
            candidates.append(f"{address_text}, {area_scope}")

    if cleaned_address and normalize_key(cleaned_address) != normalize_key(address_text):
        candidates.append(f"{cleaned_address}, Kota Malang, Jawa Timur, Indonesia")
        if area_scope:
            candidates.append(f"{cleaned_address}, {area_scope}")

    # Jika alamat berisi nama tempat lalu nama jalan, baris pertama sering cukup
    # kuat untuk Google Places, misalnya "PT X\nJl Y" atau "Toko Z Jl Y".
    first_line = re.split(r"[\r\n]+|_x000d_", address_text, flags=re.IGNORECASE)[0].strip()
    if first_line and normalize_key(first_line) != normalize_key(address_text):
        candidates.append(f"{first_line}, Kota Malang, Jawa Timur, Indonesia")
        if area_scope:
            candidates.append(f"{first_line}, {area_scope}")

    queries = []
    seen = set()
    for base in candidates:
        key = normalize_key(base)
        if key not in seen:
            seen.add(key)
            queries.append(base)

    return queries


# Mengambil key wilayah penting dari kolom kota untuk validasi hasil geocoding.
def get_area_match_keys(area):
    parts = split_wilayah_parts(area)
    keys = []
    for part in reversed(parts):
        key = normalize_key(part)
        if key and key not in {"kotamalang", "malang", "jawatimur", "indonesia"}:
            keys.append(key)
    return keys


# Memberi skor hasil geocoding dengan prioritas kecocokan kelurahan/kecamatan.
def score_geocode_result(result, index, area):
    location_data = result.get("geometry", {}).get("location", {})
    lat = location_data.get("lat")
    lon = location_data.get("lng")
    if lat is None or lon is None:
        return None

    lon = float(lon)
    lat = float(lat)
    if not (
        MALANG_BOUNDS["min_lng"] <= lon <= MALANG_BOUNDS["max_lng"] and
        MALANG_BOUNDS["min_lat"] <= lat <= MALANG_BOUNDS["max_lat"]
    ):
        return None

    formatted_address = normalize_key(result.get("formatted_address", ""))
    distance_center = ((lon - 112.6303) ** 2 + (lat + 7.9829) ** 2) ** 0.5
    score = 100 - index - (distance_center * 8)
    result_types = set(result.get("types", []))
    precise_types = {
        "street_address",
        "premise",
        "subpremise",
        "establishment",
        "point_of_interest",
        "route",
    }
    generic_types = {
        "administrative_area_level_3",
        "administrative_area_level_4",
        "locality",
        "political",
    }

    if result_types & precise_types:
        score += 25
    if result_types and result_types.issubset(generic_types):
        score -= 60

    area_keys = get_area_match_keys(area)
    if area_keys:
        matched_keys = [key for key in area_keys if key in formatted_address]
        if matched_keys:
            score += 35 + (10 * len(matched_keys))
        else:
            score -= 45

    if "malang" in formatted_address:
        score += 10

    return score, [lon, lat]


def score_place_result(result, index, area, address):
    location_data = result.get("geometry", {}).get("location", {})
    lat = location_data.get("lat")
    lon = location_data.get("lng")
    if lat is None or lon is None:
        return None

    lon = float(lon)
    lat = float(lat)
    if not (
        MALANG_BOUNDS["min_lng"] <= lon <= MALANG_BOUNDS["max_lng"] and
        MALANG_BOUNDS["min_lat"] <= lat <= MALANG_BOUNDS["max_lat"]
    ):
        return None

    name_key = normalize_key(result.get("name", ""))
    formatted_address = normalize_key(result.get("formatted_address", ""))
    searchable_result = normalize_key(f"{result.get('name', '')} {result.get('formatted_address', '')}")
    address_key = normalize_key(address)
    distance_center = ((lon - 112.6303) ** 2 + (lat + 7.9829) ** 2) ** 0.5
    score = 115 - index - (distance_center * 8)
    result_types = set(result.get("types", []))
    generic_types = {
        "administrative_area_level_3",
        "administrative_area_level_4",
        "locality",
        "political",
    }

    if result.get("business_status") in {"OPERATIONAL", "CLOSED_TEMPORARILY"}:
        score += 12
    if name_key and name_key in address_key:
        score += 35
    elif address_key and address_key in searchable_result:
        score += 20

    if result_types and result_types.issubset(generic_types):
        score -= 70

    area_keys = get_area_match_keys(area)
    if area_keys:
        matched_keys = [key for key in area_keys if key in formatted_address]
        if matched_keys:
            score += 20 + (8 * len(matched_keys))
        else:
            score -= 20

    if "malang" in formatted_address:
        score += 10

    return score, [lon, lat]


# Menggabungkan alamat dan wilayah menjadi alamat lengkap untuk tampilan dan geocoding.
def build_full_address(address, area=""):
    address_text = clean_address_for_geocode(address, area)
    area_text = normalize_text(area)
    if address_text and area_text:
        return f"{address_text}, {area_text}"
    return address_text or area_text


# Membuat URL Google Maps Directions sesuai urutan rute hasil optimasi.
def build_google_maps_navigation_url(route_data):
    navigable_points = [
        item
        for item in route_data
        if item.get("lat") is not None and item.get("lng") is not None
    ]
    if len(navigable_points) < 2:
        return ""

    # Mengubah satu titik rute menjadi format koordinat yang diterima Google Maps Directions.
    def format_point(point):
        return f"{float(point['lat'])},{float(point['lng'])}"

    ordered_points = [format_point(point) for point in navigable_points]
    return "https://www.google.com/maps/dir/" + "/".join(ordered_points) + "/?travelmode=driving"


# Mengubah catatan durasi proses menjadi daftar tahapan yang ditampilkan di UI.
def build_process_steps(timings):
    step_labels = [
        ("preprocessing", "Preprocessing Data"),
        ("geocoding", "Geocoding Alamat"),
        ("matrix + GA", "Distance Matrix dan GA"),
        ("geometry rute", "Visualisasi Rute"),
    ]
    return [
        {
            "title": title,
            "seconds": round(timings.get(key, 0), 2)
        }
        for key, title in step_labels
        if key in timings
    ]


# Mengubah koordinat internal [lon, lat] menjadi format lat,lng milik Google.
def format_google_latlng(coord):
    return f"{float(coord[1])},{float(coord[0])}"


# Mendecode encoded polyline Google Directions menjadi daftar koordinat.
def decode_google_polyline(polyline):
    coords = []
    index = 0
    lat = 0
    lng = 0

    while index < len(polyline):
        for coord_index in range(2):
            shift = 0
            result = 0
            while True:
                byte = ord(polyline[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break

            delta = ~(result >> 1) if result & 1 else result >> 1
            if coord_index == 0:
                lat += delta
            else:
                lng += delta

        coords.append([lat / 1e5, lng / 1e5])

    return coords


# Mengambil koordinat fallback berdasarkan wilayah jika geocoding tidak menemukan hasil.
def get_area_fallback_coord(area):
    area_key = normalize_key(area)
    fallback_coords = {
        "blimbing": [112.6478, -7.9397],
        "polehan": [112.6405, -7.9820],
        "pandanwangi": [112.6570, -7.9435],
        "arjosari": [112.6485, -7.9240],
        "purwodadi": [112.6460, -7.9295],
        "purwantoro": [112.6370, -7.9515],
        "kesatrian": [112.6375, -7.9710],
        "bunulrejo": [112.6410, -7.9615],
        "balearjosari": [112.6550, -7.9135],
        "polowijen": [112.6420, -7.9285],
        "jodipan": [112.6370, -7.9865],
        "klojen": [112.6303, -7.9770],
        "gadingkasri": [112.6175, -7.9585],
        "penanggungan": [112.6220, -7.9535],
        "kauman": [112.6290, -7.9825],
        "samaan": [112.6260, -7.9700],
        "kiduldalem": [112.6320, -7.9840],
        "lowokwaru": [112.6210, -7.9465],
        "tunggulwulung": [112.6070, -7.9250],
        "tunjungsekar": [112.6200, -7.9295],
        "merjosari": [112.6040, -7.9445],
        "sumbersari": [112.6160, -7.9555],
        "dinoyo": [112.6080, -7.9455],
        "mojolangu": [112.6285, -7.9330],
        "tlogomas": [112.6000, -7.9395],
        "jatimulyo": [112.6230, -7.9390],
        "sukun": [112.6150, -8.0050],
        "ciptomulyo": [112.6240, -7.9995],
        "pisangcandi": [112.6070, -7.9725],
        "bandulan": [112.6015, -7.9905],
        "gadang": [112.6255, -8.0170],
        "kedungkandang": [112.6530, -7.9985],
        "sawojajar": [112.6590, -7.9730],
        "bumiayu": [112.6385, -8.0215],
        "kotalama": [112.6340, -7.9975],
        "mergosono": [112.6370, -8.0065],
        "lesanpuro": [112.6720, -7.9835],
        "arjowinangun": [112.6480, -8.0230],
        "buring": [112.6550, -8.0350],
        "madyopuro": [112.6720, -7.9685],
    }

    area_parts = [
        normalize_key(part)
        for part in normalize_text(area).split(",")
        if normalize_key(part)
    ]
    for key in reversed(area_parts):
        if key in fallback_coords:
            return fallback_coords[key]

    for key, coord in fallback_coords.items():
        if key in area_key:
            return coord

    return [112.6303, -7.9829]


# Menggeser fallback secara kecil dan konsisten per alamat agar marker tidak menumpuk di pusat wilayah.
def spread_fallback_coord_by_address(coord, address):
    key = normalize_key(address)
    if not key:
        return coord

    seed = sum((index + 1) * ord(char) for index, char in enumerate(key))
    angle = (seed % 360) * math.pi / 180
    radius = 0.0015 + ((seed % 7) * 0.00018)
    return [
        float(coord[0]) + (math.cos(angle) * radius),
        float(coord[1]) + (math.sin(angle) * radius),
    ]


# Melakukan geocoding satu lokasi menggunakan Google Geocoding API dan cache lokal.
def geocode(location):
    require_google_api_key()

    if isinstance(location, dict):
        address = location.get("alamat", "")
        area = location.get("kota", "")
    else:
        address = location
        area = ""

    query_texts = build_geocode_queries(address, area)
    place_query_texts = build_place_search_queries(address, area)
    cache_key = f"{GEOCODE_CACHE_VERSION}|{normalize_address('|'.join(query_texts + place_query_texts))}"
    with CACHE_LOCK:
        if cache_key in GEOCODE_CACHE:
            return GEOCODE_CACHE[cache_key]

    geocode_url = "https://maps.googleapis.com/maps/api/geocode/json"
    places_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"

    best_score = -1
    best_coord = None

    address_key = normalize_key(address)
    city, _, _ = get_area_context(area)
    locality = "Malang" if "malang" in normalize_key(city) else city

    for query_text in place_query_texts:
        params = {
            "query": query_text,
            "location": "-7.9829,112.6303",
            "radius": 25000,
            "region": "id",
            "key": GOOGLE_MAPS_API_KEY,
        }

        try:
            res = requests.get(places_url, params=params, timeout=8).json()
            if res.get("status") not in {"OK", "ZERO_RESULTS"}:
                continue

            for index, result in enumerate(res.get("results", [])[:5]):
                scored_result = score_place_result(result, index, area, address)
                if scored_result is None:
                    continue

                score, coord = scored_result
                if score > best_score:
                    best_score = score
                    best_coord = coord

        except Exception:
            pass

    for query_text in query_texts:
        params = {
            "address": query_text,
            "components": f"country:ID|locality:{locality}",
            "region": "id",
            "bounds": "-8.10,112.55|-7.85,112.75",
            "key": GOOGLE_MAPS_API_KEY,
        }

        try:
            res = requests.get(geocode_url, params=params, timeout=8).json()
            if res.get("status") not in {"OK", "ZERO_RESULTS"}:
                continue

            for index, result in enumerate(res.get("results", [])):
                scored_result = score_geocode_result(result, index, area)
                if scored_result is None:
                    continue

                score, coord = scored_result
                if address_key and address_key not in normalize_key(query_text):
                    score -= 35
                if result.get("partial_match"):
                    score -= 25

                if score > best_score:
                    best_score = score
                    best_coord = coord

        except Exception:
            pass

    if best_coord and best_score >= 20:
        with CACHE_LOCK:
            GEOCODE_CACHE[cache_key] = best_coord
        return best_coord

    fallback_coord = spread_fallback_coord_by_address(
        get_area_fallback_coord(area),
        address
    )
    with CACHE_LOCK:
        GEOCODE_CACHE[cache_key] = fallback_coord
    return fallback_coord  # fallback pusat kota


# Melakukan geocoding banyak lokasi secara paralel lalu menyimpan cache.
def geocode_locations(locations):
    if not locations:
        return []

    with ThreadPoolExecutor(max_workers=GEOCODE_WORKERS) as executor:
        coords = list(executor.map(geocode, locations))

    with CACHE_LOCK:
        save_json_cache(GEOCODE_CACHE_FILE, GEOCODE_CACHE)

    return coords

# MATRIX API
# Mengambil matrix jarak dan waktu jalan aktual antar titik dari Google Distance Matrix API.
def get_matrix(coords):
    if not isinstance(coords, list) or len(coords) < 2:
        raise Exception("Google Distance Matrix error: coords must be a list of at least 2 coordinate pairs")
    if len(coords) > MAX_ROUTE_POINTS:
        raise Exception(f"Google Distance Matrix error: maksimal {MAX_ROUTE_POINTS} titik per rute")

    normalized = []
    for c in coords:
        if not isinstance(c, (list, tuple)) or len(c) != 2:
            raise Exception("Google Distance Matrix error: each location must be a [lon, lat] pair")
        try:
            lon = float(c[0])
            lat = float(c[1])
        except Exception:
            raise Exception("Google Distance Matrix error: location values must be numeric")
        normalized.append([lon, lat])

    cache_key = make_coords_cache_key(normalized)
    if cache_key in MATRIX_CACHE:
        return MATRIX_CACHE[cache_key]

    total_points = len(normalized)
    distance_matrix = [[0 for _ in range(total_points)] for _ in range(total_points)]
    duration_matrix = [[0 for _ in range(total_points)] for _ in range(total_points)]
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"

    require_google_api_key()

    for origin_start in range(0, total_points, GOOGLE_MATRIX_BATCH_SIZE):
        origin_indexes = range(origin_start, min(origin_start + GOOGLE_MATRIX_BATCH_SIZE, total_points))
        origins = [format_google_latlng(normalized[index]) for index in origin_indexes]

        for dest_start in range(0, total_points, GOOGLE_MATRIX_BATCH_SIZE):
            dest_indexes = range(dest_start, min(dest_start + GOOGLE_MATRIX_BATCH_SIZE, total_points))
            destinations = [format_google_latlng(normalized[index]) for index in dest_indexes]
            params = {
                "origins": "|".join(origins),
                "destinations": "|".join(destinations),
                "mode": "driving",
                "units": "metric",
                "key": GOOGLE_MAPS_API_KEY,
            }
            response = requests.get(url, params=params, timeout=20)
            if response.status_code != 200:
                raise Exception("Google Distance Matrix error: " + response.text)

            data = response.json()
            if data.get("status") != "OK":
                raise Exception("Google Distance Matrix error: " + data.get("error_message", data.get("status", "")))

            for row_offset, row in enumerate(data.get("rows", [])):
                origin_index = origin_start + row_offset
                for col_offset, element in enumerate(row.get("elements", [])):
                    dest_index = dest_start + col_offset
                    if origin_index == dest_index:
                        continue
                    if element.get("status") != "OK":
                        raise Exception(
                            "Google Distance Matrix error: rute jalan tidak tersedia "
                            f"dari titik {origin_index + 1} ke titik {dest_index + 1} "
                            f"({element.get('status', 'UNKNOWN')})"
                        )
                    distance_matrix[origin_index][dest_index] = element["distance"]["value"]
                    duration_matrix[origin_index][dest_index] = element["duration"]["value"]

    matrix_result = (distance_matrix, duration_matrix)
    MATRIX_CACHE[cache_key] = matrix_result
    save_json_cache(MATRIX_CACHE_FILE, MATRIX_CACHE)
    return matrix_result

# DIRECTIONS API - untuk mendapatkan geometri rute sebenarnya
# Mengambil geometri arah jalan antara dua koordinat dari Google Directions API.
def get_directions(start_coord, end_coord):
    try:
        require_google_api_key()
        url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            "origin": format_google_latlng(start_coord),
            "destination": format_google_latlng(end_coord),
            "mode": "driving",
            "key": GOOGLE_MAPS_API_KEY,
        }
        r = requests.get(url, params=params, timeout=20)
    except Exception as exc:
        print(f"Google Directions API tidak tersedia: {exc}")
        return None

    if r.status_code != 200:
        print(f"Google Directions API error: {r.text}")
        return None

    data = r.json()
    if data.get("status") == "OK" and data.get("routes"):
        encoded = data["routes"][0].get("overview_polyline", {}).get("points")
        if encoded:
            return decode_google_polyline(encoded)
    return None


# Menyusun geometri rute lengkap dari urutan koordinat yang sudah dioptimasi.
def get_route_geometry(coords_list):
    if not isinstance(coords_list, list) or len(coords_list) < 2:
        return None
    if len(coords_list) > MAX_ROUTE_POINTS:
        coords_list = coords_list[:MAX_ROUTE_POINTS]

    cache_key = make_coords_cache_key(coords_list)
    if cache_key in ROUTE_GEOMETRY_CACHE:
        return ROUTE_GEOMETRY_CACHE[cache_key]

    try:
        require_google_api_key()
    except Exception as exc:
        print(f"Google route geometry tidak tersedia: {exc}")
        return None

    url = "https://maps.googleapis.com/maps/api/directions/json"
    route_geometry = []

    for start_index in range(0, len(coords_list) - 1, GOOGLE_DIRECTIONS_MAX_COORDS - 1):
        chunk = coords_list[start_index:start_index + GOOGLE_DIRECTIONS_MAX_COORDS]
        if len(chunk) < 2:
            continue

        params = {
            "origin": format_google_latlng(chunk[0]),
            "destination": format_google_latlng(chunk[-1]),
            "mode": "driving",
            "key": GOOGLE_MAPS_API_KEY,
        }
        if len(chunk) > 2:
            params["waypoints"] = "|".join(format_google_latlng(coord) for coord in chunk[1:-1])

        try:
            r = requests.get(url, params=params, timeout=20)
        except Exception as exc:
            print(f"Google route geometry tidak tersedia: {exc}")
            return None
        if r.status_code != 200:
            print(f"Google route geometry error: {r.text}")
            return None

        data = r.json()
        if data.get("status") != "OK" or not data.get("routes"):
            print(f"Google route geometry error: {data.get('error_message', data.get('status'))}")
            return None

        encoded = data["routes"][0].get("overview_polyline", {}).get("points")
        if not encoded:
            return None

        decoded_chunk = decode_google_polyline(encoded)
        if route_geometry and decoded_chunk:
            decoded_chunk = decoded_chunk[1:]
        route_geometry.extend(decoded_chunk)

    ROUTE_GEOMETRY_CACHE[cache_key] = route_geometry
    save_json_cache(ROUTE_GEOMETRY_CACHE_FILE, ROUTE_GEOMETRY_CACHE)
    return route_geometry

# Menghitung total jarak satu kandidat rute berdasarkan matrix jarak.
def total_distance(route, matrix):
    # meter
    return sum(matrix[route[i]][route[i+1]]
               for i in range(len(route)-1))

# Menghitung total waktu satu kandidat rute berdasarkan matrix durasi.
def total_time(route, time_matrix):
    # menit
    return sum(time_matrix[route[i]][route[i+1]] / 60
               for i in range(len(route)-1))

# Menghitung nilai fitness rute dengan menggabungkan jarak dan waktu.
def calculate_fitness(route, dist_matrix, time_matrix):
    D = total_distance(route, dist_matrix)  # meter
    T = total_time(route, time_matrix)     # menit
    return 1000 / (D + T)

def compute_route_totals(route, dist_matrix, time_matrix):
    if not route or len(route) < 2:
        return 0.0, 0.0
    total_dist_km = (
        sum(dist_matrix[route[i]][route[i + 1]] for i in range(len(route) - 1)) / 1000
    )
    total_time_min = (
        sum(time_matrix[route[i]][route[i + 1]] for i in range(len(route) - 1)) / 60
    )
    return float(total_dist_km), float(total_time_min)

def compute_improvement_pct(baseline_value, optimized_value):
    try:
        baseline_value = float(baseline_value)
        optimized_value = float(optimized_value)
    except Exception:
        return None
    if baseline_value <= 0:
        return None
    return ((baseline_value - optimized_value) / baseline_value) * 100.0

# //Kode CPLEX: util untuk menghitung GAP (%) GA vs solusi exact CPLEX
def compute_gap_pct(exact_value, heuristic_value):
    try:
        exact_value = float(exact_value)
        heuristic_value = float(heuristic_value)
    except Exception:
        return None
    if exact_value <= 0:
        return None
    return ((heuristic_value - exact_value) / exact_value) * 100.0

# //Kode CPLEX: solver exact TSP (path) menggunakan docplex + IBM ILOG CPLEX
# Catatan: butuh install `docplex` dan CPLEX Runtime terpasang.
def solve_tsp_path_with_cplex(dist_matrix, start_index=0, time_limit_seconds=30):
    def _find_cplex_exe():
        candidates = []
        env_exe = os.environ.get("CPLEX_EXE")
        if env_exe:
            candidates.append(env_exe.strip().strip('"'))
        # Default lokasi umum (Community Edition 22.1.2, dll)
        candidates.extend([
            r"C:\Program Files\IBM\ILOG\CPLEX_Studio_Community2212\cplex\bin\x64_win64\cplex.exe",
            r"C:\Program Files\IBM\ILOG\CPLEX_Studio_Community2211\cplex\bin\x64_win64\cplex.exe",
            r"C:\Program Files\IBM\ILOG\CPLEX_Studio2212\cplex\bin\x64_win64\cplex.exe",
            r"C:\Program Files\IBM\ILOG\CPLEX_Studio2211\cplex\bin\x64_win64\cplex.exe",
        ])
        for path in candidates:
            try:
                if path and os.path.exists(path):
                    return path
            except Exception:
                continue
        return None

    def _solve_with_docplex():
        from docplex.mp.model import Model

        if not dist_matrix or not isinstance(dist_matrix, list):
            return []
        n = len(dist_matrix)
        if n <= 0:
            return []
        local_start_index = start_index
        if local_start_index < 0 or local_start_index >= n:
            local_start_index = 0

        dummy = n
        nodes = list(range(n + 1))
        big_m = 10**12

        def cost(i, j):
            if i == j:
                return big_m
            if j == dummy and i != dummy:
                return 0
            if i == dummy and j == local_start_index:
                return 0
            if i == dummy or j == dummy:
                return big_m
            value = dist_matrix[i][j]
            if value is None:
                return big_m
            try:
                value = float(value)
            except Exception:
                return big_m
            return value

        mdl = Model(name="tsp_path")
        if time_limit_seconds is not None:
            try:
                mdl.set_time_limit(float(time_limit_seconds))
            except Exception:
                pass

        x = {(i, j): mdl.binary_var(name=f"x_{i}_{j}") for i in nodes for j in nodes if i != j}
        u = {i: mdl.continuous_var(lb=0, ub=n, name=f"u_{i}") for i in nodes}

        mdl.minimize(mdl.sum(cost(i, j) * x[(i, j)] for (i, j) in x))

        for i in nodes:
            mdl.add_constraint(mdl.sum(x[(i, j)] for j in nodes if i != j) == 1)
        for j in nodes:
            mdl.add_constraint(mdl.sum(x[(i, j)] for i in nodes if i != j) == 1)

        for i in range(n):
            if i == local_start_index:
                continue
            for j in range(n):
                if i == j or j == local_start_index:
                    continue
                mdl.add_constraint(u[i] - u[j] + (n * x[(i, j)]) <= n - 1)

        mdl.add_constraint(u[local_start_index] == 0)

        sol = mdl.solve(log_output=False)
        if sol is None:
            raise RuntimeError("CPLEX gagal menemukan solusi TSP (tidak ada solusi atau time limit).")

        succ = {}
        for (i, j), var in x.items():
            try:
                val = sol.get_value(var)
            except Exception:
                continue
            if val is not None and val > 0.5:
                succ[i] = j

        if dummy not in succ:
            raise RuntimeError("CPLEX solution invalid: dummy node tidak punya successor.")

        path = [local_start_index]
        current = local_start_index
        visited = {local_start_index}
        while True:
            nxt = succ.get(current)
            if nxt is None:
                raise RuntimeError("CPLEX solution invalid: successor tidak lengkap.")
            if nxt == dummy:
                break
            if nxt in visited:
                raise RuntimeError("CPLEX solution invalid: subtour terdeteksi pada path.")
            path.append(nxt)
            visited.add(nxt)
            current = nxt

        if len(path) != n:
            missing = [i for i in range(n) if i not in visited]
            raise RuntimeError(f"CPLEX solution invalid: node belum dikunjungi: {missing}")

        return path

    def _write_tsp_path_lp(dist_matrix, start_index, time_limit_seconds=None):
        n = len(dist_matrix)
        dummy = n
        nodes = list(range(n + 1))
        big_m = 10**12

        def cost(i, j):
            if i == j:
                return big_m
            if j == dummy and i != dummy:
                return 0
            if i == dummy and j == start_index:
                return 0
            if i == dummy or j == dummy:
                return big_m
            value = dist_matrix[i][j]
            if value is None:
                return big_m
            try:
                return float(value)
            except Exception:
                return big_m

        lines = []
        lines.append("\\ TSP path (dummy end) generated by app.py")
        lines.append("Minimize")
        obj_terms = []
        for i in nodes:
            for j in nodes:
                if i == j:
                    continue
                c = cost(i, j)
                if c == 0:
                    obj_terms.append(f"+ 0 x_{i}_{j}")
                else:
                    obj_terms.append(f"+ {c} x_{i}_{j}")
        lines.append(" obj: " + " ".join(obj_terms))
        lines.append("Subject To")

        for i in nodes:
            terms = [f"x_{i}_{j}" for j in nodes if j != i]
            lines.append(f" out_{i}: " + " + ".join(terms) + " = 1")
        for j in nodes:
            terms = [f"x_{i}_{j}" for i in nodes if i != j]
            lines.append(f" in_{j}: " + " + ".join(terms) + " = 1")

        for i in range(n):
            if i == start_index:
                continue
            for j in range(n):
                if i == j or j == start_index:
                    continue
                lines.append(f" mtz_{i}_{j}: u_{i} - u_{j} + {n} x_{i}_{j} <= {n-1}")

        lines.append(f" u_start: u_{start_index} = 0")
        lines.append("Bounds")
        for i in range(n):
            lines.append(f" 0 <= u_{i} <= {n}")
        lines.append("Binary")
        for i in nodes:
            for j in nodes:
                if i == j:
                    continue
                lines.append(f" x_{i}_{j}")
        lines.append("End")
        return "\n".join(lines) + "\n"

    def _parse_cplex_sol_for_successors(sol_path):
        # CPLEX .sol is XML; we only need x_i_j vars with value ~1
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(sol_path)
            root = tree.getroot()
            succ = {}
            for var in root.iter("variable"):
                name = var.attrib.get("name", "")
                if not name.startswith("x_"):
                    continue
                val = var.attrib.get("value")
                try:
                    v = float(val)
                except Exception:
                    continue
                if v <= 0.5:
                    continue
                parts = name.split("_")
                if len(parts) != 3:
                    continue
                try:
                    i = int(parts[1])
                    j = int(parts[2])
                except Exception:
                    continue
                succ[i] = j
            return succ
        except Exception as exc:
            raise RuntimeError(f"Gagal parsing file solusi CPLEX: {exc}") from exc

    def _solve_with_cplex_cli():
        if not dist_matrix or not isinstance(dist_matrix, list):
            return []
        n = len(dist_matrix)
        if n <= 0:
            return []
        local_start_index = start_index
        if local_start_index < 0 or local_start_index >= n:
            local_start_index = 0

        cplex_exe = _find_cplex_exe()
        if not cplex_exe:
            raise RuntimeError(
                "CPLEX CLI tidak ditemukan. Set env var CPLEX_EXE ke path cplex.exe "
                "atau pastikan CPLEX Studio ter-install."
            )

        lp_text = _write_tsp_path_lp(
            dist_matrix,
            start_index=local_start_index,
            time_limit_seconds=time_limit_seconds,
        )
        with tempfile.TemporaryDirectory(prefix="tsp_cplex_") as td:
            lp_path = os.path.join(td, "tsp.lp")
            sol_path = os.path.join(td, "tsp.sol")
            with open(lp_path, "w", encoding="utf-8") as fh:
                fh.write(lp_text)

            # Use CPLEX interactive commands
            # Note: command names differ; use "set timelimit" for interactive optimizer.
            cmd_script_lines = []
            cmd_script_lines.append(f'read "{lp_path}"')
            if time_limit_seconds is not None:
                try:
                    tl = float(time_limit_seconds)
                    if tl > 0:
                        cmd_script_lines.append(f"set timelimit {tl}")
                except Exception:
                    pass
            cmd_script_lines.append("optimize")
            cmd_script_lines.append(f'write "{sol_path}"')
            cmd_script_lines.append("quit")
            cmd_script = "\n".join(cmd_script_lines) + "\n"

            proc = subprocess.run(
                [cplex_exe],
                input=cmd_script,
                text=True,
                capture_output=True,
                timeout=max(5, int(time_limit_seconds or 30) + 15),
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                stdout = (proc.stdout or "").strip()
                msg = stderr if stderr else stdout
                raise RuntimeError(f"CPLEX CLI gagal (code {proc.returncode}): {msg[:800]}")

            if not os.path.exists(sol_path):
                raise RuntimeError("CPLEX tidak menghasilkan file solusi (.sol).")

            succ = _parse_cplex_sol_for_successors(sol_path)

        dummy = n
        if dummy not in succ:
            raise RuntimeError("CPLEX solution invalid: dummy node tidak punya successor.")

        path = [local_start_index]
        current = local_start_index
        visited = {local_start_index}
        while True:
            nxt = succ.get(current)
            if nxt is None:
                raise RuntimeError("CPLEX solution invalid: successor tidak lengkap.")
            if nxt == dummy:
                break
            if nxt in visited:
                raise RuntimeError("CPLEX solution invalid: subtour terdeteksi pada path.")
            path.append(nxt)
            visited.add(nxt)
            current = nxt

        if len(path) != n:
            missing = [i for i in range(n) if i not in visited]
            raise RuntimeError(f"CPLEX solution invalid: node belum dikunjungi: {missing}")

        return path

    # Prefer docplex if tersedia (lebih cepat/rapi), fallback ke CPLEX CLI agar tetap jalan.
    try:
        return _solve_with_docplex()
    except Exception:
        return _solve_with_cplex_cli()

def random_search_best_route(dist_matrix, time_matrix, iterations=200, start_index=0, seed=None):
    if not dist_matrix or not isinstance(dist_matrix, list):
        return [], 0
    n = len(dist_matrix)
    if n <= 0:
        return [], 0
    if start_index < 0 or start_index >= n:
        start_index = 0

    try:
        iterations = int(iterations)
    except Exception:
        iterations = 200
    iterations = max(1, iterations)

    rng = random.Random()
    if seed is None:
        try:
            seed = time.time_ns()
        except Exception:
            seed = None
    if seed is not None:
        try:
            rng.seed(int(seed))
        except Exception:
            pass

    nodes = [idx for idx in range(n) if idx != start_index]
    if not nodes:
        return [start_index], 0

    best_route = None
    best_key = None
    actual_iterations = 0

    for _ in range(iterations):
        actual_iterations += 1
        perm = nodes[:]
        rng.shuffle(perm)
        candidate_route = [start_index] + perm

        dist_km, time_min = compute_route_totals(candidate_route, dist_matrix, time_matrix)
        key = (dist_km, time_min)
        if best_key is None or key < best_key:
            best_key = key
            best_route = candidate_route

    return best_route or [start_index], actual_iterations


# def pmx_crossover(p1, p2):
#     size = len(p1)

#     if size <= 2:
#         return p1[:], p2[:]

#     cx1, cx2 = sorted(random.sample(range(1, size), 2))

#     c1 = [None] * size
#     c2 = [None] * size

#     c1[cx1:cx2] = p1[cx1:cx2]
#     c2[cx1:cx2] = p2[cx1:cx2]

#     def fill(child, parent):
#         for i in range(size):
#             if child[i] is None:
#                 for gene in parent:
#                     if gene not in child:
#                         child[i] = gene
#                         break
#         return child

#     c1[0] = 0
#     c2[0] = 0

#     return fill(c1, p2), fill(c2, p1)

# Melakukan crossover PMX untuk menghasilkan anak rute dari dua parent.
def pmx_crossover(p1, p2):
    size = len(p1)

    if size <= 2:
        return p1[:]  # hanya 1 child

    cx1, cx2 = sorted(random.sample(range(1, size), 2))

    child = [None] * size

    # ambil sebagian gen dari parent 1
    child[cx1:cx2] = p1[cx1:cx2]

    # isi sisanya dari parent 2
    # Mengisi gen kosong pada anak crossover menggunakan urutan dari parent.
    def fill(child, parent):
        for i in range(size):
            if child[i] is None:
                for gene in parent:
                    if gene not in child:
                        child[i] = gene
                        break
        return child

    child[0] = 0  # titik awal tetap

    return fill(child, p2)

# Melakukan mutasi dengan menukar dua titik selain titik awal.
def swap_mutation(ind):
    if len(ind) <= 2:
        return ind

    i, j = random.sample(range(1, len(ind)), 2)
    ind[i], ind[j] = ind[j], ind[i]
    return ind

# Memilih individu terbaik agar populasi generasi berikutnya tetap berkualitas.
def selection_elitism(pop, fitness, elite):
    ranked = sorted(zip(pop, fitness),
                    key=lambda x: x[1],
                    reverse=True)
    return [x[0] for x in ranked[:elite]]


# Memilih parent menggunakan tournament selection.
def tournament_selection(population, fitness, tournament_size=3):
    selected_indexes = random.sample(
        range(len(population)),
        min(tournament_size, len(population))
    )
    best_index = max(selected_indexes, key=lambda idx: fitness[idx])
    return population[best_index]


def log_ga_runtime_config(pop_size, generations, crossover_rate, mutation_rate, quiet=False):
    if quiet:
        return
    crossover_count = int(crossover_rate * pop_size)
    mutation_count = int(mutation_rate * pop_size)

    print("\nParameter algoritma genetika yang dipakai:")
    print(f"- Generasi : {generations}")
    print(f"- Populasi : {pop_size}")
    print(f"- Cr       : {crossover_rate} ({crossover_count} crossover/generasi)")
    print(f"- Mr       : {mutation_rate} ({mutation_count} mutasi/generasi)")


# GA
# Menjalankan algoritma genetika untuk mencari urutan kunjungan terbaik.
def genetic_algorithm(coords,
                      pop_size=GA_POP_SIZE,
                      generations=GA_GENERATIONS,
                      crossover_rate=GA_CROSSOVER_RATE, 
                      mutation_rate=GA_MUTATION_RATE,
                      seed=None,
                      quiet=False):

    # Jika seed diberikan, hasil GA jadi deterministik untuk kebutuhan eksperimen/debug.
    # Jika seed=None, GA memakai state random global (akan berubah tiap eksekusi).
    if seed is not None:
        try:
            random.seed(int(seed))
        except Exception:
            pass

    n = len(coords)
    dist_matrix, time_matrix = get_matrix(coords)

    population = [[0] + random.sample(range(1, n), n-1)
                  for _ in range(pop_size)]

    log_ga_runtime_config(
        pop_size,
        generations,
        crossover_rate,
        mutation_rate,
        quiet=quiet,
    )

    generation_logs = []
    fitness_summary = {
        "population_total_fitness": 0,
        "crossover_total_fitness": 0,
        "mutation_total_fitness": 0,
        "generation_total_fitness": 0,
        "population_size": pop_size,
        "generations": generations,
        "crossover_rate": crossover_rate,
        "mutation_rate": mutation_rate,
        "crossover_count": int(crossover_rate * pop_size),
        "mutation_count": int(mutation_rate * pop_size),
    }

    for gen in range(generations):
        fitness = [calculate_fitness(ind, dist_matrix, time_matrix) for ind in population]
        population_total_fitness = sum(fitness)

        offspring = []

        crossover_iterations = int(crossover_rate * pop_size)

        for _ in range(crossover_iterations):
            p1 = tournament_selection(population, fitness)
            p2 = tournament_selection(population, fitness)
            child = pmx_crossover(p1, p2)
            offspring.append(child)

        crossover_total_fitness = sum(
            calculate_fitness(ind, dist_matrix, time_matrix)
            for ind in offspring
        ) if offspring else 0

        mutation_iterations = int(mutation_rate * pop_size)
        if offspring:
            for ind in random.sample(offspring, min(mutation_iterations, len(offspring))):
                swap_mutation(ind)

        mutation_total_fitness = sum(
            calculate_fitness(ind, dist_matrix, time_matrix)
            for ind in offspring
        ) if offspring else 0

        combined = population + offspring

        fitness_combined = [
            calculate_fitness(ind, dist_matrix, time_matrix)
            for ind in combined
        ]

        population = selection_elitism(
            combined,
            fitness_combined,
            elite=pop_size
        )

        generation_fitness = [
            calculate_fitness(ind, dist_matrix, time_matrix)
            for ind in population
        ]

        generation_total_fitness = sum(generation_fitness)
        fitness_summary["population_total_fitness"] += population_total_fitness
        fitness_summary["crossover_total_fitness"] += crossover_total_fitness
        fitness_summary["mutation_total_fitness"] += mutation_total_fitness
        fitness_summary["generation_total_fitness"] += generation_total_fitness

        # Jika quiet=True, hindari menyimpan log per generasi untuk menghemat memori.
        # Jika quiet=False, simpan semua generasi 1..selesai (tanpa kelipatan).
        if not quiet:
            overall_generation_total = (
                population_total_fitness
                + crossover_total_fitness
                + mutation_total_fitness
                + generation_total_fitness
            )
            generation_logs.append({
                "generation": gen + 1,
                "population_total_fitness": population_total_fitness,
                "crossover_total_fitness": crossover_total_fitness,
                "mutation_total_fitness": mutation_total_fitness,
                "generation_total_fitness": generation_total_fitness,
                "overall_total_fitness": overall_generation_total,
                "best_fitness": max(generation_fitness),
                "avg_fitness": generation_total_fitness / len(generation_fitness)
            })

    best = max(population, key=lambda r: calculate_fitness(r, dist_matrix, time_matrix))
    fitness_summary["best_fitness"] = calculate_fitness(best, dist_matrix, time_matrix)
    fitness_summary["overall_total_fitness"] = (
        fitness_summary.get("population_total_fitness", 0)
        + fitness_summary.get("crossover_total_fitness", 0)
        + fitness_summary.get("mutation_total_fitness", 0)
        + fitness_summary.get("generation_total_fitness", 0)
    )

    return best, dist_matrix, time_matrix, generation_logs, fitness_summary


# Menulis ringkasan proses optimasi ke console untuk debugging dan evaluasi.
def log_optimization_summary(
    tgl,
    petugas,
    generation_logs,
    total_dist,
    total_time,
    process_seconds,
    timings=None,
    fitness_summary=None
):
    print("\n=== HASIL OPTIMASI ===")
    print(f"Kurir                : {petugas}")

    if fitness_summary:
        print("\nParameter GA:")
        print(f"- Generasi : {fitness_summary.get('generations', GA_GENERATIONS)}")
        print(f"- Populasi : {fitness_summary.get('population_size', GA_POP_SIZE)}")
        print(
            f"- Cr       : {fitness_summary.get('crossover_rate', GA_CROSSOVER_RATE)} "
            f"({fitness_summary.get('crossover_count', int(GA_CROSSOVER_RATE * GA_POP_SIZE))} crossover/generasi)"
        )
        print(
            f"- Mr       : {fitness_summary.get('mutation_rate', GA_MUTATION_RATE)} "
            f"({fitness_summary.get('mutation_count', int(GA_MUTATION_RATE * GA_POP_SIZE))} mutasi/generasi)"
        )

    if generation_logs:
        print("\nLog fitness per generasi:")
        print(
            f"{'Generasi':>8} | {'Fitness Populasi':>16} | {'Fitness Cr':>16} | "
            f"{'Fitness Mr':>16} | {'Fitness Total':>16}"
        )
        print("-" * 86)
        for log in generation_logs:
            print(
                f"{log.get('generation', 0):>8} | "
                f"{log.get('population_total_fitness', 0):>16.10f} | "
                f"{log.get('crossover_total_fitness', 0):>16.10f} | "
                f"{log.get('mutation_total_fitness', 0):>16.10f} | "
                f"{log.get('overall_total_fitness', 0):>16.10f}"
            )

    if fitness_summary:
        print("Total keseluruhan fitness:")
        print(f"- Fitness populasi : {fitness_summary['population_total_fitness']:.10f}")
        print(f"- Fitness cr       : {fitness_summary['crossover_total_fitness']:.10f}")
        print(f"- Fitness mr       : {fitness_summary['mutation_total_fitness']:.10f}")
        print(f"- Fitness generasi : {fitness_summary['generation_total_fitness']:.10f}")
        overall_total = fitness_summary.get("overall_total_fitness")
        if overall_total is None:
            overall_total = (
                fitness_summary.get("population_total_fitness", 0)
                + fitness_summary.get("crossover_total_fitness", 0)
                + fitness_summary.get("mutation_total_fitness", 0)
                + fitness_summary.get("generation_total_fitness", 0)
            )
        print(f"- Fitness total    : {overall_total:.10f}")
        print(f"- Fitness terbaik  : {fitness_summary['best_fitness']:.10f}")

    print(f"Total Jarak          : {round(total_dist, 2)} km")
    print(f"Total Waktu          : {round(total_time, 2)} menit")
    if timings:
        print("Rincian waktu:")
        for label, seconds in timings.items():
            print(f"- {label}: {seconds:.2f} detik")
    print(f"Waktu proses optimasi: {process_seconds:.2f} detik")
    print("======================\n")


# Mengubah baris paket terfilter menjadi daftar alamat yang siap dioptimasi.
def build_route_addresses(df_subset):
    data_list = []

    for _, row in df_subset.iterrows():
        alamat = row["__alamat"]
        no_resi = row["__resi"]
        nama = row["__nama"]
        kota = row["__kota"]

        if alamat:
            data_list.append({
                "alamat": alamat,
                "alamat_lengkap": build_full_address(alamat, kota),
                "resi": no_resi,
                "nama": nama,
                "kota": kota
            })

    return data_list


# Menggeser titik marker yang bertumpuk agar marker tetap terlihat di peta.
def spread_overlapping_map_point(coord, used_positions):
    key = (round(float(coord[0]), 6), round(float(coord[1]), 6))
    duplicate_index = used_positions.get(key, 0)
    used_positions[key] = duplicate_index + 1

    if duplicate_index == 0:
        return coord

    ring = (duplicate_index - 1) // 8 + 1
    slot = (duplicate_index - 1) % 8
    angle = (2 * 3.141592653589793 * slot) / 8
    offset = 0.00008 * ring
    lon = float(coord[0]) + (offset * math.cos(angle))
    lat = float(coord[1]) + (offset * math.sin(angle))
    return [lon, lat]


# Menyusun hasil akhir optimasi berisi tabel rute, titik peta, geometri, dan navigasi.
def build_optimization_result(addresses, route, coords, dist_matrix, time_matrix):
    total_dist = sum(
        dist_matrix[route[i]][route[i + 1]]
        for i in range(len(route) - 1)
    ) / 1000

    total_time = sum(
        time_matrix[route[i]][route[i + 1]]
        for i in range(len(route) - 1)
    ) / 60

    route_data = []
    map_points = []
    ordered_coords = []
    used_map_positions = {}

    for i, idx in enumerate(route):
        point_coord = coords[idx]
        ordered_coords.append(point_coord)

        if idx == 0:
            route_data.append({
                "no": i + 1,
                "alamat": "Kantor Pos Besar Malang",
                "alamat_lengkap": "Kantor Pos Besar Malang, Kota Malang",
                "resi": "-",
                "nama": "-",
                "kota": "-",
                "lat": point_coord[1],
                "lng": point_coord[0],
            })
            point_name = "Kantor Pos Besar Malang"
        else:
            d = addresses[idx - 1]
            route_data.append({
                "no": i + 1,
                "alamat": d["alamat"],
                "alamat_lengkap": d.get("alamat_lengkap") or build_full_address(d["alamat"], d["kota"]),
                "resi": d["resi"],
                "nama": d["nama"],
                "kota": d["kota"],
                "lat": point_coord[1],
                "lng": point_coord[0],
            })
            point_name = d["alamat"]

        visual_coord = spread_overlapping_map_point(point_coord, used_map_positions)

        map_points.append({
            "order": i + 1,
            "lat": visual_coord[1],
            "lng": visual_coord[0],
            "name": point_name
        })

    route_geometry = get_route_geometry(ordered_coords)
    if route_geometry is None:
        route_geometry = []

    return {
        "route_data": route_data,
        "distance": round(total_dist, 2),
        "time": round(total_time, 2),
        "package_count": len(addresses),
        "map_points": map_points,
        "route_geometry": route_geometry,
        "navigation_url": build_google_maps_navigation_url(route_data),
        "total_dist_raw": total_dist,
        "total_time_raw": total_time
    }


# Menghitung optimasi rute historis untuk tanggal dan kurir tertentu.
def compute_optimization(package_df, tgl, petugas, assignment_df=None, ga_params=None):
    start_time = time.perf_counter()
    timings = {}

    step_time = time.perf_counter()
    prepared_package = prepare_package_dataframe(package_df, require_city=assignment_df is not None)

    if assignment_df is None:
        petugas_column = find_column(
            package_df,
            ["Petugas", "Kurir", "Nama Kurir", "Nama Petugas"],
            "nama kurir"
        )
        prepared_package["__petugas"] = package_df[petugas_column].apply(normalize_text)
        filtered_rows = prepared_package[
            (prepared_package["__tanggal"] == str(tgl)) &
            (prepared_package["__petugas"] == petugas)
        ]
        assigned_city_names = []
    else:
        prepared_assignment = prepare_assignment_dataframe(assignment_df)
        assigned_city_rows = prepared_assignment[prepared_assignment["__petugas"] == petugas]
        assigned_city_keys = set(assigned_city_rows["__penugasan_key"].tolist())
        assigned_city_names = sorted(set(assigned_city_rows["__penugasan"].tolist()))

        if not assigned_city_keys:
            raise ValueError("Penugasan untuk kurir yang dipilih tidak ditemukan.")

        filtered = prepared_package[prepared_package["__tanggal"] == str(tgl)]
        filtered_rows = filtered[filtered["__kota_key"].isin(assigned_city_keys)]
    timings["preprocessing"] = time.perf_counter() - step_time

    step_time = time.perf_counter()
    addresses = build_route_addresses(filtered_rows)

    if not addresses:
        if assignment_df is None:
            raise ValueError("Tidak ada alamat untuk kurir yang dipilih pada tanggal tersebut.")
        raise ValueError("Tidak ada alamat yang cocok dengan penugasan kurir pada tanggal tersebut.")

    if len(addresses) > MAX_POINTS_PER_COURIER:
        addresses = addresses[:MAX_POINTS_PER_COURIER]

    locations = [
        {"alamat": "Kantor Pos Besar Malang", "kota": "KOTA MALANG, KLOJEN"}
    ] + [
        {"alamat": d["alamat"], "kota": d["kota"]}
        for d in addresses
    ]
    coords = geocode_locations(locations)
    timings["geocoding"] = time.perf_counter() - step_time

    if len(coords) < 2:
        raise ValueError("Koordinat rute tidak cukup untuk dihitung.")

    step_time = time.perf_counter()
    ga_params = ga_params or get_ga_params()
    # Reseed supaya klik ulang tetap menguji variasi GA (pakai state random global).
    try:
        random.seed(time.time_ns())
    except Exception:
        pass

    route, dist_matrix, time_matrix, generation_logs, fitness_summary = genetic_algorithm(
        coords,
        pop_size=int(ga_params.get("pop_size", GA_POP_SIZE)),
        generations=int(ga_params.get("generations", GA_GENERATIONS)),
        crossover_rate=float(ga_params.get("crossover_rate", GA_CROSSOVER_RATE)),
        mutation_rate=float(ga_params.get("mutation_rate", GA_MUTATION_RATE)),
    )
    timings["matrix + GA"] = time.perf_counter() - step_time

    step_time = time.perf_counter()
    random_iterations_target = int(
        max(
            1,
            int(ga_params.get("pop_size", GA_POP_SIZE)) * int(ga_params.get("generations", GA_GENERATIONS)),
        )
    )
    random_route, random_iterations = random_search_best_route(
        dist_matrix,
        time_matrix,
        iterations=random_iterations_target,
        start_index=0,
    )
    random_dist_km, random_time_min = compute_route_totals(random_route, dist_matrix, time_matrix)
    timings["random baseline"] = time.perf_counter() - step_time

    step_time = time.perf_counter()
    optimization_result = build_optimization_result(
        addresses,
        route,
        coords,
        dist_matrix,
        time_matrix
    )
    timings["geometry rute"] = time.perf_counter() - step_time

    process_seconds = time.perf_counter() - start_time
    log_optimization_summary(
        tgl,
        petugas,
        generation_logs,
        optimization_result["total_dist_raw"],
        optimization_result["total_time_raw"],
        process_seconds,
        timings,
        fitness_summary
    )

    optimization_result["assigned_areas"] = assigned_city_names
    optimization_result["fitness_summary"] = fitness_summary
    optimization_result["random_baseline"] = {
        "method": "Random Search",
        "iterations": int(random_iterations),
        "iterations_target": int(random_iterations_target),
        "distance": round(random_dist_km, 2),
        "time": round(random_time_min, 2),
        "distance_improvement_pct": compute_improvement_pct(random_dist_km, optimization_result.get("total_dist_raw", 0)),
        "time_improvement_pct": compute_improvement_pct(random_time_min, optimization_result.get("total_time_raw", 0)),
    }
    optimization_result["process_steps"] = build_process_steps(timings)
    optimization_result.pop("total_dist_raw", None)
    optimization_result.pop("total_time_raw", None)
    return optimization_result


# Menghitung jarak kuadrat antar koordinat untuk proses clustering cepat.
def distance_squared(coord_a, coord_b):
    lon_diff = float(coord_a[0]) - float(coord_b[0])
    lat_diff = float(coord_a[1]) - float(coord_b[1])
    return (lon_diff * lon_diff) + (lat_diff * lat_diff)


# Membagi kapasitas paket secara seimbang untuk setiap kurir dalam satu wilayah.
def get_balanced_cluster_capacities(total_rows, total_couriers):
    base_count = total_rows // total_couriers
    extra_count = total_rows % total_couriers
    return [
        base_count + (1 if index < extra_count else 0)
        for index in range(total_couriers)
    ]


# Memilih centroid awal untuk pembagian alamat ke beberapa kurir.
def choose_initial_centroids(coords, total_couriers):
    if total_couriers <= 1:
        return [coords[0]]

    lon_spread = max(coord[0] for coord in coords) - min(coord[0] for coord in coords)
    lat_spread = max(coord[1] for coord in coords) - min(coord[1] for coord in coords)
    axis_index = 0 if lon_spread >= lat_spread else 1
    sorted_coords = sorted(coords, key=lambda coord: coord[axis_index])

    centroids = []
    total_coords = len(sorted_coords)
    for index in range(total_couriers):
        position = round(index * (total_coords - 1) / max(total_couriers - 1, 1))
        centroids.append(sorted_coords[position])

    return centroids


# Menempatkan titik alamat ke centroid terdekat dengan batas kapasitas seimbang.
def assign_points_to_balanced_centroids(coords, centroids, capacities):
    assignments = [[] for _ in centroids]
    remaining_capacity = capacities[:]
    point_preferences = []

    for point_index, coord in enumerate(coords):
        distances = sorted(
            (
                distance_squared(coord, centroid),
                centroid_index
            )
            for centroid_index, centroid in enumerate(centroids)
        )
        nearest_distance = distances[0][0]
        second_distance = distances[1][0] if len(distances) > 1 else nearest_distance
        point_preferences.append((
            second_distance - nearest_distance,
            point_index,
            distances
        ))

    point_preferences.sort(reverse=True)

    for _, point_index, distances in point_preferences:
        for _, centroid_index in distances:
            if remaining_capacity[centroid_index] > 0:
                assignments[centroid_index].append(point_index)
                remaining_capacity[centroid_index] -= 1
                break

    return assignments


# Menghitung ulang centroid berdasarkan hasil penempatan titik.
def recompute_centroids(coords, assignments, previous_centroids):
    centroids = []
    for centroid_index, point_indexes in enumerate(assignments):
        if not point_indexes:
            centroids.append(previous_centroids[centroid_index])
            continue

        lon_total = sum(coords[point_index][0] for point_index in point_indexes)
        lat_total = sum(coords[point_index][1] for point_index in point_indexes)
        centroids.append([
            lon_total / len(point_indexes),
            lat_total / len(point_indexes)
        ])

    return centroids


# Membagi alamat dalam satu wilayah ke beberapa kurir berdasarkan kedekatan geografis.
def split_rows_balanced_fast(rows, courier_names):
    if not rows or not courier_names:
        return {}

    courier_count = min(len(courier_names), len(rows))
    active_couriers = courier_names[:courier_count]
    capacities = get_balanced_cluster_capacities(len(rows), courier_count)

    assignments = {petugas: [] for petugas in courier_names}
    if not active_couriers:
        return assignments

    # Urutkan supaya hasil stabil (mengurangi efek acak pada distribusi).
    prepared_rows = sorted(rows, key=lambda item: normalize_text(item.get("alamat")))
    courier_index = 0
    for row in prepared_rows:
        # Cari kurir berikutnya yang masih punya kapasitas.
        for _ in range(len(active_couriers)):
            petugas = active_couriers[courier_index]
            if len(assignments[petugas]) < capacities[courier_index]:
                assignments[petugas].append(row)
                break
            courier_index = (courier_index + 1) % len(active_couriers)
        courier_index = (courier_index + 1) % len(active_couriers)

    return assignments


def split_rows_by_nearest_balanced_area(rows, courier_names, penugasan, fast_mode=False):
    if not rows or not courier_names:
        return {}

    if len(courier_names) == 1:
        return {courier_names[0]: rows}

    # Mode cepat: lewati geocoding (yang biasanya paling lama) dan bagi alamat secara seimbang.
    if fast_mode:
        return split_rows_balanced_fast(rows, courier_names)

    courier_count = min(len(courier_names), len(rows))
    active_couriers = courier_names[:courier_count]
    capacities = get_balanced_cluster_capacities(len(rows), courier_count)
    locations = [
        {"alamat": row["alamat"], "kota": row.get("kota") or penugasan}
        for row in rows
    ]
    coords = geocode_locations(locations)
    centroids = choose_initial_centroids(coords, courier_count)

    assignments = [[] for _ in active_couriers]
    for _ in range(6):
        assignments = assign_points_to_balanced_centroids(coords, centroids, capacities)
        next_centroids = recompute_centroids(coords, assignments, centroids)
        if next_centroids == centroids:
            break
        centroids = next_centroids

    grouped_rows = {}
    for courier_index, point_indexes in enumerate(assignments):
        petugas = active_couriers[courier_index]
        grouped_rows[petugas] = [
            rows[point_index]
            for point_index in sorted(
                point_indexes,
                key=lambda index: distance_squared(coords[index], centroids[courier_index])
            )
        ]

    for petugas in courier_names[courier_count:]:
        grouped_rows[petugas] = []

    return grouped_rows


# Membentuk kelompok alamat per kurir dengan membaca kolom kota sebagai wilayah penugasan.
def build_courier_clusters(cluster_df, assignment_df, fast_mode=False):
    prepared_cluster = prepare_package_dataframe(cluster_df, require_city=True)
    prepared_assignment = prepare_assignment_dataframe(assignment_df)

    if prepared_assignment.empty:
        raise ValueError("Data penugasan kurir belum tersedia.")

    clustered_groups = {}
    unmatched_addresses = []
    area_buckets = {}
    distribution_summary = []

    for _, row in prepared_cluster.iterrows():
        matched_assignment_rows = get_valid_assignment_rows_for_package(
            row,
            prepared_assignment
        )
        if matched_assignment_rows.empty:
            unmatched_addresses.append({
                "alamat": row["__alamat"],
                "kota": row["__kota"],
                "resi": row["__resi"],
                "nama": row["__nama"],
            })
            continue

        matched_row = matched_assignment_rows.iloc[0]
        assignment_key = matched_row["__penugasan_key"]
        penugasan = matched_row["__penugasan"]
        package_item = {
            "alamat": row["__alamat"],
            "alamat_lengkap": build_full_address(row["__alamat"], penugasan),
            "resi": row["__resi"],
            "nama": row["__nama"],
            "kota": penugasan,
        }

        area_buckets.setdefault(assignment_key, {
            "penugasan": penugasan,
            "rows": []
        })
        area_buckets[assignment_key]["rows"].append(package_item)

    for assignment_key, bucket in area_buckets.items():
        courier_names, penugasan = get_couriers_for_assignment(prepared_assignment, assignment_key)
        if not courier_names:
            continue

        area_distribution = {
            "wilayah": penugasan,
            "total_alamat": len(bucket["rows"]),
            "couriers": []
        }
        grouped_rows = split_rows_by_nearest_balanced_area(
            bucket["rows"],
            courier_names,
            penugasan,
            fast_mode=fast_mode,
        )

        for petugas, rows in grouped_rows.items():
            if rows:
                clustered_groups.setdefault(petugas, {
                    "assigned_areas": set(),
                    "rows": []
                })
                clustered_groups[petugas]["assigned_areas"].add(penugasan)
                clustered_groups[petugas]["rows"].extend(rows)

        for petugas in courier_names:
            area_distribution["couriers"].append({
                "petugas": petugas,
                "jumlah_alamat": len(grouped_rows.get(petugas, []))
            })

        distribution_summary.append(area_distribution)

    if not clustered_groups:
        raise ValueError("Tidak ada alamat yang berhasil dicocokkan dengan penugasan kurir.")

    return {
        "clustered_groups": clustered_groups,
        "unmatched_addresses": unmatched_addresses,
        "distribution_summary": distribution_summary,
    }


# Mengoptimasi rute untuk satu kurir yang dipilih dari hasil pembagian alamat.
def optimize_clustered_route_for_petugas(
    petugas,
    group,
    ga_params=None,
    coords=None,
    force_reroll=False,
    quiet=False,
    runs=1,
):
    start_time = time.perf_counter()
    timings = {}
    step_time = time.perf_counter()
    addresses = group["rows"]
    if len(addresses) > MAX_POINTS_PER_COURIER:
        addresses = addresses[:MAX_POINTS_PER_COURIER]
    timings["preprocessing"] = time.perf_counter() - step_time

    step_time = time.perf_counter()
    locations = [
        {"alamat": "Kantor Pos Besar Malang", "kota": "KOTA MALANG, KLOJEN"}
    ] + [
        {"alamat": d["alamat"], "kota": d["kota"]}
        for d in addresses
    ]
    if coords is None:
        coords = geocode_locations(locations)
    timings["geocoding"] = time.perf_counter() - step_time

    if len(coords) < 2:
        raise ValueError("Koordinat rute tidak cukup untuk dihitung.")

    step_time = time.perf_counter()
    ga_params = ga_params or get_ga_params()
    runs = max(1, int(runs or 1))

    run_totals = []
    last_route = None
    last_dist_matrix = None
    last_time_matrix = None
    last_generation_logs = []
    last_fitness_summary = {}

    # Jalankan GA beberapa kali untuk eksperimen (hasil akan berbeda karena random).
    for run_index in range(runs):
        # Force reroll: reseed supaya setiap run menghasilkan jalur acak baru.
        if force_reroll or runs > 1:
            try:
                random.seed(time.time_ns())
            except Exception:
                pass

        run_quiet = quiet or (runs > 1 and run_index < runs - 1)
        route, dist_matrix, time_matrix, generation_logs, fitness_summary = genetic_algorithm(
            coords,
            pop_size=int(ga_params.get("pop_size", GA_POP_SIZE)),
            generations=int(ga_params.get("generations", GA_GENERATIONS)),
            crossover_rate=float(ga_params.get("crossover_rate", GA_CROSSOVER_RATE)),
            mutation_rate=float(ga_params.get("mutation_rate", GA_MUTATION_RATE)),
            quiet=run_quiet,
        )

        fitness_total = fitness_summary.get("overall_total_fitness")
        if fitness_total is None:
            fitness_total = (
                fitness_summary.get("population_total_fitness", 0)
                + fitness_summary.get("crossover_total_fitness", 0)
                + fitness_summary.get("mutation_total_fitness", 0)
                + fitness_summary.get("generation_total_fitness", 0)
            )
        try:
            fitness_total = float(fitness_total)
        except Exception:
            fitness_total = 0.0
        run_totals.append(fitness_total)

        last_route = route
        last_dist_matrix = dist_matrix
        last_time_matrix = time_matrix
        last_generation_logs = generation_logs
        last_fitness_summary = fitness_summary

    route = last_route
    dist_matrix = last_dist_matrix
    time_matrix = last_time_matrix
    generation_logs = last_generation_logs
    fitness_summary = last_fitness_summary
    timings["matrix + GA"] = time.perf_counter() - step_time

    step_time = time.perf_counter()
    random_iterations_target = int(
        max(
            1,
            int(ga_params.get("pop_size", GA_POP_SIZE)) * int(ga_params.get("generations", GA_GENERATIONS)),
        )
    )
    random_route, random_iterations = random_search_best_route(
        dist_matrix,
        time_matrix,
        iterations=random_iterations_target,
        start_index=0,
    )
    random_dist_km, random_time_min = compute_route_totals(random_route, dist_matrix, time_matrix)
    timings["random baseline"] = time.perf_counter() - step_time

    step_time = time.perf_counter()
    optimization_result = build_optimization_result(
        addresses,
        route,
        coords,
        dist_matrix,
        time_matrix
    )
    timings["geometry rute"] = time.perf_counter() - step_time
    process_seconds = time.perf_counter() - start_time

    if not quiet:
        if runs > 1:
            print("\nParameter GA")
            print(f"Generasi: {ga_params.get('generations', GA_GENERATIONS)}")
            print(f"Populasi: {ga_params.get('pop_size', GA_POP_SIZE)}")
            print(f"Cr: {ga_params.get('crossover_rate', GA_CROSSOVER_RATE)}")
            print(f"Mr: {ga_params.get('mutation_rate', GA_MUTATION_RATE)}")
            print(f"\nTotal running {runs}x")
            for idx, fitness_total in enumerate(run_totals, start=1):
                print(f"fitness total {idx}: {fitness_total:.10f}")

        log_optimization_summary(
            "Pemetaan",
            petugas,
            generation_logs,
            optimization_result["total_dist_raw"],
            optimization_result["total_time_raw"],
            process_seconds,
            timings=timings,
            fitness_summary=fitness_summary
        )

    return {
        "petugas": petugas,
        "assigned_areas": sorted(group["assigned_areas"]),
        "distance": optimization_result["distance"],
        "time": optimization_result["time"],
        "random_baseline": {
            "method": "Random Search",
            "iterations": int(random_iterations),
            "iterations_target": int(random_iterations_target),
            "distance": round(random_dist_km, 2),
            "time": round(random_time_min, 2),
            "distance_improvement_pct": compute_improvement_pct(random_dist_km, optimization_result.get("total_dist_raw", 0)),
            "time_improvement_pct": compute_improvement_pct(random_time_min, optimization_result.get("total_time_raw", 0)),
        },
        "package_count": optimization_result["package_count"],
        "route_data": optimization_result["route_data"],
        "map_points": optimization_result["map_points"],
        "route_geometry": optimization_result["route_geometry"],
        "navigation_url": optimization_result["navigation_url"],
        "fitness_summary": fitness_summary,
        "process_steps": build_process_steps(timings),
        "_ga_signature": get_ga_signature(ga_params),
        "_coords": coords,
        "_ga_run_totals": run_totals,
    }


# Mengoptimasi rute untuk setiap kelompok alamat milik kurir hasil pemetaan.
def optimize_clustered_routes(clustered_groups, ga_params=None):
    results = []
    for petugas, group in sorted(clustered_groups.items()):
        results.append(optimize_clustered_route_for_petugas(petugas, group, ga_params=ga_params))

    return results


# Menulis ringkasan keseluruhan hasil pemetaan semua kurir ke console.
def log_pemetaan_overall_summary(results):
    if not results:
        return

    total_packages = sum(result.get("package_count", 0) for result in results)
    total_distance = sum(result.get("distance", 0) for result in results)
    total_time = sum(result.get("time", 0) for result in results)
    total_fitness = {
        "population_total_fitness": 0,
        "crossover_total_fitness": 0,
        "mutation_total_fitness": 0,
        "generation_total_fitness": 0,
    }

    print("\n=== HASIL KESELURUHAN PEMETAAN ===")
    print(f"Total Kurir          : {len(results)}")
    print(f"Total Paket          : {total_packages}")
    print(f"Total Jarak          : {round(total_distance, 2)} km")
    print(f"Total Waktu          : {round(total_time, 2)} menit")
    print("\nRingkasan per kurir:")

    for result in results:
        fitness_summary = result.get("fitness_summary", {})
        for key in total_fitness:
            total_fitness[key] += fitness_summary.get(key, 0)

        print(f"- {result['petugas']}")
        print(f"  Paket              : {result['package_count']}")
        print(f"  Jarak              : {result['distance']} km")
        print(f"  Waktu              : {result['time']} menit")
        print(f"  Fitness populasi   : {fitness_summary.get('population_total_fitness', 0):.10f}")
        print(f"  Fitness cr         : {fitness_summary.get('crossover_total_fitness', 0):.10f}")
        print(f"  Fitness mr         : {fitness_summary.get('mutation_total_fitness', 0):.10f}")
        print(f"  Fitness generasi   : {fitness_summary.get('generation_total_fitness', 0):.10f}")
        print(f"  Fitness terbaik    : {fitness_summary.get('best_fitness', 0):.10f}")

    print("\nTotal keseluruhan fitness semua kurir:")
    print(f"- Fitness populasi   : {total_fitness['population_total_fitness']:.10f}")
    print(f"- Fitness cr         : {total_fitness['crossover_total_fitness']:.10f}")
    print(f"- Fitness mr         : {total_fitness['mutation_total_fitness']:.10f}")
    print(f"- Fitness generasi   : {total_fitness['generation_total_fitness']:.10f}")
    print("=====================================\n")


# Memfilter hasil pemetaan agar UI hanya menampilkan kurir yang dipilih.
def filter_pemetaan_result_by_petugas(pemetaan_result, selected_petugas):
    if not selected_petugas:
        return pemetaan_result

    filtered_results = [
        result for result in pemetaan_result.get("results", [])
        if result.get("petugas") == selected_petugas
    ]

    filtered_distribution = []
    for item in pemetaan_result.get("distribution_summary", []):
        couriers = [
            courier for courier in item.get("couriers", [])
            if courier.get("petugas") == selected_petugas and courier.get("jumlah_alamat", 0) > 0
        ]
        if couriers:
            filtered_item = dict(item)
            filtered_item["couriers"] = couriers
            filtered_item["total_alamat"] = sum(
                courier.get("jumlah_alamat", 0)
                for courier in couriers
            )
            filtered_distribution.append(filtered_item)

    return {
        "results": filtered_results,
        "unmatched_addresses": pemetaan_result.get("unmatched_addresses", []),
        "distribution_summary": filtered_distribution,
    }


# Menjalankan proses upload aktual sampai pembagian alamat ke kurir, tanpa optimasi rute.
def compute_pemetaan_distribution(cluster_df, assignment_df, fast_mode=False):
    pemetaan_data = build_courier_clusters(cluster_df, assignment_df, fast_mode=fast_mode)

    return {
        "clustered_groups": pemetaan_data["clustered_groups"],
        "optimized_results": {},
        "unmatched_addresses": pemetaan_data["unmatched_addresses"],
        "distribution_summary": pemetaan_data["distribution_summary"],
    }


# Menjalankan seluruh proses pemetaan aktual dari clustering sampai optimasi rute.
def compute_pemetaan_optimizations(cluster_df, assignment_df, fast_mode=False, ga_params=None):
    pemetaan_data = build_courier_clusters(cluster_df, assignment_df, fast_mode=fast_mode)
    results = optimize_clustered_routes(pemetaan_data["clustered_groups"], ga_params=ga_params)
    log_pemetaan_overall_summary(results)

    return {
        "clustered_groups": pemetaan_data["clustered_groups"],
        "optimized_results": {
            result["petugas"]: result
            for result in results
        },
        "results": results,
        "unmatched_addresses": pemetaan_data["unmatched_addresses"],
        "distribution_summary": pemetaan_data["distribution_summary"],
    }

# Membersihkan payload session lama sebelum setiap request Flask diproses.
@app.before_request
def remove_large_legacy_session_payloads():
    purge_legacy_result_session_keys()


# Menambahkan header agar browser tidak memakai cache halaman lama.
@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# Menghapus file historis aktif dan mengembalikan user ke halaman input.
@app.route("/reset", methods=["GET", "POST"])
def reset():
    remove_uploaded_file("excel_file")
    session.pop("petugas_list", None)
    session.pop("tgl_list", None)
    clear_optimization_cache()
    clear_routing_cache()
    session.modified = True

    return redirect("/") 


# Menampilkan halaman utama aplikasi.
@app.route("/")
def home():
    return render_template("home.html")

# Menangani upload data historis dan menyiapkan filter tanggal serta kurir.
@app.route("/input", methods=["GET", "POST"])
def input_data():
    error = None
    if request.method == "POST":
        try:
            if "file" in request.files and request.files["file"].filename != "":
                file = request.files["file"]
                filepath = save_uploaded_file(file, "excel_file", "data_upload")
                df = load_uploaded_dataframe(filepath)
                petugas_column = find_column(
                    df,
                    ["Petugas", "Kurir", "Nama Kurir", "Nama Petugas"],
                    "nama kurir"
                )
                tanggal_column = find_column(
                    df,
                    ["Tgl_Antaran_Pertama", "Tanggal Antaran Pertama", "Tgl Kirim", "Tanggal"],
                    "tanggal antaran"
                )

                session["petugas_list"] = sorted(df[petugas_column].dropna().astype(str).str.strip().unique().tolist())
                session["tgl_list"] = sorted(
                    {
                        normalize_delivery_date(value)
                        for value in df[tanggal_column].dropna().tolist()
                        if normalize_delivery_date(value)
                    }
                )
                clear_optimization_cache()
                session.modified = True

                return redirect("/hasil")

        except Exception as exc:
            error = str(exc)

    return render_template("input.html", error=error)


# Mengelola input, update, dan hapus master penugasan kurir.
@app.route("/input-penugasan", methods=["GET", "POST"])
def input_penugasan():
    error = None
    edit_id = request.args.get("edit_id")
    selected_wilayah = normalize_text(request.args.get("filter_wilayah"))
    selected_wilayah_key = normalize_key(selected_wilayah)
    assignments = load_manual_assignments()
    edit_item = None

    if edit_id:
        edit_item = next((item for item in assignments if item["id"] == edit_id), None)

    filtered_assignments = assignments
    if selected_wilayah_key:
        filtered_assignments = [
            item for item in assignments
            if normalize_key(item.get("penugasan")) == selected_wilayah_key
        ]

    if request.method == "POST":
        action = request.form.get("action")
        petugas = normalize_text(request.form.get("petugas"))
        penugasan = normalize_text(request.form.get("penugasan"))
        item_id = request.form.get("id")

        try:
            if action == "delete":
                assignments = [item for item in assignments if item["id"] != item_id]
                save_manual_assignments(assignments)
                clear_pemetaan_cache()
                return redirect("/input-penugasan")

            if not petugas or not penugasan:
                raise ValueError("Nama kurir dan wilayah penugasan wajib diisi.")

            selected_penugasans = expand_penugasan_selection(penugasan)
            if not selected_penugasans:
                raise ValueError("Wilayah penugasan tidak valid.")

            if action == "update" and item_id:
                updated = False
                used_penugasans = set()
                for item in assignments:
                    if item["id"] == item_id:
                        item["petugas"] = petugas
                        item["penugasan"] = selected_penugasans[0]
                        used_penugasans.add(normalize_key(selected_penugasans[0]))
                        updated = True
                        break
                if not updated:
                    raise ValueError("Data penugasan yang akan diubah tidak ditemukan.")

                existing_keys = {
                    (normalize_key(item.get("petugas")), normalize_key(item.get("penugasan")))
                    for item in assignments
                }
                for item_penugasan in selected_penugasans[1:]:
                    item_key = (normalize_key(petugas), normalize_key(item_penugasan))
                    if item_key in existing_keys or normalize_key(item_penugasan) in used_penugasans:
                        continue
                    assignments.append({
                        "id": str(uuid.uuid4()),
                        "petugas": petugas,
                        "penugasan": item_penugasan,
                    })
                    existing_keys.add(item_key)
                    used_penugasans.add(normalize_key(item_penugasan))
            else:
                existing_keys = {
                    (normalize_key(item.get("petugas")), normalize_key(item.get("penugasan")))
                    for item in assignments
                }
                for item_penugasan in selected_penugasans:
                    item_key = (normalize_key(petugas), normalize_key(item_penugasan))
                    if item_key in existing_keys:
                        continue
                    assignments.append({
                        "id": str(uuid.uuid4()),
                        "petugas": petugas,
                        "penugasan": item_penugasan,
                    })
                    existing_keys.add(item_key)

            save_manual_assignments(assignments)
            clear_pemetaan_cache()
            return redirect("/input-penugasan")
        except Exception as exc:
            error = str(exc)

    return render_template(
        "input_penugasan.html",
        error=error,
        assignments=filtered_assignments,
        assignment_summary=get_manual_assignment_summary(),
        edit_item=edit_item,
        kecamatan_options=get_kecamatan_options(),
        wilayah_options=MALANG_WILAYAH,
        selected_wilayah=selected_wilayah,
        total_assignments=len(assignments),
        filtered_count=len(filtered_assignments),
    )


# Menghapus file pemetaan aktual dan cache rute terkait.
@app.route("/reset-pemetaan", methods=["GET", "POST"])
def reset_pemetaan():
    remove_uploaded_file("cluster_file")
    clear_pemetaan_cache()
    clear_routing_cache()
    session.modified = True
    return redirect("/hasil-pemetaan")


# Menangani upload data aktual untuk proses pemetaan alamat ke kurir.
@app.route("/input-pemetaan", methods=["GET", "POST"])
def input_pemetaan():
    error = None
    uploaded_file_name = None
    fast_mode = bool(session.get("pemetaan_fast_mode", True))

    if "cluster_file" in session:
        uploaded_file_name = os.path.basename(session["cluster_file"])

    if request.method == "POST":
        try:
            if "file" in request.files and request.files["file"].filename != "":
                file = request.files["file"]
                fast_mode = request.form.get("fast_mode") in {"1", "true", "on", "yes"}
                filepath = save_uploaded_file(file, "cluster_file", "data_pemetaan")
                cluster_df = load_uploaded_dataframe(filepath)
                assignment_df = build_assignment_dataframe_from_manual()
                session["pemetaan_fast_mode"] = fast_mode
                cache_key = get_pemetaan_cache_key(filepath, fast_mode=fast_mode)
                clear_pemetaan_cache()
                clear_routing_cache()
                CLUSTER_OPTIMIZATION_RESULTS_CACHE[cache_key] = compute_pemetaan_distribution(
                    cluster_df,
                    assignment_df,
                    fast_mode=fast_mode,
                )
                session.modified = True
                uploaded_file_name = os.path.basename(filepath)
                return redirect("/hasil-pemetaan")
        except Exception as exc:
            error = str(exc)

    return render_template(
        "input_pemetaan.html",
        error=error,
        uploaded_file_name=uploaded_file_name,
        assignment_summary=get_manual_assignment_summary(),
        fast_mode=fast_mode,
    )

# Menampilkan hasil optimasi historis berdasarkan tanggal dan kurir yang dipilih.
@app.route("/hasil", methods=["GET", "POST"])
def hasil():
    if "excel_file" not in session:
        return redirect("/input")

    petugas_list = session.get("petugas_list", [])
    tgl_list = session.get("tgl_list", [])
    uploaded_file_name = os.path.basename(session["excel_file"])
    
    result = None
    map_points = []
    route_geometry = []
    route_data = []
    selected_tgl = None
    selected_petugas = None
    error = None

    if request.method == "POST":
        if request.form.get("reset"):
            remove_uploaded_file("excel_file")
            session.pop("petugas_list", None)
            session.pop("tgl_list", None)
            clear_optimization_cache()
            clear_routing_cache()
            session.modified = True
            return redirect("/input")
    
    # Ambil dari query string atau form
    selected_tgl = normalize_delivery_date(request.args.get("tgl") or request.form.get("tgl"))
    selected_petugas = request.args.get("petugas") or request.form.get("petugas")

    try:
        df_for_dates = load_uploaded_dataframe(session["excel_file"])
        tanggal_column_for_dates = find_column(
            df_for_dates,
            ["Tgl_Antaran_Pertama", "Tanggal Antaran Pertama", "Tgl Kirim", "Tanggal"],
            "tanggal antaran"
        )
        tgl_list = sorted(
            {
                normalize_delivery_date(value)
                for value in df_for_dates[tanggal_column_for_dates].dropna().tolist()
                if normalize_delivery_date(value)
            }
        )
        session["tgl_list"] = tgl_list
        session.modified = True
    except Exception:
        pass
    
    # Jika ada pilihan tanggal dan kurir, tampilkan peta
    if selected_tgl and selected_petugas:
        try:
            cache_key = get_optimization_cache_key(
                session["excel_file"],
                selected_tgl,
                selected_petugas
            )

            if cache_key not in OPTIMIZATION_RESULTS_CACHE:
                df = load_uploaded_dataframe(session["excel_file"])
                OPTIMIZATION_RESULTS_CACHE[cache_key] = compute_optimization(
                    df,
                    selected_tgl,
                    selected_petugas,
                    ga_params=get_ga_params(),
                )

            opt_data = OPTIMIZATION_RESULTS_CACHE[cache_key]
            route_data = opt_data["route_data"]
            map_points = opt_data["map_points"]
            route_geometry = opt_data["route_geometry"]

            result = {
                "tanggal": selected_tgl,
                "petugas": selected_petugas,
                "distance": opt_data["distance"],
                "time": opt_data["time"],
                "random_baseline": opt_data.get("random_baseline"),
                "package_count": opt_data["package_count"],
                "navigation_url": opt_data.get("navigation_url", ""),
                "process_steps": opt_data.get("process_steps", []),
            }
        except Exception as exc:
            error = str(exc)
    
    # Update daftar kurir berdasarkan tanggal yang dipilih
    petugas_filter_list = []
    if selected_tgl:
        try:
            df = load_uploaded_dataframe(session["excel_file"])
            tanggal_column = find_column(
                df,
                ["Tgl_Antaran_Pertama", "Tanggal Antaran Pertama", "Tgl Kirim", "Tanggal"],
                "tanggal antaran"
            )
            petugas_column = find_column(
                df,
                ["Petugas", "Kurir", "Nama Kurir", "Nama Petugas"],
                "nama kurir"
            )
            normalized_dates = df[tanggal_column].apply(normalize_delivery_date)
            filtered = df[normalized_dates == selected_tgl]
            petugas_filter_list = sorted(filtered[petugas_column].dropna().astype(str).str.strip().unique().tolist())
        except Exception:
            petugas_filter_list = []
    
    return render_template(
        "hasil.html",
        result=result,
        route_data=route_data,
        map_points=map_points,
        route_geometry=route_geometry,
        petugas_list=petugas_list,
        petugas_filter_list=petugas_filter_list,
        tgl_list=tgl_list,
        uploaded_file_name=uploaded_file_name,
        selected_tgl=selected_tgl,
        selected_petugas=selected_petugas,
        google_maps_api_key=GOOGLE_MAPS_API_KEY,
        error=error,
    )


# Menampilkan hasil pemetaan aktual, rute per kurir, dan navigasi Google Maps.
@app.route("/hasil-pemetaan", methods=["GET", "POST"])
def hasil_pemetaan():
    if not load_manual_assignments():
        return redirect("/input-penugasan")
    if "cluster_file" not in session:
        return redirect("/input-pemetaan")

    uploaded_file_name = os.path.basename(session["cluster_file"])
    assignment_summary = get_manual_assignment_summary()
    fast_mode = bool(session.get("pemetaan_fast_mode", True))

    # Ambil/ubah konfigurasi GA dari query string (untuk UI konfigurasi di halaman hasil pemetaan).
    if request.args.get("ga_reset") in {"1", "true", "on", "yes"}:
        session.pop("ga_params", None)
        session.modified = True

    if any(key in request.args for key in ("pop_size", "generations", "cr", "mr")):
        session["ga_params"] = parse_ga_params(request.args)
        session.modified = True

    ga_params = get_ga_params()
    ga_signature = get_ga_signature(ga_params)
    regen = request.args.get("regen") in {"1", "true", "on", "yes"}
    regen_all = request.args.get("regen_all") in {"1", "true", "on", "yes"}

    if request.args.get("save_defaults") in {"1", "true", "on", "yes"}:
        save_json_cache(GA_DEFAULTS_FILE, ga_params)

    cache_key = get_pemetaan_cache_key(session["cluster_file"], fast_mode=fast_mode)
    pemetaan_result = CLUSTER_OPTIMIZATION_RESULTS_CACHE.get(cache_key)
    error = None
    if pemetaan_result is None or "clustered_groups" not in pemetaan_result:
        try:
            cluster_df = load_uploaded_dataframe(session["cluster_file"])
            assignment_df = build_assignment_dataframe_from_manual()
            pemetaan_result = compute_pemetaan_distribution(
                cluster_df,
                assignment_df,
                fast_mode=fast_mode,
            )
            CLUSTER_OPTIMIZATION_RESULTS_CACHE[cache_key] = pemetaan_result
        except Exception as exc:
            error = str(exc)
            pemetaan_result = {
                "clustered_groups": {},
                "optimized_results": {},
                "unmatched_addresses": [],
                "distribution_summary": [],
            }

    cluster_petugas_list = sorted(
        petugas
        for petugas, group in pemetaan_result.get("clustered_groups", {}).items()
        if petugas and group.get("rows")
    )
    selected_cluster_petugas = normalize_text(request.args.get("petugas"))
    optimized_results = pemetaan_result.setdefault("optimized_results", {})

    if regen_all and cluster_petugas_list:
        print("\nMenghitung hasil...\n")
        for petugas in cluster_petugas_list:
            existing = optimized_results.get(petugas)
            existing_coords = existing.get("_coords") if isinstance(existing, dict) else None
            optimized_results[petugas] = optimize_clustered_route_for_petugas(
                petugas,
                pemetaan_result["clustered_groups"][petugas],
                ga_params=ga_params,
                coords=existing_coords,
                force_reroll=True,
                quiet=True,
                runs=3,
            )

        # Log ringkasan batch: tampilkan hanya blok ringkas sesuai format yang diminta.
        print("\nParameter GA")
        print(f"Generasi: {ga_params.get('generations', GA_GENERATIONS)}")
        print(f"Populasi: {ga_params.get('pop_size', GA_POP_SIZE)}")
        print(f"Cr: {ga_params.get('crossover_rate', GA_CROSSOVER_RATE)}")
        print(f"Mr: {ga_params.get('mutation_rate', GA_MUTATION_RATE)}")

        print("\nTotal running 3x")

        total_all = 0.0
        total_distance_all = 0.0
        total_time_all = 0.0
        total_random_distance_all = 0.0
        total_random_time_all = 0.0
        total_cplex_distance_all = 0.0
        total_cplex_time_all = 0.0
        for index, petugas in enumerate(cluster_petugas_list, start=1):
            result = optimized_results.get(petugas) or {}
            run_totals = result.get("_ga_run_totals") or []
            if not isinstance(run_totals, list) or not run_totals:
                run_totals = [0.0, 0.0, 0.0]

            print(f"Kurir {index} ({petugas})")
            courier_total = 0.0
            courier_count = 0
            for run_index, fitness_total in enumerate(run_totals, start=1):
                try:
                    fitness_total = float(fitness_total)
                except Exception:
                    fitness_total = 0.0
                courier_total += fitness_total
                courier_count += 1
                print(f"fitness total {run_index}: {fitness_total:.10f}")

            courier_avg = courier_total / max(1, courier_count)
            total_all += courier_avg
            print(f"fitness rata-rata: {courier_avg:.10f}")

            try:
                total_distance_all += float(result.get("distance", 0) or 0)
            except Exception:
                pass
            try:
                total_time_all += float(result.get("time", 0) or 0)
            except Exception:
                pass

            random_baseline = result.get("random_baseline") if isinstance(result, dict) else None
            if isinstance(random_baseline, dict):
                try:
                    total_random_distance_all += float(random_baseline.get("distance", 0) or 0)
                except Exception:
                    pass
                try:
                    total_random_time_all += float(random_baseline.get("time", 0) or 0)
                except Exception:
                    pass

            # //Kode CPLEX: hitung solusi exact per kurir (jarak optimal) untuk evaluasi GAP GA vs CPLEX
            coords = result.get("_coords") if isinstance(result, dict) else None
            if isinstance(coords, list) and len(coords) >= 2:
                try:
                    dist_matrix, time_matrix = get_matrix(coords)
                    cplex_route = solve_tsp_path_with_cplex(dist_matrix, start_index=0, time_limit_seconds=30)
                    cplex_dist_km, cplex_time_min = compute_route_totals(cplex_route, dist_matrix, time_matrix)
                    total_cplex_distance_all += cplex_dist_km
                    total_cplex_time_all += cplex_time_min
                    result["cplex_exact"] = {
                        "method": "CPLEX Exact TSP",
                        "distance": round(cplex_dist_km, 2),
                        "time": round(cplex_time_min, 2),
                        "gap_distance_pct": compute_gap_pct(cplex_dist_km, result.get("distance", 0)),
                        "gap_time_pct": compute_gap_pct(cplex_time_min, result.get("time", 0)),
                    }
                except Exception as exc:
                    result["cplex_exact"] = {
                        "method": "CPLEX Exact TSP",
                        "error": str(exc),
                    }

        print(f"\nTotal fitness semua kurir (jumlah rata-rata/kurir): {total_all:.10f}\n")
        print(f"Total jarak semua kurir: {round(total_distance_all, 2)} km")
        print(f"Total waktu semua kurir: {round(total_time_all, 2)} menit")
        print(
            "Random search semua kurir: "
            f"{round(total_random_distance_all, 2)} km, {round(total_random_time_all, 2)} menit\n"
        )
        if total_cplex_distance_all > 0 and total_cplex_time_all > 0:
            # //Kode CPLEX: rekap total solusi exact semua kurir + GAP total
            print(f"CPLEX semua kurir: {round(total_cplex_distance_all, 2)} km, {round(total_cplex_time_all, 2)} menit")
            gap_dist_all = compute_gap_pct(total_cplex_distance_all, total_distance_all)
            gap_time_all = compute_gap_pct(total_cplex_time_all, total_time_all)
            if gap_dist_all is not None:
                print(f"Gap Jarak (GA vs CPLEX): {gap_dist_all:.2f}%")
            if gap_time_all is not None:
                print(f"Gap Waktu (GA vs CPLEX): {gap_time_all:.2f}%")
            print("")
        distance_improvement_all = compute_improvement_pct(total_random_distance_all, total_distance_all)
        time_improvement_all = compute_improvement_pct(total_random_time_all, total_time_all)
        if distance_improvement_all is not None:
            print(f"Peningkatan Jarak (vs random): {distance_improvement_all:.2f}%")
        if time_improvement_all is not None:
            print(f"Peningkatan Waktu (vs random): {time_improvement_all:.2f}%")
        print("")

        CLUSTER_OPTIMIZATION_RESULTS_CACHE[cache_key] = pemetaan_result

    if selected_cluster_petugas:
        if selected_cluster_petugas not in pemetaan_result.get("clustered_groups", {}):
            error = "Kurir yang dipilih tidak ditemukan pada hasil pembagian alamat."
        else:
            try:
                existing = optimized_results.get(selected_cluster_petugas)
                existing_signature = existing.get("_ga_signature") if isinstance(existing, dict) else None
                existing_coords = existing.get("_coords") if isinstance(existing, dict) else None
                should_recompute = regen or (not existing) or (existing_signature != ga_signature)

                if should_recompute:
                    optimized_results[selected_cluster_petugas] = optimize_clustered_route_for_petugas(
                        selected_cluster_petugas,
                        pemetaan_result["clustered_groups"][selected_cluster_petugas],
                        ga_params=ga_params,
                        coords=existing_coords,
                        force_reroll=regen or (not existing) or (existing_signature != ga_signature),
                        runs=3 if should_recompute else 1,
                    )
                    # //Kode CPLEX: tampilkan hasil exact untuk 1 kurir saat generate 1 kurir
                    generated = optimized_results.get(selected_cluster_petugas) or {}
                    coords = generated.get("_coords") if isinstance(generated, dict) else None
                    if isinstance(coords, list) and len(coords) >= 2:
                        try:
                            dist_matrix, time_matrix = get_matrix(coords)
                            cplex_route = solve_tsp_path_with_cplex(dist_matrix, start_index=0, time_limit_seconds=30)
                            cplex_dist_km, cplex_time_min = compute_route_totals(cplex_route, dist_matrix, time_matrix)
                            generated["cplex_exact"] = {
                                "method": "CPLEX Exact TSP",
                                "distance": round(cplex_dist_km, 2),
                                "time": round(cplex_time_min, 2),
                                "gap_distance_pct": compute_gap_pct(cplex_dist_km, generated.get("distance", 0)),
                                "gap_time_pct": compute_gap_pct(cplex_time_min, generated.get("time", 0)),
                            }
                            print(f"CPLEX ({selected_cluster_petugas}): {round(cplex_dist_km, 2)} km, {round(cplex_time_min, 2)} menit")
                            gap_dist = generated["cplex_exact"].get("gap_distance_pct")
                            gap_time = generated["cplex_exact"].get("gap_time_pct")
                            if gap_dist is not None:
                                print(f"Gap Jarak (GA vs CPLEX): {float(gap_dist):.2f}%")
                            if gap_time is not None:
                                print(f"Gap Waktu (GA vs CPLEX): {float(gap_time):.2f}%")
                            print("")
                        except Exception as exc:
                            generated["cplex_exact"] = {
                                "method": "CPLEX Exact TSP",
                                "error": str(exc),
                            }
                            print(f"CPLEX ({selected_cluster_petugas}): {exc}")
                            print("")
                    CLUSTER_OPTIMIZATION_RESULTS_CACHE[cache_key] = pemetaan_result
            except Exception as exc:
                error = str(exc)

    selected_result = optimized_results.get(selected_cluster_petugas)
    base_display_result = {
        "results": [selected_result] if selected_result else [],
        "unmatched_addresses": pemetaan_result.get("unmatched_addresses", []),
        "distribution_summary": pemetaan_result.get("distribution_summary", []),
    }
    display_pemetaan_result = filter_pemetaan_result_by_petugas(
        base_display_result,
        selected_cluster_petugas
    ) if selected_cluster_petugas else base_display_result

    return render_template(
        "hasil_pemetaan.html",
        uploaded_file_name=uploaded_file_name,
        assignment_summary=assignment_summary,
        pemetaan_result=display_pemetaan_result,
        cluster_petugas_list=cluster_petugas_list,
        selected_cluster_petugas=selected_cluster_petugas,
        ga_params=ga_params,
        google_maps_api_key=GOOGLE_MAPS_API_KEY,
        error=error,
    )

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
#         tgl_list = sorted(df["Tgl_Kirim"].dropna().astype(str).unique())

#     return render_template(
#         "index.html",
#         petugas_list=petugas_list,
#         tgl_list=tgl_list,
#         result=result,
#         file_missing=file_missing,
#     )


# if __name__ == "__main__":
#     app.run(debug=True)
