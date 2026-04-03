import asyncio
import niquests
from datetime import datetime
import os
import time
import json
from bs4 import BeautifulSoup
import sqlite3

# Absolute path to current directory
path = os.path.dirname(__file__)

# Function: Helper to remove any None values from dict (borrowed from: https://stackoverflow.com/a/44528129)
def clean_dict(raw_dict):
    return { k: ('' if v is None else v) for k, v in raw_dict.items() }

# Function: Extract Links for a single instance
async def extractLinks(instance, snapshot, client, semaphore):
    async with semaphore:
        links = []
        try:
            # Construct URL
            links_url = "https://" + instance + "/api/v1/trends/links"

            for i in range(0, 5):
                # Set request parameters
                params = {
                    'limit': 20,
                    'offset': i * 20
                }

                response = await client.get(url=links_url, params=params, timeout=10)
                response.raise_for_status()
                links = links + response.json()

                # Sleep for 100ms so we're not bombarding the server
                await asyncio.sleep(0.1)

            results = []
            # Loop through links
            for index, link in enumerate(links, start=1):
                linkMeta = {
                    'link': link['url'],
                    'rank': index,
                    'uses_1d': int(link['history'][0]['uses']),
                    'uses_total': sum(int(activity['uses']) for activity in link['history']),
                    'instance': instance,
                    'snapshot': snapshot
                }
                results.append(clean_dict(linkMeta))

            print("INSTANCE COMPLETE:", instance)
            return results

        except Exception as e:
            print(f"ERROR [{instance}]:", e)
            return []

async def main():
    # Setup DB connection
    con = sqlite3.connect(os.path.join(path, "feditrends.db"))
    con.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cur = con.cursor()

    # Snapshot timestamp
    snapshot = int(time.time())

    # Instance list
    with open(os.path.join(path, "servers.txt"), "r") as f:
        instances = [line.strip() for line in f if line.strip()]

    print("SNAPSHOT START:", snapshot)

    semaphore = asyncio.Semaphore(10)

    async with niquests.AsyncSession(multiplexed=False, disable_http2=True, disable_http3=True) as client:
        tasks = [extractLinks(instance, snapshot, client, semaphore) for instance in instances]
        all_results = await asyncio.gather(*tasks)

    # Flatten results and insert into DB sequentially
    for instance_results in all_results:
        for clean_meta in instance_results:
            columns = ', '.join(clean_meta.keys())
            placeholders = ', '.join(['?'] * len(clean_meta))
            query = f"INSERT INTO links ({columns}) VALUES ({placeholders});"
            cur.execute(query, tuple(clean_meta.values()))

    con.commit()
    con.close()

    print("SNAPSHOT COMPLETE:", snapshot)

if __name__ == "__main__":
    asyncio.run(main())
