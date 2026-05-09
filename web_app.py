from flask import Flask, render_template, request, jsonify
import json
import os
import re
import subprocess
import webbrowser
from threading import Timer

import queue
import threading
import time

# 定義基礎目錄為腳本所在位置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# 資料庫路徑
VOCAB_FILE = os.path.join(BASE_DIR, "dictionary.json")
PHRASE_FILE = os.path.join(BASE_DIR, "phrases.json")
SLANG_FILE = os.path.join(BASE_DIR, "slangs.json")

# 安全設定: 建議部署到網路上時修改此 Token
ACCESS_TOKEN = "Kakeru0913" 

def check_auth(request):
    """檢查請求是否包含正確的 Token"""
    token = request.headers.get('X-Access-Token') or request.args.get('token')
    return token == ACCESS_TOKEN

# 同步任務佇列
sync_queue = queue.Queue()

def sync_worker():
    """背景同步執行緒，處理 Git 推送任務"""
    last_sync_time = 0
    pending_files = set()
    
    while True:
        try:
            # 從佇列中取得任務
            file_path = sync_queue.get()
            if file_path is None: break # 結束訊號
            
            pending_files.add(file_path)
            
            # 等待一段時間，合併短時間內的多個更動 (Debounce)
            # 如果佇列還有東西，就先不處理，繼續收集
            if not sync_queue.empty():
                sync_queue.task_done()
                continue
                
            # 延遲一點點時間再執行，確保連續操作被合併
            time.sleep(2)
            
            files_to_sync = list(pending_files)
            pending_files.clear()
            
            for f_path in files_to_sync:
                filename = os.path.basename(f_path)
                try:
                    # Windows 下隱藏控制台視窗的設定
                    startupinfo = None
                    if os.name == 'nt':
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTFLAGS_SWHIDE
                    
                    subprocess.run(["git", "add", filename], check=True, cwd=BASE_DIR, startupinfo=startupinfo)
                    subprocess.run(["git", "commit", "-m", f"Auto-update {filename}"], check=True, cwd=BASE_DIR, startupinfo=startupinfo)
                    subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, cwd=BASE_DIR, startupinfo=startupinfo)
                    print(f"背景同步完成: {filename}")
                except Exception as e:
                    print(f"同步過程發生錯誤 ({filename}): {e}")
            
            sync_queue.task_done()
        except Exception as e:
            print(f"Worker 異常: {e}")
            time.sleep(1)

# 啟動背景 Worker
threading.Thread(target=sync_worker, daemon=True).start()

def format_pos(pos):
    """將詞性轉為字首大寫，並處理常見縮寫"""
    if not pos: return "Unknown"
    pos = pos.strip().lower()
    mapping = {
        "n": "Noun", "n.": "Noun", "noun": "Noun",
        "v": "Verb", "v.": "Verb", "verb": "Verb",
        "adj": "Adjective", "adj.": "Adjective", "adjective": "Adjective",
        "adv": "Adverb", "adv.": "Adverb", "adverb": "Adverb",
        "prep": "Preposition", "prep.": "Preposition", "preposition": "Preposition",
        "conj": "Conjunction", "conj.": "Conjunction", "conjunction": "Conjunction",
        "pron": "Pronoun", "pron.": "Pronoun", "pronoun": "Pronoun",
        "int": "Interjection", "int.": "Interjection", "interjection": "Interjection"
    }
    return mapping.get(pos, pos.capitalize())

def load_data(file_path):
    if not os.path.exists(file_path): return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return []

def save_and_sync(data, file_path):
    """儲存資料到 JSON 並發送同步請求到背景佇列"""
    try:
        # 1. 儲存本地檔案 (這是即時的)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        
        # 2. 將同步請求放入佇列，由背景執行緒處理
        sync_queue.put(file_path)
        return True
    except Exception as e:
        print(f"儲存檔案異常: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

import requests

def get_example_sentence(word):
    """強化版例句抓取：多重來源備援 (FreeDict -> MyMemory)"""
    # 1. 基礎清理
    clean_word = re.sub(r'\(.*\)', '', word).strip()
    clean_word = clean_word.split(' ')[0].strip()
    if not clean_word: return ""

    # 策略 A: Free Dictionary API (最精準，含詞性)
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{clean_word}"
        response = requests.get(url, timeout=4)
        if response.status_code == 200:
            data = response.json()
            for entry in data:
                for meaning in entry.get('meanings', []):
                    for definition in meaning.get('definitions', []):
                        example = definition.get('example')
                        if example: return example
    except: pass

    # 策略 B: MyMemory 翻譯資料庫 (後備來源，內容極豐富但較雜)
    # 我們搜尋這個單字的翻譯，MyMemory 通常會附帶對應的雙語例句
    try:
        url = f"https://api.mymemory.translated.net/get?q={requests.utils.quote(clean_word)}&langpair=en|zh-TW"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            matches = res.json().get('matches', [])
            for match in matches:
                segment = match.get('segment', "")
                # 過濾：必須包含該單字，且長度適中（避免抓到太短或太長的）
                if clean_word.lower() in segment.lower() and 15 < len(segment) < 120:
                    # 避免抓到全是符號或只有單字的
                    if " " in segment.strip():
                        return segment
    except: pass

    return ""

def translate_to_chinese(text):
    """翻譯介面"""
    if not text: return ""
    try:
        url = f"https://api.mymemory.translated.net/get?q={requests.utils.quote(text)}&langpair=en|zh-TW"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            # 優先找最精準的翻譯
            return res.json().get('responseData', {}).get('translatedText', "")
    except: pass
    return ""

@app.route('/api/fetch-example', methods=['GET'])
def fetch_example():
    word = request.args.get('word', '').strip()
    if not word: return jsonify({"example": "", "translation": ""})
    
    example = get_example_sentence(word)
    translation = translate_to_chinese(example) if example else ""
    
    return jsonify({
        "example": example,
        "translation": translation
    })

# --- Vocabulary API ---
@app.route('/api/words', methods=['GET'])
def get_words():
    words = load_data(VOCAB_FILE)
    words.sort(key=lambda x: x['word'].lower())
    return jsonify(words)

def normalize_meaning(m):
    """清理意思字串，移除頭尾符號與多餘空白，方便精準比對"""
    if not m: return ""
    # 移除頭尾常見標點符號與空白: . 。 , ， ; ； ! ！ ? ？ ( ) [ ] { }
    import re
    cleaned = re.sub(r'^[.。，,；;！!？?\s（）\(\)\[\]\{\}]+', '', m.strip())
    cleaned = re.sub(r'[.。，,；;！!？?\s（）\(\)\[\]\{\}]+$', '', cleaned)
    return cleaned.lower()

@app.route('/api/words', methods=['POST'])
def add_word():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    word = data.get('word', '').strip()
    w_type = format_pos(data.get('type', '').strip())
    meaning = data.get('meaning', '').strip()
    
    words = load_data(VOCAB_FILE)
    existing = next((w for w in words if w['word'].lower() == word.lower()), None)
    new_defn = {"type": w_type, "meaning": meaning}
    
    if existing:
        for d in existing['definitions']:
            if d['type'].lower() == w_type.lower():
                import re
                # 分割符號包含：分號、逗號、斜線、以及它們的全形版本
                delimiters = r'[;；,，/]'
                existing_parts = set(normalize_meaning(p) for p in re.split(delimiters, d['meaning']) if p.strip())
                new_parts = set(normalize_meaning(p) for p in re.split(delimiters, meaning) if p.strip())
                
                # 只要新輸入的任何一個意思，在現有的清單中已經出現過，就跳出提醒
                overlap = new_parts.intersection(existing_parts)
                if overlap:
                    duplicate_str = "、".join(list(overlap))
                    return jsonify({
                        "status": "exists", 
                        "message": f"字典中已存在相同的解釋 ({duplicate_str})：'{word} [{w_type}]'"
                    }), 200
        existing['definitions'].append(new_defn)
    else:
        words.append({"word": word, "definitions": [new_defn]})
        
    save_and_sync(words, VOCAB_FILE)
    return jsonify({"success": True})

@app.route('/api/words', methods=['DELETE'])
def delete_word():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    word_to_delete = request.args.get('word', '').strip()
    words = load_data(VOCAB_FILE)
    new_words = [w for w in words if w['word'].lower() != word_to_delete.lower()]
    if len(new_words) < len(words):
        save_and_sync(new_words, VOCAB_FILE)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/words/batch', methods=['DELETE'])
def delete_words_batch():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    words_to_delete = {w.lower() for w in data.get('words', [])}
    words = load_data(VOCAB_FILE)
    new_words = [w for w in words if w['word'].lower() not in words_to_delete]
    save_and_sync(new_words, VOCAB_FILE)
    return jsonify({"success": True})

@app.route('/api/words/update', methods=['PUT'])
def update_word():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    old_word = data.get('old_word', '').strip()
    words = load_data(VOCAB_FILE)
    word_item = next((w for w in words if w['word'].lower() == old_word.lower()), None)
    if word_item:
        word_item['word'] = data.get('new_word', '').strip()
        new_defs = data.get('definitions', [])
        for d in new_defs: d['type'] = format_pos(d['type'])
        word_item['definitions'] = new_defs
        save_and_sync(words, VOCAB_FILE)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/search', methods=['GET'])
def search_word():
    query = request.args.get('q', '').lower()
    words = load_data(VOCAB_FILE)
    results = [w for w in words if query in w['word'].lower() or any(query in d['meaning'].lower() for d in w['definitions'])]
    return jsonify(results)

# --- Phrases API ---
@app.route('/api/phrases', methods=['GET'])
def get_phrases():
    phrases = load_data(PHRASE_FILE)
    phrases.sort(key=lambda x: x['phrase'].lower())
    return jsonify(phrases)

@app.route('/api/phrases', methods=['POST'])
def add_phrase():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    phrase = data.get('phrase', '').strip()
    meaning = data.get('meaning', '').strip()
    
    phrases = load_data(PHRASE_FILE)
    existing = next((p for p in phrases if p['phrase'].lower() == phrase.lower()), None)
    
    if existing:
        return jsonify({"status": "exists", "message": f"片語庫中已存在：'{phrase}'"}), 200
    
    phrases.append({"phrase": phrase, "meaning": meaning})
    save_and_sync(phrases, PHRASE_FILE)
    return jsonify({"success": True})

@app.route('/api/phrases', methods=['DELETE'])
def delete_phrase():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    phrase_to_delete = request.args.get('phrase', '').strip()
    phrases = load_data(PHRASE_FILE)
    new_phrases = [p for p in phrases if p['phrase'].lower() != phrase_to_delete.lower()]
    if len(new_phrases) < len(phrases):
        save_and_sync(new_phrases, PHRASE_FILE)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/phrases/batch', methods=['DELETE'])
def delete_phrases_batch():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    phrases_to_delete = {p.lower() for p in data.get('phrases', [])}
    phrases = load_data(PHRASE_FILE)
    new_phrases = [p for p in phrases if p['phrase'].lower() not in phrases_to_delete]
    save_and_sync(new_phrases, PHRASE_FILE)
    return jsonify({"success": True})

@app.route('/api/phrases/update', methods=['PUT'])
def update_phrase():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    old_phrase = data.get('old_phrase', '').strip()
    phrases = load_data(PHRASE_FILE)
    phrase_item = next((p for p in phrases if p['phrase'].lower() == old_phrase.lower()), None)
    if phrase_item:
        phrase_item['phrase'] = data.get('new_phrase', '').strip()
        phrase_item['meaning'] = data.get('meaning', '').strip()
        save_and_sync(phrases, PHRASE_FILE)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/phrases/search', methods=['GET'])
def search_phrases():
    query = request.args.get('q', '').lower()
    phrases = load_data(PHRASE_FILE)
    results = [p for p in phrases if query in p['phrase'].lower() or query in p['meaning'].lower()]
    return jsonify(results)

# --- Slangs API ---
@app.route('/api/slangs', methods=['GET'])
def get_slangs():
    slangs = load_data(SLANG_FILE)
    slangs.sort(key=lambda x: x['slang'].lower())
    return jsonify(slangs)

@app.route('/api/slangs', methods=['POST'])
def add_slang():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    slang = data.get('slang', '').strip()
    meaning = data.get('meaning', '').strip()
    
    slangs = load_data(SLANG_FILE)
    existing = next((s for s in slangs if s['slang'].lower() == slang.lower()), None)
    
    if existing:
        return jsonify({"status": "exists", "message": f"Slang 庫中已存在：'{slang}'"}), 200
    
    slangs.append({"slang": slang, "meaning": meaning})
    save_and_sync(slangs, SLANG_FILE)
    return jsonify({"success": True})

@app.route('/api/slangs', methods=['DELETE'])
def delete_slang():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    slang_to_delete = request.args.get('slang', '').strip()
    slangs = load_data(SLANG_FILE)
    new_slangs = [s for s in slangs if s['slang'].lower() != slang_to_delete.lower()]
    if len(new_slangs) < len(slangs):
        save_and_sync(new_slangs, SLANG_FILE)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/slangs/batch', methods=['DELETE'])
def delete_slangs_batch():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    slangs_to_delete = {s.lower() for s in data.get('slangs', [])}
    slangs = load_data(SLANG_FILE)
    new_slangs = [s for s in slangs if s['slang'].lower() not in slangs_to_delete]
    save_and_sync(new_slangs, SLANG_FILE)
    return jsonify({"success": True})

@app.route('/api/slangs/update', methods=['PUT'])
def update_slang():
    if not check_auth(request): return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True)
    old_slang = data.get('old_slang', '').strip()
    slangs = load_data(SLANG_FILE)
    slang_item = next((s for s in slangs if s['slang'].lower() == old_slang.lower()), None)
    if slang_item:
        slang_item['slang'] = data.get('new_slang', '').strip()
        slang_item['meaning'] = data.get('meaning', '').strip()
        save_and_sync(slangs, SLANG_FILE)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/slangs/search', methods=['GET'])
def search_slangs():
    query = request.args.get('q', '').lower()
    slangs = load_data(SLANG_FILE)
    results = [s for s in slangs if query in s['slang'].lower() or query in s['meaning'].lower()]
    return jsonify(results)

def open_browser():
    # 在伺服器環境中不執行開啟瀏覽器
    pass

if __name__ == '__main__':
    # 本地測試時使用
    app.run(debug=True, host='0.0.0.0', port=5000)

