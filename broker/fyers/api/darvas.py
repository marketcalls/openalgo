import os
import http.client
import json
import pandas as pd

def get_data(auth_token):

    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    """Fetch funds data from Fyers' API using the provided authentication token."""
    conn = http.client.HTTPSConnection("api-t1.fyers.in")
    headers = {
        'Authorization': f'{api_key}:{auth_token}',  # 'app_id:access_token' format expected in auth_token
    }
    conn.request("GET", "/api/v3/funds", '', headers)

    # res = conn.getresponse()
    # data = res.read()
    # funds_data = json.loads(data.decode("utf-8"))

    # print(funds_data)
    csv_file_path = r'https://docs.google.com/spreadsheets/d/e/2PACX-1vQF6jEQvUmNGEvoFr5eTfoW3HxkgYimmsLNl5CvLI-LKJ8TcRcv1CJtopkTnpvnOiP5y_LqHl-6Dmue/pub?gid=64571827&single=true&output=csv'
    data = pd.read_csv(csv_file_path)
    transformed_data = []
    for row in data.itertuples(index=False):
        transformed_trade = {
            "RANK":row[data.columns.get_loc('RANK')],
            "COMPANY":row[data.columns.get_loc('COMPANY')],
            "CODE":row[data.columns.get_loc('CODE')],
            "QTY":row[data.columns.get_loc('QTY')],
            "RATE":row[data.columns.get_loc('RATE')],
            "CMP":row[data.columns.get_loc('CMP')],
            "Profit_Loss":row[data.columns.get_loc('Profit_Loss')],
            "Profit_loss_per":row[data.columns.get_loc('Profit_loss_per')]
        }
        transformed_data.append(transformed_trade) 
    return transformed_data