from flask import Flask, render_template, request, redirect, session
import requests, random, os
import pandas as pd
import random

app = Flask(__name__)
app.secret_key = "genetic-secret-key"

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjQ3MTUwMTVhYjM2YzFhZmUxM2E3ODIwODkxMmE4NmMxZjQzYzJjYjAzNWMzNmRlZjgyZDhjZDM5IiwiaCI6Im11cm11cjY0In0="

# GEOCODING
def geocode(address):
    url = "https://api.openrouteservice.org/geocode/search"

    queries = [
        f"{address}, Malang, Jawa Timur",
        f"{address}, Kota Malang",
        f"{address}, Lowokwaru, Malang",
        f"{address}, Klojen, Malang",
        f"{address}, Blimbing, Malang",
        f"{address}, Sukun, Malang",
        f"{address}, Kedungkandang, Malang"
    ]

    best_score = 0
    best_coord = None

    for q in queries:
        params = {
            "api_key": ORS_API_KEY,
            "text": q,
            "boundary.country": "ID",
            "boundary.rect.min_lon": 112.55,
            "boundary.rect.min_lat": -8.10,
            "boundary.rect.max_lon": 112.75,
            "boundary.rect.max_lat": -7.85,
            "size": 5
        }

        try:
            res = requests.get(url, params=params, timeout=10).json()

            for f in res.get("features", []):
                lon, lat = f["geometry"]["coordinates"]
                props = f.get("properties", {})

                confidence = props.get("confidence", 0)

                distance_center = ((lon - 112.6303)**2 + (lat + 7.9829)**2) ** 0.5

                score = confidence + (1 / (distance_center + 0.0001))

                if score > best_score:
                    best_score = score
                    best_coord = [lon, lat]

        except:
            pass

    if best_coord:
        return best_coord

    return [112.6303, -7.9829]  # fallback pusat kota

# MATRIX API
def get_matrix(coords):
    url = "https://api.openrouteservice.org/v2/matrix/driving-car"

    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json"
    }
    locations = coords

    payload = {
        "locations": locations,
        "metrics": ["distance", "duration"]
    }

    r = requests.post(url, json=payload, headers=headers, timeout=20)

    if r.status_code != 200:
        raise Exception("ORS ERROR: " + r.text)

    data = r.json()
    return data["distances"], data["durations"]

def total_distance(route, matrix):
    # km -> meter
    return sum(matrix[route[i]][route[i+1]] * 1000
               for i in range(len(route)-1))

def total_time(route, time_matrix):
    # menit
    return sum(time_matrix[route[i]][route[i+1]] / 60
               for i in range(len(route)-1))

def calculate_fitness(route, dist_matrix, time_matrix):
    D = total_distance(route, dist_matrix)  # meter
    T = total_time(route, time_matrix)     # menit
    return 1000 / (D + T)

def pmx_crossover(p1, p2):
    size = len(p1)

    if size <= 2:
        return p1[:], p2[:]

    cx1, cx2 = sorted(random.sample(range(1, size), 2))

    c1 = [None] * size
    c2 = [None] * size

    c1[cx1:cx2] = p1[cx1:cx2]
    c2[cx1:cx2] = p2[cx1:cx2]

    def fill(child, parent):
        for i in range(size):
            if child[i] is None:
                for gene in parent:
                    if gene not in child:
                        child[i] = gene
                        break
        return child

    c1[0] = 0
    c2[0] = 0

    return fill(c1, p2), fill(c2, p1)

def swap_mutation(ind):
    if len(ind) <= 2:
        return ind

    i, j = random.sample(range(1, len(ind)), 2)
    ind[i], ind[j] = ind[j], ind[i]
    return ind

def selection_elitism(pop, fitness, elite):
    ranked = sorted(zip(pop, fitness),
                    key=lambda x: x[1],
                    reverse=True)
    return [x[0] for x in ranked[:elite]]

# GA
def genetic_algorithm(coords,
                      pop_size=40,
                      generations=80,
                      crossover_rate=0.4, #2 anak per 2 parent, jadi 0.4 untuk menghasilkan 40 anak dari 40 parent 
                      mutation_rate=0.6):

    n = len(coords)
    dist_matrix, time_matrix = get_matrix(coords)

    population = [[0] + random.sample(range(1, n), n-1)
                  for _ in range(pop_size)]

    best_fitness_log = []

    for gen in range(generations):

        fitness = [calculate_fitness(ind, dist_matrix, time_matrix) for ind in population]

        best_fitness_log.append(max(fitness))

        offspring = []

        crossover_iterations = int(crossover_rate * pop_size)

        for _ in range(crossover_iterations):
            p1, p2 = random.sample(population, 2)
            c1, c2 = pmx_crossover(p1, p2)
            offspring.extend([c1, c2])

        mutation_iterations = int(mutation_rate * pop_size)

        for _ in range(mutation_iterations):
            ind = random.choice(offspring)
            swap_mutation(ind)
            
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

    best = max(population, key=lambda r: calculate_fitness(r, dist_matrix, time_matrix))

    return best, dist_matrix, time_matrix, best_fitness_log

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/reset", methods=["GET", "POST"])
def reset():
    excel_path = session.pop("excel_file", None)
    if excel_path and os.path.exists(excel_path):
        try:
            os.remove(excel_path)
        except Exception:
            pass
    session.pop("petugas_list", None)
    session.pop("tgl_list", None)
    session.modified = True

    return redirect("/") 


@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    map_points = []
    petugas_list = []
    tgl_list = []
    uploaded_file_name = None

    # if "excel_file" in session and os.path.exists(session["excel_file"]):
    #     uploaded_file_name = os.path.basename(session["excel_file"])
    #     df = pd.read_excel(session["excel_file"])
    #     petugas_list = sorted(df["Petugas"].dropna().unique())
    #     tgl_list = sorted(df["Tgl_Kirim"].dropna().astype(str).unique())
    if "excel_file" in session:
        uploaded_file_name = os.path.basename(session["excel_file"])

        petugas_list = session.get("petugas_list", [])
        tgl_list = session.get("tgl_list", [])

    if request.method == "POST":

        if request.form.get("reset"):
            session.pop("excel_file", None)
            return redirect("/")

        if "file" in request.files and request.files["file"].filename != "":
            file = request.files["file"]

            if not file.filename.endswith((".xlsx", ".xls")):
                return "File harus Excel"

            if "excel_file" in session:
                old_file = session["excel_file"]
                if os.path.exists(old_file):
                    os.remove(old_file)

            # filename = "data_upload.xlsx"
            # filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

            # file.save(filepath)

            # # UPDATE SESSION
            # session["excel_file"] = filepath

            # return redirect("/")
            filename = "data_upload.xlsx"
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

            file.save(filepath)

            df = pd.read_excel(filepath)

            session["excel_file"] = filepath
            session["petugas_list"] = sorted(df["Petugas"].dropna().unique().tolist())
            session["tgl_list"] = sorted(df["Tgl_Kirim"].dropna().astype(str).unique().tolist())

            return redirect("/")

        # Proses optimasi setelah filter dipilih
        if "excel_file" in session:
            selected_petugas = request.form.get("petugas")
            selected_tgl = request.form.get("tgl")

            if selected_petugas and selected_tgl:
                df = pd.read_excel(session["excel_file"])

                filtered = df[
                    (df["Petugas"] == selected_petugas) &
                    (df["Tgl_Kirim"].astype(str) == selected_tgl)
                ]

              
                # addresses = filtered.iloc[:, 11].dropna().unique().tolist()
                data_list = []

                for _, row in filtered.iterrows():
                    alamat = row.iloc[11]
                    no_resi = row.iloc[0]      # Kolom A
                    nama = row.iloc[10]        # Kolom K

                    if pd.notna(alamat):
                        data_list.append({
                            "alamat": alamat,
                            "resi": no_resi,
                            "nama": nama
                        })

                addresses = [d["alamat"] for d in data_list]
                MAX_LOCATIONS = 20   

                if len(addresses) > MAX_LOCATIONS:
                    addresses = addresses[:MAX_LOCATIONS]

                locations = ["Kantor Pos Besar Malang"] + addresses
                coords = [geocode(a) for a in locations]
                # FILTER KOORDINAT INVALID
                clean_coords = []
                clean_locations = []

                for loc, (lon, lat) in zip(locations, coords):
                    if 112.55 <= lon <= 112.75 and -8.10 <= lat <= -7.85:
                        clean_coords.append([lon, lat])
                        clean_locations.append(loc)

                coords = clean_coords
                locations = clean_locations
                # DEBUG
                print("TOTAL TITIK:", len(coords))
                print("CONTOH KOORD:", coords[0])
                print("FORMAT ORS:", [coords[0][1], coords[0][0]])

                route, dist_matrix, time_matrix, fitness_log = genetic_algorithm(
                coords,
                pop_size=40,
                generations=80,
                crossover_rate=0.85,
                mutation_rate=0.12
                )

                total_dist = sum(dist_matrix[route[i]][route[i+1]] for i in range(len(route)-1)) / 1000
                total_time = sum(time_matrix[route[i]][route[i+1]] for i in range(len(route)-1)) / 60

                for order, idx in enumerate(route):
                    lon, lat = coords[idx]
                    map_points.append({
                        "name": locations[idx],
                        "lat": lat,
                        "lng": lon,
                        "order": order + 1
                    })

                kota_list = filtered.iloc[:, 12].dropna().unique().tolist()
                route_data = []

                for i, idx in enumerate(route):
                    if idx == 0:
                        route_data.append({
                            "no": i+1,
                            "alamat": "Kantor Pos Besar Malang",
                            "resi": "-",
                            "nama": "-"
                        })
                    else:
                        d = data_list[idx-1]
                        route_data.append({
                            "no": i+1,
                            "alamat": d["alamat"],
                            "resi": d["resi"],
                            "nama": d["nama"]
                        })

                result = {
                "petugas": selected_petugas,
                "tanggal": selected_tgl,
                "kota": ", ".join(kota_list) if kota_list else "-",
                "jumlah": len(filtered),
                "route_data": route_data,
                "route_order": route,
                "distance": round(total_dist, 2),
                "time": round(total_time, 2)
                }

    return render_template(
        "index.html",
        result=result,
        map_points=map_points,
        petugas_list=petugas_list,
        tgl_list=tgl_list,
        uploaded_file_name=uploaded_file_name,
    )

if __name__ == "__main__":
    app.run(debug=True)

# @app.route("/", methods=["GET", "POST"])
# def index():
#     petugas_list = []
#     tgl_list = []
#     result = None
#     file_missing = False

#     # ===== CEK FILE SESSION =====
#     if "excel_file" in session and not os.path.exists(session["excel_file"]):
#         file_missing = True
#         session.pop("excel_file", None)

#     # ===== MODE POST =====
#     if request.method == "POST":

#         # ==== MODE UPLOAD ====
#         if "upload" in request.form:
#             file = request.files.get("file")
#             if file and file.filename != "":
#                 filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
#                 file.save(filepath)
#                 session["excel_file"] = filepath
#                 return redirect("/")

#         # ==== MODE PROSES ====
#         if "process" in request.form and "excel_file" in session:
#             if not os.path.exists(session["excel_file"]):
#                 session.pop("excel_file", None)
#                 return redirect("/")

#             df = pd.read_excel(session["excel_file"])

#             selected_petugas = request.form.get("petugas")
#             selected_tgl = request.form.get("tgl")

#             if selected_petugas and selected_tgl:
#                 filtered = df[
#                     (df["Petugas"] == selected_petugas)
#                     & (df["Tgl_Kirim"].astype(str) == selected_tgl)
#                 ]

#                 result = filtered.to_dict(orient="records")

#     # ===== AMBIL FILTER =====
#     if "excel_file" in session and os.path.exists(session["excel_file"]):
#         df = pd.read_excel(session["excel_file"])
#         petugas_list = sorted(df["Petugas"].dropna().unique())
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