import csv

with open('data_MD_update/topic_list.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['Status'] in ('Pending', 'InProgress'):
            print(f"{row['TopicName']} : {row['Status']}")
