
# YCPeopleScraper Security Research

## Overview
The **YCPeopleScraper** is an asynchronous Python-based tool designed to scrape Y Combinator’s public **People** page, extract basic profile information for each individual (name, title, category, image, description), and enrich it with additional data such as social media links and Hacker News (HN) profile details. The scraper uses `aiohttp` for concurrent HTTP requests, `BeautifulSoup` for HTML parsing, and optional proxy support via Geonode.

## The “YC Exploit”
During the development and testing of this scraper, a potential information-disclosure vulnerability was discovered:

1. **What Was Done**  
   - The scraper navigates YC’s public “People” directory and identifies links to individual profile pages.  
   - On each profile page, the scraper fetched available social links. This included any explicit HN profile URL (e.g., `https://news.ycombinator.com/user?id=ndessaigne`).  
   - In cases where no explicit HN URL existed, a name-based permutation search was performed:  
     - The full name was normalized (lowercased, diacritics removed).  
     - Various username permutations (e.g., `first`, `last`, `firstlast`, `lastfirst`, `first.last`, etc.) were tested against Hacker News to find valid accounts.  
   - As a result, it was possible to map many YC individuals to their private or less-obvious HN accounts—data not directly exposed on YC’s public pages.

2. **How the Exploit Worked**  
   - **Direct HN Links**: Some YC profiles contained an HN link hidden among social icons. The scraper simply detected `news.ycombinator.com/user?id=` links.  
   - **Permutation Lookup**: For people without an explicit HN link, the scraper guessed likely HN usernames by combining name tokens. Since HN usernames are often simple variants of one’s real name, this method successfully discovered numerous accounts.  
   - **Unrestricted Scraping**: No rate limiting or CAPTCHA protections were in place to deter automated requests against HN’s public user endpoint. This allowed rapid enumeration of valid HN accounts.

3. **Potential Impact**  
   - **Privacy Violation**: YC individuals who prefer to keep their HN activity separate could have their accounts linked back to their YC identity without consent.  
   - **Profiling & Phishing**: Malicious actors could gather additional personal data from HN profiles (e.g., karma, activity timestamps, “about” text) and use it for targeted phishing or social engineering.  
   - **Automated Attacks**: Without CAPTCHAs or rate limits, an attacker could enumerate a large set of valid HN accounts, facilitating brute-force or credential-stuffing attempts.

## Mitigations & Best Practices
To reduce or eliminate this information-disclosure vector:

1. **Remove or Obfuscate HN References**  
   - Do not publish direct HN profile URLs on public pages.  
   - If displaying social icons, link to a generically-branded redirect that first verifies user consent before revealing the actual HN link.

2. **Rate Limiting & CAPTCHAs on HN Endpoint**  
   - HN’s public user lookup (`/user?id=<username>`) should enforce rate limits or require simple bot-detection mechanisms to prevent automated enumeration.

3. **Robots.txt & API Restrictions**  
   - Add `Disallow: /user` (or a wider rule) in HN’s `robots.txt` to discourage web crawlers.  
   - Provide a documented, authenticated API endpoint for user lookups (e.g., OAuth-protected) instead of a fully public GET endpoint.

4. **User Education**  
   - Inform platform users that linking their public profiles could reveal other private accounts.  
   - Offer granular privacy controls to hide or delay social link publication until after user review.

## Disclosure
This research was conducted **solely** to demonstrate a proof-of-concept and to provide evidence to the Y Combinator security team. No data was stored beyond the duration necessary for testing, and no malicious intent was involved. All findings have been responsibly disclosed, and any identified issues can be remediated following the above recommendations.

> **Disclaimer:**  
> This work was performed exclusively for security research purposes. No unauthorized data collection or distribution was performed, and all collected information is publicly accessible.

