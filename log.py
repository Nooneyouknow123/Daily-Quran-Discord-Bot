from datetime import datetime

def log(message):
    with open('console.txt', 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")