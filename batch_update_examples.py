import json
import requests
import time
import os

VOCAB_FILE = "dictionary.json"

def get_example_sentence(word):
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            for entry in data:
                for meaning in entry.get('meanings', []):
                    for definition in meaning.get('definitions', []):
                        example = definition.get('example')
                        if example:
                            return example
    except:
        pass
    return None

def batch_update():
    if not os.path.exists(VOCAB_FILE):
        print("找不到 dictionary.json")
        return

    with open(VOCAB_FILE, 'r', encoding='utf-8') as f:
        words = json.load(f)

    updated_count = 0
    total_words = len(words)
    
    print(f"開始處理 {total_words} 個單字...")

    for i, word_item in enumerate(words):
        word = word_item['word']
        changed = False
        
        for defn in word_item['definitions']:
            # 如果還沒有 [Example] 標籤，就嘗試抓取
            if "[Example]" not in defn['meaning']:
                print(f"[{i+1}/{total_words}] 正在抓取 '{word}' 的例句...")
                example = get_example_sentence(word)
                if example:
                    defn['meaning'] += f"\n\n[Example] {example}"
                    updated_count += 1
                    changed = True
                # 稍微延遲避免被 API 封鎖
                time.sleep(0.5)
        
        if (i + 1) % 10 == 0:
            # 每 10 個存檔一次比較安全
            with open(VOCAB_FILE, 'w', encoding='utf-8') as f:
                json.dump(words, f, ensure_ascii=False, indent=4)

    # 最後完整存檔
    with open(VOCAB_FILE, 'w', encoding='utf-8') as f:
        json.dump(words, f, ensure_ascii=False, indent=4)
    
    print(f"\n處理完成！共幫 {updated_count} 個解釋補上了例句。")

if __name__ == "__main__":
    batch_update()
