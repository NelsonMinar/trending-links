from liquid import Environment, FileSystemLoader
import os
from datetime import datetime
import zoneinfo

path = "mastodon"
env = Environment(loader=FileSystemLoader(os.path.join(path, "templates/")))
html_template = env.get_template("trending-links.html")

with open(os.path.join(path, "servers.txt"), "r") as f:
    instances = [line.strip() for line in f if line.strip()]

la_tz = zoneinfo.ZoneInfo("America/Los_Angeles")
timestamp = datetime.now(la_tz).strftime("%Y-%m-%d %H:%M:%S %Z")

processed_links = [
    {
        'url': 'https://example.com/test',
        'title': 'Test Link',
        'description': 'Description',
        'image': 'https://example.com/image.png',
        'share_count': 10,
        'rank': 1,
        'domain': 'EXAMPLE.COM'
    }
]

html_feed = html_template.render(
    links=processed_links,
    timestamp=timestamp,
    instances=instances
)

os.makedirs(os.path.join(path, "output"), exist_ok=True)
with open(os.path.join(path, "output/trending-links.html"), "w") as f:
    f.write(html_feed)
