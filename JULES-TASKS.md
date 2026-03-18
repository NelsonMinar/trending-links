This is a file Nelson maintains to keep track of tasks to give to Jules to do. Jules may edit this file itself but mostly it's Nelson's responsibility.

## Suggestions from initial review 2026-03-18

### Reliability & Robustness

- [X] Fix SQL Injection Vulnerability: In fetch.py, you construct the INSERT query by concatenating Python strings (str(tuple(linkMeta.values()))). If a URL or preview text contains a single quote ('), it will break the query and crash the script. We should use parameterized queries (e.g., cur.execute("INSERT ... VALUES (?, ?, ...)", values)) instead.
- [X] Better Error Handling: build.py uses a bare except: block when fetching previews, which swallows all errors (like KeyboardInterrupts) and makes debugging hard. Also, if a site returns a timeout, it might hang for a while.
- [X] Fix Server Duplication: Remove the duplicate sfba.social in fetch.py.

### Tuning the Algorithm

- [ ] Change the Rank Penalty: Using max(rank) (the worst rank) severely penalizes links that are popular everywhere but happen to barely scrape into the top 100 on one specific server. Changing this to avg(rank) or min(rank) (the best rank) would likely give you a much fairer score.
- [ ] Adjust the Threshold: The rule instances > 5 means a link must appear on almost half of your 13 unique servers to be published. This is quite strict and might limit how many links you discover. We could lower this to 3 or 4.

### Infrastructure & Servers

- [ ] Dynamic Server List: Instead of hardcoding the server list, you could periodically fetch the top instances from an API (like instances.social) to ensure you're always querying active, highly populated servers.
- [ ] Database Optimization: You currently delete all old data on every run. If you kept historical data, you could do your own trend analysis over time (e.g., "fastest rising links of the week"), though it would require more storage.
- [ ] Would you like me to start implementing some of these improvements? I can put together a plan to fix the bugs and adjust the ranking formula if you'd like.
