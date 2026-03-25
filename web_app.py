from flask import Flask, render_template, request, jsonify
import json
import os
import re
import subprocess

# 定義基礎目錄為腳本所在位置 (D:\YiHsiang\CODE\dictionary)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))

# 資料庫路徑
VOCAB_FILE = os.path.join(BASE_DIR, "dictionary.json")
PHRASE_FILE = os.path.join(BASE_DIR, "phrases.json")

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
    """儲存資料到 JSON 並自動推送到 GitHub"""
    try:
        # 1. 儲存本地檔案
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        
        # 2. 執行 Git 指令同步到 GitHub
        filename = os.path.basename(file_path)
        subprocess.run(["git", "add", filename], check=True, cwd=BASE_DIR)
        subprocess.run(["git", "commit", "-m", f"Auto-update {filename} data"], check=True, cwd=BASE_DIR)
        
        # 使用 subprocess.PIPE 來捕捉錯誤，避免因為沒權限而卡死
        result = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True, cwd=BASE_DIR)
        
        if result.returncode == 0:
            print(f"{filename} 同步成功！")
            return True
        else:
            print(f"{filename} 同步失敗: {result.stderr}")
            return False
    except Exception as e:
        print(f"程式執行異常: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

# --- Vocabulary API ---
@app.route('/api/words', methods=['GET'])
def get_words():
    words = load_data(VOCAB_FILE)
    words.sort(key=lambda x: x['word'].lower())
    return jsonify(words)

@app.route('/api/words', methods=['POST'])
def add_word():
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
                delimiters = r'[;；,，/]'
                existing_parts = set(p.strip() for p in re.split(delimiters, d['meaning']) if p.strip())
                new_parts = set(p.strip() for p in re.split(delimiters, meaning) if p.strip())
                if new_parts.issubset(existing_parts):
                    return jsonify({"status": "exists", "message": f"字典中已存在：'{word}'"}), 200
        existing['definitions'].append(new_defn)
    else:
        words.append({"word": word, "definitions": [new_defn]})
        
    save_and_sync(words, VOCAB_FILE)
    return jsonify({"success": True})

@app.route('/api/words', methods=['DELETE'])
def delete_word():
    word_to_delete = request.args.get('word', '').strip()
    words = load_data(VOCAB_FILE)
    new_words = [w for w in words if w['word'].lower() != word_to_delete.lower()]
    if len(new_words) < len(words):
        save_and_sync(new_words, VOCAB_FILE)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/words/batch', methods=['DELETE'])
def delete_words_batch():
    data = request.get_json(silent=True)
    words_to_delete = {w.lower() for w in data.get('words', [])}
    words = load_data(VOCAB_FILE)
    new_words = [w for w in words if w['word'].lower() not in words_to_delete]
    save_and_sync(new_words, VOCAB_FILE)
    return jsonify({"success": True})

@app.route('/api/words/update', methods=['PUT'])
def update_word():
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
    phrase_to_delete = request.args.get('phrase', '').strip()
    phrases = load_data(PHRASE_FILE)
    new_phrases = [p for p in phrases if p['phrase'].lower() != phrase_to_delete.lower()]
    if len(new_phrases) < len(phrases):
        save_and_sync(new_phrases, PHRASE_FILE)
        return jsonify({"success": True})
    return jsonify({"error": "Not found"}), 404

@app.route('/api/phrases/batch', methods=['DELETE'])
def delete_phrases_batch():
    data = request.get_json(silent=True)
    phrases_to_delete = {p.lower() for p in data.get('phrases', [])}
    phrases = load_data(PHRASE_FILE)
    new_phrases = [p for p in phrases if p['phrase'].lower() not in phrases_to_delete]
    save_and_sync(new_phrases, PHRASE_FILE)
    return jsonify({"success": True})

@app.route('/api/phrases/update', methods=['PUT'])
def update_phrase():
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

if __name__ == '__main__':
    app.run(debug=True, port=5000)
