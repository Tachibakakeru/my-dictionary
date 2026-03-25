from flask import Flask, render_template, request, jsonify
import json
import os
import re
import subprocess

# 定義基礎目錄為腳本所在位置 (D:\YiHsiang\CODE\dictionary)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# 使用絕對路徑確保讀取正確的 dictionary.json
STORAGE_FILE = os.path.join(BASE_DIR, "dictionary.json")

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

def load_data():
    if not os.path.exists(STORAGE_FILE): return []
    try:
        with open(STORAGE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return []

def save_and_sync(data):
    """儲存資料到 JSON 並自動推送到 GitHub"""
    try:
        # 1. 儲存本地檔案
        with open(STORAGE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        
        # 2. 執行 Git 指令同步到 GitHub
        print(f"正在同步到 GitHub... (目錄: {BASE_DIR})")
        # 確保在正確的目錄執行
        subprocess.run(["git", "add", "dictionary.json"], check=True, cwd=BASE_DIR)
        subprocess.run(["git", "commit", "-m", "Auto-update dictionary data"], check=True, cwd=BASE_DIR)
        
        # 使用 subprocess.PIPE 來捕捉錯誤，避免因為沒權限而卡死
        result = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, cwd=BASE_DIR)
        
        if result.returncode == 0:
            print("同步成功！")
            return True
        else:
            print(f"同步失敗: {result.stderr}")
            return False
    except Exception as e:
        print(f"程式執行異常: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/words', methods=['GET'])
def get_words():
    words = load_data()
    words.sort(key=lambda x: x['word'].lower())
    return jsonify(words)

@app.route('/api/words', methods=['POST'])
def add_word():
    data = request.get_json(silent=True)
    word = data.get('word', '').strip()
    w_type = format_pos(data.get('type', '').strip())
    meaning = data.get('meaning', '').strip()
    
    words = load_data()
    existing = next((w for w in words if w['word'].lower() == word.lower()), None)
    new_defn = {"type": w_type, "meaning": meaning}
    
    if existing:
        # 檢查重複...
        for d in existing['definitions']:
            if d['type'].lower() == w_type.lower():
                import re
                delimiters = r'[;；,，/]'
                existing_parts = set(p.strip() for p in re.split(delimiters, d['meaning']) if p.strip())
                new_parts = set(p.strip() for p in re.split(delimiters, meaning) if p.strip())
                if new_parts.issubset(existing_parts):
                    return jsonify({"status": "exists", "message": f"字典中已存在：'{word}'"}), 200
        existing['definitions'].append(new_defn)
    else:
        words.append({"word": word, "definitions": [new_defn]})
        
    save_and_sync(words)
    return jsonify({"success": True})

@app.route('/api/words', methods=['DELETE'])
def delete_word():
    word_to_delete = request.args.get('word', '').strip()
    words = load_data()
    new_words = [w for w in words if w['word'].lower() != word_to_delete.lower()]
    if len(new_words) < len(words):
        save_and_sync(new_words)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/words/batch', methods=['DELETE'])
def delete_words_batch():
    data = request.get_json(silent=True)
    words_to_delete = {w.lower() for w in data.get('words', [])}
    words = load_data()
    new_words = [w for w in words if w['word'].lower() not in words_to_delete]
    save_and_sync(new_words)
    return jsonify({"success": True})

@app.route('/api/words/update', methods=['PUT'])
def update_word():
    data = request.get_json(silent=True)
    old_word = data.get('old_word', '').strip()
    words = load_data()
    word_item = next((w for w in words if w['word'].lower() == old_word.lower()), None)
    if word_item:
        word_item['word'] = data.get('new_word', '').strip()
        new_defs = data.get('definitions', [])
        for d in new_defs: d['type'] = format_pos(d['type'])
        word_item['definitions'] = new_defs
        save_and_sync(words)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/search', methods=['GET'])
def search_word():
    query = request.args.get('q', '').lower()
    words = load_data()
    results = [w for w in words if query in w['word'].lower() or any(query in d['meaning'].lower() for d in w['definitions'])]
    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
