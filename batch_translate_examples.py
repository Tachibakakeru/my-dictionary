import json
import requests
import time
import os
import re

VOCAB_FILE = "dictionary.json"

def translate_to_chinese(text):
    if not text: return ""
    try:
        url = f"https://api.mymemory.translated.net/get?q={requests.utils.quote(text)}&langpair=en|zh-TW"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            return res.json().get('responseData', {}).get('translatedText', "")
    except:
        pass
    return ""

def batch_translate():
    if not os.path.exists(VOCAB_FILE):
        print("找不到 dictionary.json")
        return

    with open(VOCAB_FILE, 'r', encoding='utf-8') as f:
        words = json.load(f)

    updated_count = 0
    total_words = len(words)
    
    print(f"開始幫舊例句補上中文翻譯...")

    for i, word_item in enumerate(words):
        changed = False
        for defn in word_item['definitions']:
            meaning = defn['meaning']
            # 如果有例句但沒有翻譯標籤
            if "[Example]" in meaning and "[Translation]" not in meaning:
                # 提取例句內容
                parts = meaning.split("[Example]")
                example_text = parts[1].strip()
                
                print(f"[{i+1}/{total_words}] 正在翻譯 '{word_item['word']}' 的例句...")
                translation = translate_to_chinese(example_text)
                
                if translation:
                    defn['meaning'] += f"\n[Translation] {translation}"
                    updated_count += 1
                    changed = True
                    # 稍微延遲避免 API 封鎖
                    time.sleep(0.3)
        
        if changed and (i + 1) % 10 == 0:
            with open(VOCAB_FILE, 'w', encoding='utf-8') as f:
                json.dump(words, f, ensure_ascii=False, indent=4)

    with open(VOCAB_FILE, 'w', encoding='utf-8') as f:
        json.dump(words, f, ensure_ascii=False, indent=4)
    
    print(f"\n處理完成！共幫 {updated_count} 個例句補上了中文翻譯。")

if __name__ == "__main__":
    batch_translate()
