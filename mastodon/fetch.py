import asyncio
import os
import time
import json
import httpx
import sqlite3
import socket

# Absolute path to current directory
path = os.path.dirname(__file__)

# Function: Helper to remove any None values from dict (borrowed from: https://stackoverflow.com/a/44528129)
def clean_dict(raw_dict):
    return { k: ('' if v is None else v) for k, v in raw_dict.items() }
  
# Function: Extract Links
async def extractLinks(instance, snapshot, client, semaphore):
	links = []
	# Construct URL
	links_url = "https://" + instance + "/api/v1/trends/links"

	async with semaphore:
		print("INSTANCE START:", instance)
		try:
			for i in range(0, 5):
				# Set request parameters
				params = {
					'limit': 20,
					'offset': i * 20
				}

				response = await client.get(url=links_url, params=params, timeout=10)
				response.raise_for_status()
				new_links = response.json()
				links = links + new_links

				# Sleep for 100ms so we're not bombarding the server
				await asyncio.sleep(0.1)

			print("INSTANCE COMPLETE:", instance)
			return instance, links

		except Exception as e:
			print(f"ERROR [{instance}]:", e)
			return instance, []

async def main():
	# Setup DB connection
	con = sqlite3.connect(os.path.join(path, "feditrends.db"))
	con.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
	cur = con.cursor()

	# Snapshot timetamp
	snapshot = int(time.time())

	# Instance list
	with open(os.path.join(path, "servers.txt"), "r") as f:
		instances = [line.strip() for line in f if line.strip()]

	print("SNAPSHOT START:", snapshot)

	semaphore = asyncio.Semaphore(10)

	# Use a custom transport to force IPv4 if needed
	# httpx doesn't have an easy way to force IPv4 globally like requests/urllib3 hack
	# but we can try to use a transport with a custom limits or just let it be.
	# If IPv6 is a problem, usually it's better to handle it at the OS level or
	# use a custom resolver.

	async with httpx.AsyncClient(headers={'Connection': 'close'}, follow_redirects=True) as client:
		tasks = [extractLinks(instance, snapshot, client, semaphore) for instance in instances]
		results = await asyncio.gather(*tasks)

	# Loop through results and write to DB
	for instance, links in results:
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

			clean_meta = clean_dict(linkMeta)
			columns = ', '.join(clean_meta.keys())
			placeholders = ', '.join(['?'] * len(clean_meta))
			query = f"INSERT INTO links ({columns}) VALUES ({placeholders});"
			cur.execute(query, tuple(clean_meta.values()))

		con.commit()

	print("SNAPSHOT COMPLETE:", snapshot)
	con.close()

if __name__ == "__main__":
	asyncio.run(main())
