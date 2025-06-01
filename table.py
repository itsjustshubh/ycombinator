import json
import csv
from pathlib import Path
from typing import List, Dict, Optional


def load_json(filepath: str) -> List[Dict]:
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_users_by_category(data: List[Dict], category: Optional[str]) -> List[Dict]:
    if category is None:
        return data
    return [person for person in data if person.get("category") == category]


def get_top_username(profile: Dict) -> Optional[Dict]:
    hn_profiles = profile.get("hn_profiles", [])
    if not hn_profiles:
        return None
    try:
        return max(hn_profiles, key=lambda u: int(u.get("karma", 0)))
    except ValueError:
        return None


def export_to_csv(users: List[Dict], csv_path: str) -> None:
    fieldnames = ["Name", "Title", "Category",
                  "HN Username", "Email", "Created", "Karma", "About"]
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for person in users:
            name = person.get("name")
            title = person.get("title")
            category = person.get("category")
            top_profile = get_top_username(person.get("profile", {}))
            if top_profile:
                username = top_profile.get("username")
                email = f"{username}@ycombinator.com" if username else ""
                writer.writerow({
                    "Name": name,
                    "Title": title,
                    "Category": category,
                    "HN Username": username,
                    "Email": email,
                    "Created": top_profile.get("created"),
                    "Karma": top_profile.get("karma"),
                    "About": top_profile.get("about")
                })


def main():
    json_file = "yc_people.json"
    output_csv = "yc_people_contacts.csv"

    if not Path(json_file).exists():
        print(f"File not found: {json_file}")
        return

    data = load_json(json_file)
    category = None  # Set to a category like "Founders" or leave as None to include all
    users = get_users_by_category(data, category)

    if not users:
        print("No users found.")
        return

    export_to_csv(users, output_csv)
    print(f"CSV exported to: {output_csv}")


if __name__ == '__main__':
    main()
