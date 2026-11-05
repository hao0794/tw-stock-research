import os
from fugle_marketdata import RestClient

client = RestClient(api_key=os.environ["FUGLE_API_KEY"])
print(client.stock.intraday.quote(symbol="2330"))
