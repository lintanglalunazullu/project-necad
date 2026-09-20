# scripts/reindex_documents.py — Re-indexasi data dokumen Supabase untuk akurasi RAG tinggi
import os
import sys

# Tambahkan services/api ke sys.path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_api_dir = os.path.abspath(os.path.join(_current_dir, "..", "services", "api"))
if _api_dir not in sys.path:
    sys.path.insert(0, _api_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(_api_dir, ".env"))
load_dotenv()

from supabase import create_client
import config
from ai.embedding import embed_text, validate_embedding

def run_reindex():
    print("🚀 Memulai proses re-indexing dokumen untuk akurasi tinggi...")
    sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)

    # 1. Pastikan jadwal-ekstrakurikuler berkategori 'public'
    res_ekskul = sb.table("pdf_documents").update({"category": "public"}).eq("pdf_name", "jadwal-ekstrakurikuler").execute()
    print(f"✅ Kategori jadwal-ekstrakurikuler diperbarui ke 'public' ({len(res_ekskul.data or [])} baris)")

    # 2. Re-chunk profile-school menjadi blok tematik presisi tinggi (~300 kata)
    profile_chunks = [
        {
            "pdf_name": "profile-school",
            "category": "public",
            "content": (
                "[DOKUMEN: profile-school | TOPIK: Identitas Sekolah, NPSN, & Kontak]\n"
                "PROFIL SEKOLAH TAHUN PELAJARAN 2026/2027\n"
                "Nama Sekolah: SMP Negeri 2 Cibungbulang (SMPN 2 Cibungbulang)\n"
                "NPSN (Nomor Pokok Sekolah Nasional): 20200640\n"
                "NSS (Nomor Statistik Sekolah): 201020216213\n"
                "Tahun Pendirian / Beroperasi: 1998 / 1998\n"
                "Alamat Sekolah: Jalan Desa Girimulya RT.02 RW.01, Desa Giri Mulya, Kecamatan Cibungbulang, Kabupaten Bogor, Provinsi Jawa Barat.\n"
                "Nomor Telepon: (0251) 8647771\n"
                "Email: smpn_2cibungbulang@yahoo.co.id\n"
                "Website Resmi: https://smpn2cibungbulang.sch.id"
            )
        },
        {
            "pdf_name": "profile-school",
            "category": "public",
            "content": (
                "[DOKUMEN: profile-school | TOPIK: Kepala Sekolah & Sarana Lahan]\n"
                "Kepala Sekolah SMP Negeri 2 Cibungbulang:\n"
                "Nama: Rosihan Anwar, S.Pd., M.M.\n"
                "Pendidikan Terakhir: S2 Magister Manajemen (Tahun 2012)\n"
                "Nomor HP/Kontak Kepala Sekolah: 081319843384\n\n"
                "Data Kepemilikan Tanah dan Bangunan:\n"
                "a. Status Tanah: Milik Pemda / Bersertifikat\n"
                "b. Luas Tanah Sekolah: 10.300 M² (sepuluh ribu tiga ratus meter persegi)\n"
                "c. Luas Bangunan Sekolah: 6.045 M² (enam ribu empat puluh lima meter persegi)"
            )
        },
        {
            "pdf_name": "profile-school",
            "category": "public",
            "content": (
                "[DOKUMEN: profile-school | TOPIK: Visi dan Misi Sekolah]\n"
                "VISI SEKOLAH SMPN 2 CIBUNGBULANG:\n"
                "Terwujudnya Sekolah yang Berkembang Profil Pelajar Pancasila unggul dalam prestasi Akademik dan Non Akademik serta berwawasan lingkungan.\n\n"
                "MISI SEKOLAH SMPN 2 CIBUNGBULANG:\n"
                "1. Membangun karakter yang mengintegrasikan nilai-nilai moral dan etika dalam kurikulum untuk membentuk karakter yang positif, berkebhinekaan, tangguh dan berintegritas sesuai Profil Pelajar Pancasila.\n"
                "2. Menyediakan Pendidikan yang Berkualitas: Mendorong pembelajaran yang mendalam dan bermakna bagi semua peserta didik dengan memberikan akses ke sumber daya Pendidikan yang berkualitas.\n"
                "3. Meningkatkan Prestasi Akademik dan Non-Akademik: Mengembangkan bakat, minat, dan potensi peserta didik melalui kegiatan kokurikuler dan ekstrakurikuler serta kompetisi."
            )
        },
        {
            "pdf_name": "profile-school",
            "category": "public",
            "content": (
                "[DOKUMEN: profile-school | TOPIK: Sarana Prasarana & Sanitasi]\n"
                "Data Ruang dan Sarana Prasarana SMPN 2 Cibungbulang:\n"
                "1. Laboratorium Komputer: Luas 6 x 5 meter, memadai, digunakan setiap hari untuk kegiatan pembelajaran (kapasitas 20 orang).\n"
                "2. Sanitasi & Toilet:\n"
                "   - WC Guru: 1 ruang (ukuran 6 x 5 = 30 M²)\n"
                "   - WC Siswa: 14 ruang (ukuran 3 x 2 x 14 = 84 M²)\n"
                "3. Ruang Koperasi: 1 ruang (ukuran 12 x 10 = 120 M²)\n"
                "4. Hall / Lobi: 1 ruang (ukuran 5 x 10 = 50 M²)\n"
                "5. Perpustakaan dan Laboratorium IPA tersedia untuk kegiatan akademik."
            )
        },
        {
            "pdf_name": "profile-school",
            "category": "public",
            "content": (
                "[DOKUMEN: profile-school | TOPIK: Tenaga Pendidik & Guru Mata Pelajaran]\n"
                "Daftar Guru dan Pengajar di SMP Negeri 2 Cibungbulang:\n"
                "- Guru IPA: Dedi Sutendi, S.Pd (S1/IPA/2001), Asti Wigianti, S.Pd (S1/IPA/2010), Bambang Ilham Firdaus, S.Pd (S1/IPA/2018)\n"
                "- Guru Matematika: Ficka Anggraeny, S.Pd (S1/Matematika/2013), Khotimah, S.Pd (S1/Matematika/2017), Tata, S.Kom (S1/Informatika/2012)\n"
                "- Guru PJOK (Pendidikan Jasmani): Atep Nugraha Darisman, S.Pd (S1/Penjas/2011)\n"
                "- Guru PAI (Pendidikan Agama Islam): Ahmad Yudi Miftahudin, S.Pd.I (S1/PAI)\n"
                "- Guru Bahasa Sunda: Reni Yusnita, SP."
            )
        }
    ]

    print("🗑️ Menghapus chunk lama profile-school...")
    sb.table("pdf_documents").delete().eq("pdf_name", "profile-school").execute()

    print("🧠 Menghitung embedding Gemini untuk chunk baru profile-school...")
    rows_to_insert = []
    for item in profile_chunks:
        emb = embed_text(item["content"])
        if not validate_embedding(emb):
            raise ValueError("Embedding tidak valid")
        rows_to_insert.append({
            "pdf_name": item["pdf_name"],
            "category": item["category"],
            "content": item["content"],
            "embedding": emb,
        })

    ins_res = sb.table("pdf_documents").insert(rows_to_insert).execute()
    print(f"✅ Berhasil memasukkan {len(ins_res.data or [])} chunk baru terstruktur untuk profile-school.")

    # 3. Re-chunk tata-tertib-siswa menjadi 3 chunk tematik
    tata_tertib_chunks = [
        {
            "pdf_name": "tata-tertib-siswa",
            "category": "public",
            "content": (
                "[DOKUMEN: tata-tertib-siswa | TOPIK: Ketertiban Kelas & Istirahat]\n"
                "Tata Tertib Siswa SMP Negeri 2 Cibungbulang:\n"
                "1. Waktu Istirahat: Murid tidak diperkenankan berada di dalam kelas waktu istirahat. Sanksi: Ditegur dan diingatkan.\n"
                "2. Pergantian Jam Pelajaran: Murid dilarang keluar kelas pada waktu pergantian jam pelajaran tanpa izin. Sanksi: Ditegur dan diarahkan kembali ke kelas.\n"
                "3. Izin Meninggalkan Sekolah: Murid yang meninggalkan sekolah sebelum jam pelajaran selesai wajib melapor dan membawa surat izin dari Guru Piket/BP."
            )
        },
        {
            "pdf_name": "tata-tertib-siswa",
            "category": "public",
            "content": (
                "[DOKUMEN: tata-tertib-siswa | TOPIK: Ibadah & Shalat Berjamaah]\n"
                "Tata Tertib Keagamaan dan Peribadatan Siswa:\n"
                "1. Shalat Dhuhur dan Ashar Berjamaah: Wajib diikuti oleh seluruh murid muslim sesuai jadwal yang ditentukan sekolah.\n"
                "2. Konsekuensi / Sanksi Pelanggaran: Murid muslim yang tidak melaksanakan shalat dhuhur atau ashar berjamaah akan ditegur dan disuruh langsung shalat.\n"
                "3. Murid non-muslim melaksanakan kegiatan keagamaan atau literasi terarah sesuai bimbingan guru pendamping."
            )
        },
        {
            "pdf_name": "tata-tertib-siswa",
            "category": "public",
            "content": (
                "[DOKUMEN: tata-tertib-siswa | TOPIK: Pakaian Seragam & Kedisiplinan]\n"
                "Tata Tertib Pakaian dan Kerapian Siswa:\n"
                "1. Pakaian Seragam: Siswa wajib mengenakan seragam resmi lengkap dengan atribut (badge OSIS, lokasi sekolah, dasi, ikat pinggang hitam) sesuai hari yang ditentukan.\n"
                "2. Sepatu & Kaus Kaki: Sepatu warna hitam dominan dengan kaus kaki putih/hitam sesuai ketentuan.\n"
                "3. Rambut & Aksesoris: Rambut siswa laki-laki dipotong rapi (tidak gondrong, tidak diwarnai). Siswa dilarang memakai perhiasan berlebih atau tato."
            )
        }
    ]

    print("🗑️ Menghapus chunk lama tata-tertib-siswa...")
    sb.table("pdf_documents").delete().eq("pdf_name", "tata-tertib-siswa").execute()

    print("🧠 Menghitung embedding Gemini untuk tata-tertib-siswa...")
    tt_rows = []
    for item in tata_tertib_chunks:
        emb = embed_text(item["content"])
        if not validate_embedding(emb):
            raise ValueError("Embedding tidak valid")
        tt_rows.append({
            "pdf_name": item["pdf_name"],
            "category": item["category"],
            "content": item["content"],
            "embedding": emb,
        })

    ins_tt = sb.table("pdf_documents").insert(tt_rows).execute()
    print(f"✅ Berhasil memasukkan {len(ins_tt.data or [])} chunk baru terstruktur untuk tata-tertib-siswa.")

    # 4. Re-chunk jadwal-ekstrakurikuler
    ekskul_content = (
        "[DOKUMEN: jadwal-ekstrakurikuler | TOPIK: Daftar Semua Kegiatan Ekstrakurikuler & Jadwal Hari]\n"
        "DAFTAR EKSTRAKURIKULER (EKSKUL) DAN JADWAL KEGIATAN SMP NEGERI 2 CIBUNGBULANG TAHUN PELAJARAN 2026/2027:\n\n"
        "Daftar Kegiatan Ekstrakurikuler yang ada di sekolah:\n"
        "1. Pramuka: Hari Kamis (Ekskul Wajib)\n"
        "2. PMR (Palang Merah Remaja): Hari Kamis (Ekskul Wajib)\n"
        "3. Passus (Pasukan Khusus): Hari Kamis (Ekskul Wajib)\n"
        "4. Rohis (Kerohanian Islam): Hari Jumat (Ekskul Pilihan)\n"
        "5. Futsal: Hari Jumat (Ekskul Pilihan)\n"
        "6. Basket (Bola Basket): Hari Selasa (Ekskul Pilihan)\n"
        "7. Voli (Bola Voli): Hari Rabu (Ekskul Pilihan)\n"
        "8. Seni Musik: Hari Jumat (Ekskul Pilihan)\n"
        "9. Seni Tari: Hari Senin (Ekskul Pilihan)\n"
        "10. Marching Band: Hari Rabu (Ekskul Pilihan)\n"
        "11. English Club: Hari Selasa (Ekskul Pilihan)\n"
        "12. MIPAS (MIPA Siswa): Hari Rabu (Ekskul Pilihan)\n"
        "13. PLH (Pendidikan Lingkungan Hidup): Hari Senin (Ekskul Pilihan)\n\n"
        "Catatan: Ekstrakurikuler Pramuka, PMR, dan Passus wajib diikuti sesuai jadwal hari Kamis."
    )
    print("🧠 Menghitung embedding Gemini untuk jadwal-ekstrakurikuler...")
    emb_ekskul = embed_text(ekskul_content)
    sb.table("pdf_documents").delete().eq("pdf_name", "jadwal-ekstrakurikuler").execute()
    sb.table("pdf_documents").insert([{
        "pdf_name": "jadwal-ekstrakurikuler",
        "category": "public",
        "content": ekskul_content,
        "embedding": emb_ekskul,
    }]).execute()
    print("✅ Berhasil memasukkan chunk baru terstruktur untuk jadwal-ekstrakurikuler.")

    # 5. Re-chunk wali-kelas
    wali_chunks = [
        {
            "pdf_name": "wali-kelas",
            "category": "public",
            "content": (
                "[DOKUMEN: wali-kelas | KELAS 7 / VII]\n"
                "DAFTAR WALI KELAS VII (KELAS 7) SMP NEGERI 2 CIBUNGBULANG TP 2026/2027:\n"
                "- Wali Kelas 7.1 / VII-1: Hj. Rahmatullaeliah, S. Pd.\n"
                "- Wali Kelas 7.2 / VII-2: Fitri Inayah, S.Pd.\n"
                "- Wali Kelas 7.3 / VII-3: Ika Permana, S.Pd.\n"
                "- Wali Kelas 7.4 / VII-4: Nonok Fatonah, S. Pd.\n"
                "- Wali Kelas 7.5 / VII-5: Iwan Kurniawan, S.Pd.\n"
                "- Wali Kelas 7.6 / VII-6: Atep Nugraha Darisman, S.Pd.\n"
                "- Wali Kelas 7.7 / VII-7: Mega Suci Ramdani, SH, S.Pd.\n"
                "- Wali Kelas 7.8 / VII-8: Nuris Tia Andina, S.Pd.\n"
                "- Wali Kelas 7.9 / VII-9: Reni Yusnita, SP.\n"
                "- Wali Kelas 7.10 / VII-10: Nidaan Chofiyyah Astari, S.Pd."
            ),
        },
        {
            "pdf_name": "wali-kelas",
            "category": "public",
            "content": (
                "[DOKUMEN: wali-kelas | KELAS 8 / VIII]\n"
                "DAFTAR WALI KELAS VIII (KELAS 8) SMP NEGERI 2 CIBUNGBULANG TP 2026/2027:\n"
                "- Wali Kelas 8.1 / VIII-1: A. Kusdinar, S. Pd.\n"
                "- Wali Kelas 8.2 / VIII-2: Bambang Ilham F., S.Pd.\n"
                "- Wali Kelas 8.3 / VIII-3: Khotimah, S.Pd.\n"
                "- Wali Kelas 8.4 / VIII-4: Fajar Zikri Utama, S.Pd.\n"
                "- Wali Kelas 8.5 / VIII-5: Hj. Mela Dewi Rahmawati, S. Pd.\n"
                "- Wali Kelas 8.6 / VIII-6: Tata, S.Kom.\n"
                "- Wali Kelas 8.7 / VIII-7: Asti Wigianti, S.Pd.\n"
                "- Wali Kelas 8.8 / VIII-8: Dina Rosdiana, S.Pd.\n"
                "- Wali Kelas 8.9 / VIII-9: Arum Nuraeni, S.Pd.\n"
                "- Wali Kelas 8.10 / VIII-10: Yayah Robaiyah, S. Pd. I."
            ),
        },
        {
            "pdf_name": "wali-kelas",
            "category": "public",
            "content": (
                "[DOKUMEN: wali-kelas | KELAS 9 / IX]\n"
                "DAFTAR WALI KELAS IX (KELAS 9) SMP NEGERI 2 CIBUNGBULANG TP 2026/2027:\n"
                "- Wali Kelas 9.1 / IX-1: Anik Tri Handayani, S.Pd.\n"
                "- Wali Kelas 9.2 / IX-2: Maya, S.Pd.\n"
                "- Wali Kelas 9.3 / IX-3: Mahmud Badarudin, S.Pd., M.Han.\n"
                "- Wali Kelas 9.4 / IX-4: Elin Erlina, S. Pd.\n"
                "- Wali Kelas 9.5 / IX-5: Santi Komalapuri, S. Pd.\n"
                "- Wali Kelas 9.6 / IX-6: Dedi Sutendi, S.Pd.\n"
                "- Wali Kelas 9.7 / IX-7: Ficka Anggraeny, S.Pd.\n"
                "- Wali Kelas 9.8 / IX-8: Ahmad Yudi Miftahudin, S.Pd.I.\n"
                "- Wali Kelas 9.9 / IX-9: Fitria Pandyasari, S.Pd.\n"
                "- Wali Kelas 9.10 / IX-10: Neneng Danukarti, SE, MM.\n\n"
                "Kepala Sekolah: Rosihan Anwar, S. Pd. MM (NIP. 196608151991031008)"
            ),
        },
    ]

    print("🧠 Menghitung embedding Gemini untuk wali-kelas...")
    wali_rows = []
    for item in wali_chunks:
        emb = embed_text(item["content"])
        wali_rows.append({
            "pdf_name": item["pdf_name"],
            "category": item["category"],
            "content": item["content"],
            "embedding": emb,
        })

    sb.table("pdf_documents").delete().eq("pdf_name", "wali-kelas").execute()
    sb.table("pdf_documents").insert(wali_rows).execute()
    print("✅ Berhasil memasukkan 3 chunk baru terstruktur untuk wali-kelas.")

    print("\n🎉 Re-indexing selesai 100%! Semua dokumen siap diuji.")

if __name__ == "__main__":
    run_reindex()

