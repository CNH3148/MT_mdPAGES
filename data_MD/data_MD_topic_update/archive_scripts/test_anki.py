import re
import sys

def test():
    try:
        with open(r'C:\Users\star0\Desktop\data_MD\data_MD_update\new_MD\醫學分子檢驗學與臨床鏡檢學\基因變異篩檢技術.md', 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r"```Anki\s*\r?\n(.*?)```", content, re.DOTALL)
        with open(r'C:\Users\star0\Desktop\data_MD\data_MD_update\out.txt', 'w', encoding='utf-8') as f:
            f.write(f"MATCHED: {bool(match)}\n")
            if match:
                cards = [line for line in match.group(1).splitlines() if line.strip() and ";" in line]
                f.write(f"COUNT: {len(cards)}\n")
            else:
                f.write("No match\n")
    except Exception as e:
        with open(r'C:\Users\star0\Desktop\data_MD\data_MD_update\out.txt', 'w', encoding='utf-8') as f:
            f.write(f"ERROR: {str(e)}\n")

if __name__ == '__main__':
    test()
