import os
import asyncio
import json
import random
import unicodedata
import urllib.parse
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, track
import aiohttp
import logging


class YCPeopleScraper:
    """
    Async Y Combinator People scraper with proxy support and concurrent requests.
    Uses environment variables GEONODE_USER/GEONODE_PASS for proxy authentication.

    Attributes:
        BASE_URL (str): Base URL for Y Combinator people page.
        PROXY_HOST (str): Host for proxy service.
        PROXY_PORTS (list): List of proxy ports to rotate through.
        url (str): URL to scrape people from.
        session (aiohttp.ClientSession): HTTP session for requests.
        html (str): Raw HTML content of the people page.
        soup (BeautifulSoup): Parsed HTML soup.
        people (list): List of extracted people dictionaries.
        username_cache (dict): Cache for HN username lookups.
        semaphore (asyncio.Semaphore): Limits concurrent requests.
        geonode_user (str): Proxy username from env.
        geonode_pass (str): Proxy password from env.
        use_proxy (bool): Whether to use proxy for requests.
    """
    BASE_URL = "https://www.ycombinator.com"
    PROXY_HOST = "proxy.geonode.io"
    PROXY_PORTS = list(range(9000, 9011))

    def __init__(self, url=None, max_concurrency=10):
        """
        Initialize the YCPeopleScraper.

        Args:
            url (str, optional): The URL to scrape. Defaults to YC people page.
            max_concurrency (int): Maximum concurrent HTTP requests.
        """
        self.url = url or f"{self.BASE_URL}/people"
        self.session = None
        self.html = None
        self.soup = None
        self.people = []
        self.username_cache = {}
        self.semaphore = asyncio.Semaphore(max_concurrency)
        # load geonode creds
        self.geonode_user = os.getenv("GEONODE_USER")
        self.geonode_pass = os.getenv("GEONODE_PASS")
        self.use_proxy = bool(self.geonode_user and self.geonode_pass)

    async def __aenter__(self):
        """
        Async context manager entry. Initializes aiohttp session.

        Returns:
            YCPeopleScraper: The initialized scraper instance.
        """
        timeout = aiohttp.ClientTimeout(total=15)
        # force_close=True makes the connector shut down without waiting for
        # a graceful SSL teardown on each connection.
        connector = aiohttp.TCPConnector(limit=100, force_close=True)
        headers = {"User-Agent": "Mozilla/5.0"}
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers=headers,
            trust_env=True
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """
        Async context manager exit. Closes aiohttp session.
        """
        # Because the connector was created with force_close=True, this close()
        # should no longer hang waiting for SSL shutdown on each socket.
        await self.session.close()

    def _get_proxy_url(self):
        """
        Build a random rotating proxy URL for Geonode.

        Returns:
            str or None: Proxy URL if credentials are set, else None.
        """
        if not (self.geonode_user and self.geonode_pass):
            return None
        port = random.choice(self.PROXY_PORTS)
        return f"http://{self.geonode_user}:{self.geonode_pass}@{self.PROXY_HOST}:{port}"

    async def fetch_html(self):
        """
        Fetch the HTML content of the people page asynchronously, using proxy if configured.
        Sets self.html with the page content.
        """
        proxy = self._get_proxy_url() if self.use_proxy else None
        async with self.semaphore:
            async with self.session.get(self.url, proxy=proxy) as resp:
                resp.raise_for_status()
                self.html = await resp.text()

    def parse_html(self):
        """
        Parse the fetched HTML content using BeautifulSoup and set self.soup.
        """
        self.soup = BeautifulSoup(self.html, 'html.parser')

    def extract_sections(self):
        """
        Extract all relevant <section> elements containing people categories.

        Returns:
            list: List of BeautifulSoup section elements.
        """
        return [sec for sec in self.soup.find_all('section')
                if sec.find('h2', class_='text-2xl')]

    def normalize(self, text):
        """
        Normalize a string to lowercase, ASCII, and remove diacritics.

        Args:
            text (str): The input string.
        Returns:
            str: Normalized string.
        """
        nf = unicodedata.normalize('NFKD', text)
        return ''.join(c for c in nf if not unicodedata.combining(c)).lower()

    async def find_hn_usernames(self, full_name):
        """
        Fetch possible Hacker News usernames for a given full name by trying various permutations.
        Uses a cache to avoid redundant lookups.

        Args:
            full_name (str): The person's full name.
        Returns:
            list: List of dicts with keys: username, created, karma, about.
        """
        if full_name in self.username_cache:
            return self.username_cache[full_name]

        norm = self.normalize(full_name)
        tokens = norm.split()
        if not tokens:
            return []

        first, last = tokens[0], tokens[-1]
        # include various username permutations
        candidates = [
            first,
            last,
            f"{first}{last}",
            f"{last}{first}",
            f"{first}.{last}",
            f"{first}_{last}",
            f"{first[0]}{last}",
            f"{first}{last[0]}",
            norm.replace(" ", "")  # full name concatenated
        ]
        details_list = []

        for candidate in candidates:
            detail = await self._fetch_hn_details(candidate)
            if detail:
                details_list.append(detail)

        # dedupe by username
        unique = []
        seen = set()
        for info in details_list:
            uname = info.get('username')
            if uname and uname not in seen:
                seen.add(uname)
                unique.append(info)

        self.username_cache[full_name] = unique
        return unique

    async def _fetch_hn_details(self, candidate, attempts=3):
        """
        Try fetching a Hacker News profile for a username candidate up to `attempts` times,
        rotating proxies if service errors occur.

        Args:
            candidate (str): Username candidate to try.
            attempts (int): Number of retry attempts.
        Returns:
            dict or None: Profile details if found, else None.
        """
        url = f"https://news.ycombinator.com/user?id={candidate}"
        for _ in range(attempts):
            proxy = self._get_proxy_url()
            try:
                async with self.session.get(url, proxy=proxy) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
            except Exception:
                continue

            if "We're having some trouble serving your request" in text:
                # service error, retry with new proxy
                continue
            if "No such user." in text:
                return None

            soup = BeautifulSoup(text, 'html.parser')
            user_tag = soup.find('a', class_='hnuser')
            username = user_tag.get_text(strip=True) if user_tag else candidate

            def get_value(label):
                lbl = soup.find(
                    'td', string=lambda t: t and t.strip().startswith(label))
                if lbl:
                    val_td = lbl.find_next_sibling('td')
                    return val_td.get_text(' ', strip=True) if val_td else None
                return None

            created = get_value('created:')
            karma = get_value('karma:')
            about_td = soup.find(
                'td', string=lambda t: t and t.strip().startswith('about:'))
            about = None
            if about_td:
                about = about_td.find_next_sibling(
                    'td').get_text(' ', strip=True)

            return {
                'username': username,
                'created': created,
                'karma': karma,
                'about': about
            }
        return None

    async def extract_people(self, limit=None):
        """
        Extract people entries from the YC people page.

        Args:
            limit (int, optional): Maximum number of people to extract.
        Returns:
            list: List of people dictionaries with basic info.
        """
        await self.fetch_html()
        self.parse_html()
        entries = []
        for sec in self.extract_sections():
            cat = sec.find('h2', class_='text-2xl').get_text(strip=True)
            ul = sec.find('ul')
            if ul:
                for ent in ul.find_all(['a', 'li'], recursive=False):
                    entries.append((ent, cat))
        if limit:
            entries = entries[:limit]

        self.people = []
        with Progress(SpinnerColumn(), TextColumn("{task.completed}/{task.total} Extracting people")) as progress:
            task = progress.add_task("", total=len(entries))
            for entry, cat in entries:
                li = entry.find('li') if entry.name == 'a' else entry
                strongs = li.find_all('strong')
                if len(strongs) < 2:
                    progress.advance(task)
                    continue
                name = strongs[0].get_text(strip=True)
                title = strongs[1].get_text(strip=True)
                img = li.find('img')
                img_url = img['src'] if img and img.get('src') else None
                if img_url and img_url.startswith('//'):
                    img_url = 'https:' + img_url
                desc_div = li.find('div', class_='prose')
                desc_txt = desc_div.get_text(
                    ' ', strip=True) if desc_div else ''
                link = None
                if entry.name == 'a' and entry.get('href'):
                    link = self.BASE_URL + entry['href']
                self.people.append({
                    'name': name,
                    'title': title,
                    'category': cat,
                    'image_url': img_url,
                    'description': desc_txt,
                    'profile_link': link,
                    'profile': {
                        'social_links': {},
                        'hn_profiles': []
                    }
                })
                progress.advance(task)
        return self.people

    async def enrich_profiles(self, limit=None):
        """
        Enrich extracted people with social links and Hacker News profiles.

        Args:
            limit (int, optional): Maximum number of people to enrich.
        Returns:
            list: List of enriched people dictionaries.
        """
        people = await self.extract_people(limit)
        tasks = [self._enrich_one(p) for p in people]
        enriched = []
        for coro in track(asyncio.as_completed(tasks), total=len(tasks), description="Enriching profiles..."):
            enriched.append(await coro)
        self.people = enriched
        return enriched

    async def _enrich_one(self, person):
        """
        Enrich a single person's dictionary with social links and HN profiles.

        Args:
            person (dict): Person dictionary to enrich.
        Returns:
            dict: Enriched person dictionary.
        """
        social_links = {}
        link = person.get('profile_link')
        if link:
            try:
                proxy = self._get_proxy_url() if self.use_proxy else None
                async with self.session.get(link, proxy=proxy) as resp:
                    if resp.status == 200:
                        soup = BeautifulSoup(await resp.text(), 'html.parser')
                        sl_div = soup.find(
                            'div', class_=lambda c: c and 'mr-10' in c)
                        if sl_div:
                            for a in sl_div.find_all('a', href=True):
                                img = a.find('img')
                                if img and img.get('alt'):
                                    pf = img['alt'].split()[0].lower()
                                    social_links[pf] = a['href']
            except Exception:
                pass

        # prioritize explicit HN link
        main_hn = None
        if 'yc' in social_links:
            parsed = urllib.parse.urlparse(social_links['yc'])
            params = urllib.parse.parse_qs(parsed.query)
            if 'id' in params:
                main_hn = params['id'][0]

        hn_profiles = []
        # fetch explicit profile first
        if main_hn:
            detail = await self._fetch_hn_details(main_hn)
            if detail:
                hn_profiles.append(detail)
        # fetch additional variants
        variants = await self.find_hn_usernames(person['name'])
        for info in variants:
            uname = info.get('username')
            if uname and uname != main_hn:
                hn_profiles.append(info)

        person['profile'].update({
            'social_links': social_links,
            'hn_profiles': hn_profiles
        })
        return person

    def export_json(self, filepath, limit=None):
        """
        Export the people data to a JSON file.

        Args:
            filepath (str): Path to output JSON file.
            limit (int, optional): Maximum number of people to export.
        Returns:
            str: The filepath written to.
        """
        data = self.people if self.people else []
        if limit:
            data = data[:limit]
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return filepath

    def pretty_print(self, limit=None):
        """
        Pretty print the people data in a table using rich.

        Args:
            limit (int, optional): Maximum number of people to print.
        """
        data = self.people or []
        if limit:
            data = data[:limit]
        console = Console()
        table = Table(title="Y Combinator People")
        table.add_column("Name", style="bold")
        table.add_column("Title")
        table.add_column("Category")
        table.add_column("HN Usernames")
        for p in data:
            hn_names = ", ".join(u.get('username', '')
                                 for u in p['profile'].get('hn_profiles', []))
            table.add_row(p['name'], p['title'], p['category'], hn_names)
        console.print(table)


async def main():
    """
    Main entry point for running the scraper, enriching profiles, pretty printing, and exporting to JSON.
    """
    async with YCPeopleScraper() as scraper:
        limit = None
        await scraper.enrich_profiles(limit=limit)
        scraper.pretty_print(limit=limit)
        out = scraper.export_json('yc_people.json', limit=limit)
        print(f"Saved enriched JSON to {out}")


if __name__ == '__main__':
    asyncio.run(main())
