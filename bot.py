from dotenv import load_dotenv
import os
import requests
import boto3
import schedule
import time
from math import ceil

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = os.getenv("CHANNEL")

FLIPKART_ID = os.getenv("FLIPKART_ID")
FLIPKART_TOKEN = os.getenv("FLIPKART_TOKEN")

AWS_KEY = os.getenv("AWS_KEY")
AWS_SECRET = os.getenv("AWS_SECRET")
ASSOC_TAG = os.getenv("ASSOC_TAG")

PLACEHOLDER_IMAGE = "https://via.placeholder.com/300?text=No+Image"
POSTED_FILE = "posted_deals.txt"

HEAVY_DISCOUNT_START = 70
HEAVY_DISCOUNT_END = 90
MIN_DISCOUNT = 20
MIN_TOP_DEALS = 3
PRIORITY_CATEGORIES = ["Electronics", "Fashion", "Home", "Kitchen & Appliances"]
MAX_CAPTION_ITEMS = 5

FLIPKART_API = "https://affiliate-api.flipkart.net/affiliate/offers/v1/dotd/json"
flipkart_headers = {
    "Fk-Affiliate-Id": FLIPKART_ID,
    "Fk-Affiliate-Token": FLIPKART_TOKEN
}

amazon_client = boto3.client(
    "advertising",
    aws_access_key_id=AWS_KEY,
    aws_secret_access_key=AWS_SECRET,
    region_name="us-east-1"
)

def load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, "r") as f:
        return set(line.strip() for line in f.readlines())

def save_posted(urls):
    with open(POSTED_FILE, "a") as f:
        for url in urls:
            f.write(url + "\n")

def fetch_flipkart_deals():
    try:
        r = requests.get(FLIPKART_API, headers=flipkart_headers)
        if r.status_code == 200:
            deals = r.json().get("dotdList", [])
            results = []
            for deal in deals:
                try:
                    mrp = float(deal.get("mrp", 0))
                    sp = float(deal.get("sellingPrice", 0))
                    discount = round(((mrp - sp) / mrp) * 100, 2) if mrp > 0 else 0
                except:
                    discount = 0
                image_url = deal.get("imageUrls", [{}])[0].get("url") or PLACEHOLDER_IMAGE
                category = deal.get("category", "Other")
                results.append({
                    "title": deal.get("title", "No title"),
                    "url": deal.get("url", ""),
                    "image": image_url,
                    "discount": discount,
                    "category": category
                })
            return results
        else:
            print("Flipkart API error:", r.status_code)
            return []
    except Exception as e:
        print("Flipkart fetch error:", e)
        return []

def fetch_amazon_deals():
    try:
        resp = amazon_client.get_items(
            ItemIds=["B0C1XYZ123","B0C2XYZ456"], # sample ASINs, replace later
            PartnerTag=ASSOC_TAG,
            PartnerType="Associates"
        )
        items = resp["ItemsResult"]["Items"]
        results = []
        for item in items:
            try:
                mrp = float(item["ItemInfo"]["ListPrice"]["Amount"])
                sp = float(item["Offers"]["Listings"][0]["Price"]["Amount"])
                discount = round(((mrp - sp)/mrp)*100,2) if mrp>0 else 0
            except:
                discount=0
            image_url = item.get("Images",{}).get("Primary",{}).get("Medium",{}).get("URL") or PLACEHOLDER_IMAGE
            category = item.get("BrowseNodeInfo",{}).get("ProductGroup","Other")
            results.append({
                "title": item["ItemInfo"]["Title"]["DisplayValue"],
                "url": item["DetailPageURL"],
                "image": image_url,
                "discount": discount,
                "category": category
            })
        return results
    except Exception as e:
        print("Amazon fetch error:", e)
        return []

def prioritize_deals(deals):
    priority_deals = [d for d in deals if any(c.lower() in d["category"].lower() for c in PRIORITY_CATEGORIES)]
    other_deals = [d for d in deals if d not in priority_deals]
    return priority_deals if priority_deals else other_deals

def post_deals():
    posted_urls = load_posted()
    all_deals = fetch_flipkart_deals() + fetch_amazon_deals()
    new_deals = [d for d in all_deals if d["url"] not in posted_urls]
    if not new_deals:
        print("No new deals to post.")
        return
    prioritized_deals = prioritize_deals(new_deals)
    threshold = HEAVY_DISCOUNT_START
    selected_deals=[]
    while threshold>=MIN_DISCOUNT:
        selected_deals=[d for d in prioritized_deals if threshold<=d["discount"]<=HEAVY_DISCOUNT_END]
        if len(selected_deals)>=MIN_TOP_DEALS:
            break
        threshold-=10
    else:
        selected_deals=[d for d in prioritized_deals if d["discount"]>=MIN_DISCOUNT]
    if not selected_deals:
        selected_deals=[d for d in new_deals if d["discount"]>=MIN_DISCOUNT]
        if not selected_deals:
            print("No deals to post at all.")
            return
    selected_deals=sorted(selected_deals,key=lambda x:x["discount"],reverse=True)
    max_per_album=10
    num_albums=ceil(len(selected_deals)/max_per_album)
    for album_index in range(num_albums):
        album_deals = selected_deals[album_index*max_per_album:(album_index+1)*max_per_album]
        caption = "🔥 *Top Deals Alert!*\n\n"
        for i, deal in enumerate(album_deals[:MAX_CAPTION_ITEMS],1):
            caption+=f"🎯 *{i}. {deal['title']}*\n💸 Discount: *{deal['discount']}% OFF*\n🛒 Grab it here: [{deal['title']}]({deal['url']})\n📂 Category: {deal['category']}\n\n"
        if len(album_deals)>MAX_CAPTION_ITEMS:
            caption+=f"✨ And {len(album_deals)-MAX_CAPTION_ITEMS} more deals in this album!"
        media_group=[]
        for i, deal in enumerate(album_deals):
            if i==0:
                media_group.append({
                    "type":"photo",
                    "media":deal["image"],
                    "caption":caption,
                    "parse_mode":"Markdown"
                })
            else:
                media_group.append({"type":"photo","media":deal["image"]})
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup"
        response=requests.post(url,json={"chat_id":CHANNEL,"media":media_group})
        print(f"Posted album {album_index+1}/{num_albums}: ", response.json())
        save_posted([d["url"] for d in album_deals])

schedule.every(5).minutes.do(post_deals)
print("🤖 Smart Deals Bot started... top 5 caption, priority categories, dynamic discounts, fallback ≥20%, no repeats")
while True:
    schedule.run_pending()
    time.sleep(60)
