from googleapiclient.discovery import build

service = build('drive', 'v3')
service.close()
