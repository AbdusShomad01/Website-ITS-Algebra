import sqlite3
import random
import pandas as pd
import os
from flask import Flask, render_template, request, g, url_for, redirect, session

app = Flask(__name__)
app.secret_key = 'kunci_rahasia_super_aman_admin_ganteng' # Kunci sesi
DATABASE = 'its_database.db'

# ==========================================
#        1. KONFIGURASI DATA MATERI
# ==========================================
# Pastikan ID ini sama dengan kolom 'materi_id' di Excel Anda
daftar_materi = [
    {"id": "bab1", "nama": "1. Algebraic Representation & Formulae"},
    {"id": "bab2", "nama": "2. Algebraic Manipulation"},
    {"id": "bab3", "nama": "3. Solution of Equations & Inequalities"},
    {"id": "bab4", "nama": "4. Graphs in Practical Situations"},
    {"id": "bab5", "nama": "5. Straight-Line Graphs"},
    {"id": "bab6", "nama": "6. Graphs of Functions"},
    {"id": "bab7", "nama": "7. Number Sequence"},
    {"id": "bab8", "nama": "8. Indices"},
    {"id": "bab9", "nama": "9. Proportion"},
    {"id": "bab10", "nama": "10. Linear Programming"},
    {"id": "bab11", "nama": "11. Functions"},
    {"id": "bab12", "nama": "12. Differentiation"},
    {"id": "bab13", "nama": "13. Integration"},
    # Ujian Akhir
    {"id": "final_exam", "nama": "FINAL EVALUATION", "is_exam": True}
]

# ==========================================
#        2. FUNGSI MEMBACA EXCEL
# ==========================================
def read_excel_questions(filename):
    """Membaca file Excel soal dengan aman dan mengubahnya jadi list."""
    print(f"--- Mencoba membaca file: {filename} ---")
    
    if not os.path.exists(filename):
        print(f"[WARNING] File '{filename}' tidak ditemukan. Pastikan nama & lokasi benar.")
        return []

    try:
        df = pd.read_excel(filename)
        df.columns = [c.lower().strip() for c in df.columns] # Normalkan nama kolom (huruf kecil)
        df = df.fillna("") # Hindari error data kosong
        
        soal_list = []
        for index, row in df.iterrows():
            # Ambil penjelasan jika ada, kalau tidak ada string kosong
            penjelasan = str(row['explanation']) if 'explanation' in df.columns else ""
            
            soal = {
                "id": int(row['id']),
                "materi_id": str(row['materi_id']),
                "text": str(row['text']),
                "correct_answer": str(row['correct_answer']).strip(),
                "options": [
                    str(row['option_a']), 
                    str(row['option_b']), 
                    str(row['option_c']), 
                    str(row['option_d'])
                ],
                "explanation": penjelasan
            }
            soal_list.append(soal)
            
        print(f"[SUKSES] Berhasil memuat {len(soal_list)} soal dari {filename}.")
        return soal_list
        
    except Exception as e:
        print(f"[ERROR] Gagal membaca {filename}: {e}")
        return []

# --- LOAD DATA SAAT STARTUP ---
# 1. Bank Soal Latihan
bank_soal_latihan = read_excel_questions('bank_soal.xlsx')
if not bank_soal_latihan:
    # Data Dummy jika Excel belum siap
    bank_soal_latihan = [{"id": 999, "materi_id": "bab1", "text": "Contoh Soal (Excel Kosong)", "correct_answer": "A", "options":["A","B","C","D"], "explanation":"Isi bank_soal.xlsx dulu."}]

# 2. Bank Soal Pretest
soal_pretest_excel = read_excel_questions('pretest.xlsx')

# ==========================================
#        3. DATABASE SETUP
# ==========================================
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None: db.close()

def init_db():
    with app.app_context():
        db = get_db()
        # Tabel Mastery: Menyimpan Nilai BKT (p_L) dan Status Baca (is_read)
        db.execute('''CREATE TABLE IF NOT EXISTS mastery (
                user_id TEXT, 
                materi_id TEXT, 
                p_L REAL, 
                is_read INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, materi_id))''')
        
        # Tabel Users: Menyimpan akun dan status pretest
        db.execute('''CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY, 
                password TEXT, 
                has_pretest INTEGER DEFAULT 0,
                pretest_score REAL DEFAULT 0)''')
        db.commit()

# ==========================================
#        4. LOGIKA BKT & GAMIFIKASI
# ==========================================
params = {"prob_guess": 0.25, "prob_slip": 0.10, "prob_learn": 0.20}

def hitung_bkt(current_pL, is_correct):
    L, G, S, T = current_pL, params["prob_guess"], params["prob_slip"], params["prob_learn"]
    if is_correct:
        post = (L * (1 - S)) / ((L * (1 - S)) + ((1 - L) * G))
    else:
        post = (L * S) / ((L * S) + ((1 - L) * (1 - G)))
    # Batasi max 0.99 agar selalu ada ruang belajar
    return min(post + ((1 - post) * T), 0.99)

def get_mastery_data(user_id, m_id):
    db = get_db()
    row = db.execute('SELECT p_L, is_read FROM mastery WHERE user_id = ? AND materi_id = ?', (user_id, m_id)).fetchone()
    if row: return row['p_L'], row['is_read']
    return 0.5, 0 # Default nilai awal

def set_mastery(user_id, m_id, val, is_read=0):
    db = get_db()
    db.execute('''INSERT INTO mastery (user_id, materi_id, p_L, is_read) 
                  VALUES (?, ?, ?, ?) 
                  ON CONFLICT(user_id, materi_id) DO UPDATE SET p_L=excluded.p_L''', 
                  (user_id, m_id, val, is_read))
    db.commit()

def mark_as_read(user_id, m_id):
    db = get_db()
    current_pL, _ = get_mastery_data(user_id, m_id)
    db.execute('''INSERT INTO mastery (user_id, materi_id, p_L, is_read) VALUES (?, ?, ?, 1) 
                  ON CONFLICT(user_id, materi_id) DO UPDATE SET is_read=1''', (user_id, m_id, current_pL))
    db.commit()

def is_chapter_locked(user_id, target_materi_id):
    target_index = -1
    for i, m in enumerate(daftar_materi):
        if m['id'] == target_materi_id:
            target_index = i
            break
    
    # Bab 1 selalu terbuka
    if target_index <= 0: return False
    
    # Cek nilai bab sebelumnya
    prev_materi_id = daftar_materi[target_index - 1]['id']
    prev_pL, _ = get_mastery_data(user_id, prev_materi_id)
    
    # Jika nilai bab sebelumnya < 90%, maka bab ini TERKUNCI
    if prev_pL < 0.90: return True
    return False

# ==========================================
#               ROUTES (HALAMAN)
# ==========================================

# --- LOGIN & REGISTER ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user and user['password'] == password:
            session['user_id'] = user['username']
            # Cek Pretest
            if user['has_pretest'] == 0:
                return redirect(url_for('pretest'))
            else:
                return redirect(url_for('dashboard'))
                
        return render_template('login.html', error='Username atau Password Salah')
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    try:
        db = get_db()
        db.execute('INSERT INTO users (username, password, has_pretest, pretest_score) VALUES (?, ?, 0, 0)', 
                   (request.form['username'], request.form['password']))
        db.commit()
        session['user_id'] = request.form['username']
        return redirect(url_for('pretest'))
    except:
        return render_template('login.html', error="Username sudah dipakai!")

# --- PRETEST (UI BARU) ---
@app.route('/pretest', methods=['GET', 'POST'])
def pretest():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    # Gunakan soal dari Excel Pretest
    # Jika kosong/error, ambil 5 soal dari bank soal utama sebagai cadangan
    daftar_soal = soal_pretest_excel if soal_pretest_excel else bank_soal_latihan[:5]

    if request.method == 'POST':
        score_counter = 0
        total_soal = len(daftar_soal)

        for soal in daftar_soal:
            jawaban_user = request.form.get(f"jawaban_{soal['id']}")
            
            is_correct = False
            if jawaban_user:
                # Bandingkan String Jawaban
                is_correct = (str(jawaban_user).strip().lower() == str(soal['correct_answer']).strip().lower())
            
            if is_correct: score_counter += 1

            # Set Nilai Awal Mastery (Benar=0.75, Salah=0.20)
            nilai_awal = 0.75 if is_correct else 0.20
            set_mastery(user_id, soal['materi_id'], nilai_awal, is_read=0)
        
        # Hitung Nilai Murni Pretest (0-100)
        final_pretest_score = (score_counter / total_soal) * 100 if total_soal > 0 else 0

        # Simpan ke DB
        db = get_db()
        db.execute('UPDATE users SET has_pretest = 1, pretest_score = ? WHERE username = ?', (final_pretest_score, user_id))
        db.commit()
        
        return redirect(url_for('dashboard'))

    return render_template('pretest_new.html', user_id=user_id, daftar_soal=daftar_soal)

# --- DASHBOARD (HOME - BERITA) ---
@app.route('/')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    # Cek user yang bypass URL
    user = get_db().execute('SELECT has_pretest FROM users WHERE username=?', (user_id,)).fetchone()
    if not user or user['has_pretest'] == 0: return redirect(url_for('pretest'))

    # Data Berita Dummy (Bisa diedit isinya di sini)
    berita_list = [
        {"judul": "Selamat Datang di Gebra Math!", "tanggal": "Hari Ini", "isi": "Mulai petualangan belajarmu di menu My Lessons."},
        {"judul": "Fitur Baru: Mode Game", "tanggal": "Update", "isi": "Coba asah kecepatan berhitungmu di menu Game sekarang juga!"},
        {"judul": "Tips Belajar", "tanggal": "Tips", "isi": "Jangan lupa membaca PDF materi sebelum mengerjakan latihan soal agar nilai mastery cepat naik."}
    ]
    
    return render_template('dashboard.html', user_id=user_id, berita_list=berita_list)

# --- MY LESSONS (DAFTAR 13 BAB) ---
@app.route('/lessons')
def lessons():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    data_display = []
    for m in daftar_materi:
        # Cek apakah data mastery SUDAH ADA di database?
        row = get_db().execute('SELECT p_L FROM mastery WHERE user_id = ? AND materi_id = ?', (user_id, m['id'])).fetchone()
        
        if row:
            # Jika sudah ada, ambil nilainya
            real_pL = row['p_L']
            tampilan_persen = round(real_pL * 100)
        else:
            # Jika BELUM ADA, tampilkan 0%
            tampilan_persen = 0
            
        locked = is_chapter_locked(user_id, m['id'])
        
        data_display.append({
            "id": m['id'], "nama": m['nama'], 
            "persen": tampilan_persen, 
            "is_locked": locked, 
            "is_exam": m.get('is_exam', False)
        })
    return render_template('lessons.html', user_id=user_id, daftar_materi=data_display)

# --- MY PROGRESS (RAPOR DIGITAL) ---
@app.route('/my_progress')
def my_progress():
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    # 1. Ambil Nilai Pretest
    user = get_db().execute('SELECT pretest_score FROM users WHERE username = ?', (user_id,)).fetchone()
    try:
        pretest_score = round(user['pretest_score'], 1) if user and user['pretest_score'] is not None else 0
    except:
        pretest_score = 0

    # 2. Hitung Progress & Exam TERPISAH
    total_mastery = 0
    count_materi = 0
    final_exam_score = 0
    
    for m in daftar_materi:
        # Cek data di DB
        row = get_db().execute('SELECT p_L FROM mastery WHERE user_id = ? AND materi_id = ?', (user_id, m['id'])).fetchone()
        
        if row:
            real_score = row['p_L']
        else:
            real_score = 0 # Jika belum ada data, anggap 0
        
        # Pisahkan Logika:
        if m.get('is_exam'):
            # Ini Ujian Akhir
            final_exam_score = round(real_score * 100, 1)
        else:
            # Ini Materi Pelajaran (Bab 1-13)
            total_mastery += real_score
            count_materi += 1
            
    # Hitung Rata-rata HANYA dari materi pelajaran
    if count_materi > 0:
        avg_progress = round((total_mastery / count_materi) * 100, 1)
    else:
        avg_progress = 0
    
    # 3. Status Lulus
    is_graduated = (avg_progress >= 90 and final_exam_score >= 90)
    
    return render_template('my_progress.html', 
                           user_id=user_id,
                           pretest=pretest_score,
                           progress=avg_progress,
                           exam=final_exam_score,
                           lulus=is_graduated)

# --- BELAJAR (LATIHAN SOAL + PDF) ---
@app.route('/belajar/<materi_id>', methods=['GET', 'POST'])
def belajar(materi_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    user_id = session['user_id']
    
    if is_chapter_locked(user_id, materi_id):
        return redirect(url_for('lessons'))

    soal_relevan = [s for s in bank_soal_latihan if s['materi_id'] == materi_id]
    current_pL, is_read = get_mastery_data(user_id, materi_id)
    nama_pdf = f"{materi_id}.pdf"

    if request.method == 'POST':
        jawaban = request.form['jawaban']
        soal_id = int(request.form['soal_id'])
        soal_obj = next((s for s in bank_soal_latihan if s['id'] == soal_id), None)
        
        is_correct = (jawaban.lower().strip() == soal_obj['correct_answer'].lower().strip())
        new_val = hitung_bkt(current_pL, is_correct)
        db = get_db()
        db.execute('UPDATE mastery SET p_L = ? WHERE user_id = ? AND materi_id = ?', (new_val, user_id, materi_id))
        db.commit()
        
        pesan = "JAWABAN BENAR! 🎉" if is_correct else "JAWABAN KURANG TEPAT"
        penjelasan = "" if is_correct else soal_obj['explanation']
        
        return render_template('belajar.html', materi_id=materi_id, pesan=pesan, is_correct=is_correct, 
                               explanation=penjelasan, is_read=is_read, nama_pdf=nama_pdf)

    if not soal_relevan:
        return render_template('belajar.html', materi_id=materi_id, is_read=is_read, nama_pdf=nama_pdf,
                               soal={"text": "Soal belum tersedia.", "id": 0})

    soal_terpilih = random.choice(soal_relevan)
    return render_template('belajar.html', materi_id=materi_id, soal=soal_terpilih, is_read=is_read, nama_pdf=nama_pdf)

@app.route('/mark_read/<materi_id>', methods=['POST'])
def mark_read_route(materi_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    mark_as_read(session['user_id'], materi_id)
    return redirect(url_for('belajar', materi_id=materi_id))

# --- GAME ZONE ---
@app.route('/game')
def game():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('game.html', user_id=session['user_id'])

@app.route('/play/<game_id>')
def play_game(game_id):
    if 'user_id' not in session: return redirect(url_for('login'))
    if game_id == "math-racer": return render_template('math_racer.html')
    
    # Placeholder untuk game lain
    game_name = "Space Puzzle" if game_id == "space-puzzle" else "Galactic Mission"
    return render_template('play_game.html', user_id=session['user_id'], game_name=game_name)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)