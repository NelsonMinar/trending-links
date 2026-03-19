import asyncio
import httpx
from datetime import datetime
import zoneinfo
import os
import json
import sqlite3
from linkpreview import Link, LinkPreview, LinkGrabber
from liquid import Environment
from liquid import FileSystemLoader

# Absolute path to current directory
path = os.path.dirname(__file__)

async def process_link(link, client, semaphore):
	async with semaphore:
		print("BEGIN:", link['link'])

		try:
			headers = {}

			# To avoid forced login
			if "twitter.com" in link['link']:
				headers = {'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'}
			# Look like a regular browser
			else:
				headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36'}

			response = await client.get(link['link'], headers=headers, follow_redirects=True, timeout=15)
			response.raise_for_status()

			fetch_link = Link(str(response.url), response.text)
			preview = LinkPreview(fetch_link, parser="lxml")

			processed_link = {
				'url': link['link'],
				'title': preview.force_title,
				'description': preview.description,
				'image': preview.absolute_image,
				'share_count': link['shares'],
				'instance_count': link['instances'],
				'rank': link['rank'],
				'domain': preview.link.netloc.upper().replace("WWW.","")
			}

			if processed_link['title'] is not None:
				print("SUCCESS:", link['link'])
				return processed_link
			else:
				print("ERROR [PREVIEW]:", link['link'])
				return None

		except Exception as e:
			print("ERROR [LOAD]:", link['link'], "-", e)
			return None

async def main():
	# Setup DB connection
	con = sqlite3.connect(os.path.join(path, "feditrends.db"))
	con.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
	cur = con.cursor()

	# Set up the SQL query
	sql = """
		SELECT
			link,
			shares,
			instances,
			row_number() over (order by score desc) as rank
		FROM
			(SELECT
				link,
				count(distinct instance) as instances,
				max(uses_1d) as shares,
				(count(distinct instance) * max(uses_1d)) / max(rank) as score
			FROM links
			INNER JOIN (
				SELECT
					max(snapshot) as latest_snapshot
				FROM links
				) snapshots on links.snapshot = snapshots.latest_snapshot
			GROUP BY link
			HAVING instances > 5 AND score NOT NULL
			ORDER BY score DESC
			) ranking
	"""

	res = cur.execute(sql)
	links = res.fetchall()

	# Get raw link data to associate with instances for contribution stats
	raw_sql = """
		SELECT link, instance
		FROM links
		INNER JOIN (
			SELECT max(snapshot) as latest_snapshot
			FROM links
		) snapshots ON links.snapshot = snapshots.latest_snapshot
	"""
	cur.execute(raw_sql)
	raw_links = cur.fetchall()

	# Clean up old snapshots
	maxsql = """
		SELECT max(snapshot) as maxsnap
		FROM links;
	"""

	maxget = cur.execute(maxsql)
	maxsnap_row = maxget.fetchone()
	maxsnap = maxsnap_row["maxsnap"] if maxsnap_row else None

	if maxsnap is not None:
		cur.execute("DELETE FROM links WHERE snapshot != ?", (maxsnap,))
	con.commit()
	con.execute("VACUUM")

	print("Old snapshots cleaned up")

	processed_links = []
	link_urls = set()
	semaphore = asyncio.Semaphore(10)

	async with httpx.AsyncClient(headers={'Connection': 'close'}, follow_redirects=True) as client:
		tasks = [process_link(link, client, semaphore) for link in links]
		results = await asyncio.gather(*tasks)
		for res in results:
			if res is not None:
				processed_links.append(res)
				link_urls.add(res['url'])

	# Load instances and count contributions for processed links
	instance_contributions = {}
	with open(os.path.join(path, "servers.txt"), "r") as f:
		for line in f:
			instance = line.strip()
			if instance:
				instance_contributions[instance] = 0

	for raw in raw_links:
		if raw['link'] in link_urls and raw['instance'] in instance_contributions:
			instance_contributions[raw['instance']] += 1

	# Sort instances by contribution count (descending)
	sorted_instances = sorted(instance_contributions.keys(), key=lambda x: instance_contributions[x], reverse=True)

	# Liquid template config
	env = Environment(loader=FileSystemLoader(os.path.join(path, "templates/")))

	# Load templates
	json_template = env.get_template("trending-links.json")
	rss_template = env.get_template("trending-links.xml")
	html_template = env.get_template("trending-links.html")

	# Timestamp in America/Los_Angeles
	la_tz = zoneinfo.ZoneInfo("America/Los_Angeles")
	now_la = datetime.now(la_tz)
	timestamp = now_la.strftime("%Y-%m-%d %H:%M:%S %Z")

	# Render into templates
	json_feed = json_template.render(links=processed_links)
	rss_feed = rss_template.render(links=processed_links)
	html_feed = html_template.render(
		links=processed_links,
		timestamp=timestamp,
		instances=sorted_instances,
		story_count=len(processed_links)
	)

	# Create output directory if it doesn't exist
	os.makedirs(os.path.join(path, "output"), exist_ok=True)

	# Write JSON Feed
	with open(os.path.join(path, "output/trending-links.json"), "w") as json_file:
		json_file.write(json_feed)

	# Write RSS
	with open(os.path.join(path, "output/trending-links.xml"), "w") as rss_file:
		rss_file.write(rss_feed)

	# Write HTML
	with open(os.path.join(path, "output/trending-links.html"), "w") as html_file:
		html_file.write(html_feed)

if __name__ == "__main__":
	asyncio.run(main())
