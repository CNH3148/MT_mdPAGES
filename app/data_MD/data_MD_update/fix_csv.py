"""Fix CSV notes and reset target topic"""
import csv

path = "C:/Users/star0/Desktop/data_MD/data_MD_update/topic_list.csv"
rows = []
with open(path, "r", encoding="utf-8") as f:
    reader = csv.reader(f)
    header = next(reader)
    rows.append(header)
    for row in reader:
        # If the row got split across lines due to newlines in the Note field,
        # the python csv module handles it correctly if it was quoted properly,
        # but just in case, let's fix the Note column if it's there.
        if len(row) > 9:
            # Replace newlines in Note with spaces
            row[9] = row[9].replace('\n', ' ').replace('\r', '')
            
            # Reset "微生物檢驗技術：染色與鏡檢"
            if '染色與鏡檢' in row[2]:
                print(f"Found target topic: {row[2]}, changing status from {row[8]} to Pending")
                row[8] = 'Pending'
                row[9] = ''
        rows.append(row)

with open(path, "w", encoding="utf-8", newline='') as f:
    writer = csv.writer(f)
    writer.writerows(rows)
print("CSV fixed.")
