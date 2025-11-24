import os
import logging
import random
import time
import json
import schedule
import requests
from requests_oauthlib import OAuth1Session
from datetime import datetime, date, timedelta  # Corrected import statement
import re
from groq import Groq
import gspread
from google.oauth2.service_account import Credentials
from dateutil import parser

# ====== GOOGLE SHEETS CONFIGURATION ======
# Make sure to set this in your GitHub Secrets as SHEET_ID
SHEET_ID = "1E1P_V1LqnE9nDhVhInB8zHu_P3pd-0HZzjkZN6ud8k0"
WORKSHEET_NAME = "Twitter_Bot_Memory"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[logging.StreamHandler()] + ([logging.FileHandler('twitter_bot.log')] if os.environ.get('LOG_FILE') else [])
)

class TwitterBot:
    def __init__(self):
        self.oauth = None
        self.groq_client = None
        self.sheet = None
        self.posted_tweets = set()
        self.setup_oauth()
        self.setup_groq()
        self.setup_sheet()

    def setup_oauth(self):
        """Setup Twitter OAuth session"""
        logging.info("➡️ Setting up Twitter OAuth")
        consumer_key = os.environ.get("TWITTER_API_KEY")
        consumer_secret = os.environ.get("TWITTER_API_SECRET")
        access_token = os.environ.get("TWITTER_ACCESS_TOKEN")
        access_token_secret = os.environ.get("TWITTER_ACCESS_SECRET")

        if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
            logging.error("❌ Missing Twitter API credentials as environment variables.")
            return

        self.oauth = OAuth1Session(
            consumer_key,
            client_secret=consumer_secret,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret,
        )

    def setup_groq(self):
        """Setup Groq client"""
        groq_api_key = os.environ.get("GROQ_API_KEY")
        if not groq_api_key:
            logging.error("❌ Groq API key not found in environment (GROQ_API_KEY).")
            return
        try:
            self.groq_client = Groq(api_key=groq_api_key)
            logging.info("✅ Groq client initialized successfully.")
        except Exception as e:
            logging.error(f"❌ Failed to initialize Groq client: {e}")

    def setup_sheet(self):
        """Setup Google Sheets connection."""
        try:
            google_creds_json = os.getenv("GOOGLE_CREDS_JSON")
            if not google_creds_json or not SHEET_ID:
                logging.error("❌ Missing Google Sheets credentials or sheet ID.")
                return

            creds_dict = json.loads(google_creds_json)
            creds = Credentials.from_service_account_info(
                creds_dict,
                scopes=[
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive",
                ],
            )
            client = gspread.authorize(creds)
            self.sheet = client.open_by_key(SHEET_ID).worksheet(WORKSHEET_NAME)
            logging.info("✅ Google Sheet connected successfully.")
        except Exception as e:
            logging.error(f"❌ Failed to connect to Google Sheet: {e}")

    def mark_posted(self, topic, tweet_content, tweet_id=None):
        """Append a log row: [YYYY-MM-DD, Topic, TweetContent, TweetID]"""
        if not self.sheet:
            return
        # This line is now correct, using date.today() from the datetime module
        today = date.today().isoformat()
        try:
            self.sheet.append_row([today, topic, tweet_content, tweet_id or ""])
            logging.info("📝 Post logged to Google Sheet.")
        except Exception as e:
            logging.error(f"❌ Error logging post to Google Sheet: {e}")

    def already_posted_topic(self, topic):
        """Check if the same topic has been posted within the last 2 days."""
        if not self.sheet:
            return False
        
        try:
            rows = self.sheet.get_all_values()[1:]  # skip header
            # This line is now correct, using date.today() from the datetime module
            today = date.today()
            # This line is now correct, using timedelta from the datetime module
            two_days_ago = today - timedelta(days=4)
            
            for row in rows:
                if len(row) < 2:
                    continue
                try:
                    post_date = parser.parse(row[0]).date()
                except Exception:
                    continue
                
                posted_topic = row[1]
                if post_date >= two_days_ago and posted_topic == topic:
                    return True
            return False
        except Exception as e:
            logging.error(f"❌ Error checking for posted topics: {e}")
            return False

    def clean_tweet_text(self, text):
        """Clean and format tweet text"""
        text = re.sub(
            r'^(Here\'s|Here is|Tweet:|Thought:|Here\'s a thought:|Quick thought:|Check out this insight:|'
            r'Here is your tweet:|Here\'s a tweet for you:|Insight:|Note:|Observation:|Quick tip:|'
            r'Pro tip:|Reminder:|Hot take:|Real talk:)',
            '',
            text,
            flags=re.IGNORECASE
        ).strip()
        text = re.sub(r'\s+', ' ', text)
        text = text.strip('"\' \n')

        if '#' not in text and random.random() < 0.3:
            hashtags = ['#DataScience', '#Analytics', '#DemandForecasting',
                        '#FleetOptimization', '#BusinessIntelligence', '#RetailAnalytics', '#InventoryManagement', '#SupplyChain', '#DataAnalytics']
            text += f" {random.choice(hashtags)}"

        if len(text) > 280:
            text = text[:277] + "..."
            last_space = text.rfind(' ')
            if last_space > 200:
                text = text[:last_space] + "..."

        return text

    def generate_tweet_with_groq(self, topic):
        """Generate tweet using Groq Python SDK"""
        if not self.groq_client:
            logging.error("❌ Groq client not initialized.")
            return None

        tweet_styles_str = os.environ.get('TWEET_STYLES')
        tweet_styles = json.loads(tweet_styles_str) if tweet_styles_str else [
            "Here's a quick insight about {topic} that can save a business money or time.",
            "From my experience, {topic} led to measurable improvements in operations.",
            "I’ve seen firsthand how {topic} can reduce costs or improve efficiency.",
            "In one project, focusing on {topic} helped achieve tangible results.",
            "Managing {topic} taught me a simple yet powerful lesson.",
            "While analyzing {topic}, I noticed a key pattern that made a real difference.",
            "Through practical experience, optimizing {topic} often results in significant gains.",
            "One insight from working with {topic}: small adjustments can have big impact.",
            "I found that careful attention to {topic} can save time and money.",
            "Real-world experience shows that {topic} directly affects performance and outcomes.",
            "During past projects, improving {topic} led to measurable success."
            "How data on {topic} helps companies make smarter decisions."
        ]

        selected_style = random.choice(tweet_styles).format(topic=topic)

        prompt = (
            f"Write a concise Twitter post about {topic}. {selected_style} "
            f"Requirements: Under 280 characters, business-focused, practical, and impactful. "
            f"Keep it authentic and experience-driven. Don't include hashtags unless specifically relevant. Just return the tweet text, nothing else."
        )

        logging.info(f"🧠 Generating tweet for topic: {topic} using Groq client.")

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                       "content": """You are a business-focused data analyst who writes concise, human-like Twitter posts.
Write tweets as if they are drawn from real experience, include outcomes, insights, or lessons learned.
Focus on practical business impact in areas like retail, inventory, transport, forecasting, sales, and operations.
Avoid generic advice or beginner tutorials. Avoid teaching. Avoid technical lectures.
Return only the tweet content, no hashtags, no explanations."""
},
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_completion_tokens=200,
                temperature=0.7,
                top_p=0.9
            )

            raw_tweet = response.choices[0].message.content.strip()
            tweet = self.clean_tweet_text(raw_tweet)

            if tweet in self.posted_tweets:
                logging.warning("⚠️ Duplicate tweet detected, regenerating...")
                return self.generate_fallback_tweet(topic)

            if 10 < len(tweet) <= 280:
                logging.info(f"✅ Generated tweet ({len(tweet)} chars): {tweet}")
                return tweet
            else:
                logging.warning(f"⚠️ Tweet length issue ({len(tweet)} chars). Using fallback.")
                return self.generate_fallback_tweet(topic)

        except Exception as e:
            logging.error(f"❌ Groq tweet generation failed: {e}")
            return self.generate_fallback_tweet(topic)

    def generate_fallback_tweet(self, topic):
        """Generate a simple fallback tweet when AI generation fails"""
        fallback_templates = [
            f"{topic} can reveal operational inefficiencies faster than most teams expect.",
            f"Many businesses overlook {topic}, yet it directly impacts cost, performance, and decision quality.",
            f"Improving {topic} often leads to clearer insights and better resource allocation.",
            f"Strong {topic} practices give companies a measurable advantage in planning and execution.",
            f"When {topic} is optimized, teams make faster, more confident decisions.",
            f"{topic} is one of the simplest ways to identify patterns that drive revenue or reduce waste.",
            f"Companies underestimate how much {topic} can improve forecasting and day-to-day operations."
        ]

        tweet = random.choice(fallback_templates)
        tweet = self.clean_tweet_text(tweet)
        logging.info(f"🔄 Using fallback tweet: {tweet}")
        return tweet

    def post_tweet(self, tweet_text):
        """Post tweet to Twitter and return the tweet ID"""
        if not self.oauth or not tweet_text:
            logging.error("❌ Cannot post tweet. Missing OAuth or tweet text.")
            return None

        payload = {"text": tweet_text}

        try:
            response = self.oauth.post("https://api.twitter.com/2/tweets", json=payload, timeout=30)

            if response.status_code == 201:
                tweet_id = response.json()['data']['id']
                self.posted_tweets.add(tweet_text)
                logging.info(f"✅ Tweet posted successfully! ID: {tweet_id}")
                logging.info(f"📝 Content: {tweet_text}")
                return tweet_id
            else:
                logging.error(f"❌ Twitter API error: {response.status_code}")
                logging.error(f"Response: {response.text}")
                return None

        except requests.exceptions.RequestException as e:
            logging.error(f"❌ Network error posting tweet: {e}")
            return None
        except Exception as e:
            logging.error(f"❌ Unexpected error posting tweet: {e}")
            return None

    def generate_and_post(self, schedule_time):
        """Generate and post a tweet, checking for recent topics."""
        logging.info(f"➡️ Generating tweet for schedule: {schedule_time}")

        topics_str = os.environ.get('TOPICS')
        topics = json.loads(topics_str) if topics_str else [
            "Identifying slow-moving products in retail",
            "Finding silent losses in daily sales data",
            "Forecasting demand for better purchasing decisions",
            "Reducing stockout and overstock risks",
            "Using ABC inventory analysis to improve cash flow",
            "Detecting products that drain working capital",
            "Predicting customer returns and fraud patterns",
            "Reducing product expiry risks in pharmacies",
            "Finding the most profitable customer segments",
            "Analyzing why certain branches outperform others",
            "Using data to understand fuel consumption in fleet vehicles",
            "Cost-per-trip analysis for transport businesses",
            "Identifying vehicles that consume too much fuel",
            "Tracking driver behavior with operational data",
            "Predictive maintenance for vehicles",
            "Reducing logistics costs with data insights",
            "Supplier performance analytics",
            "Detecting unusual patterns in transactions",
            "Reducing operational costs with simple data checks",
            "Using KPIs to improve business performance",
            "Finding profitable product categories with data",
            "Using dashboards to reveal hidden inefficiencies",
            "Customer churn early-warning signals",
            "Sales forecasting for small businesses",
            "Improving procurement compliance with data",
            "Simple reporting automation for business teams",
            "Detecting counterfeit stockout issues",
            "Finding revenue leakages in inventory data",
            "Understanding customer buying patterns with data",
            "How small businesses can benefit from predictive analytics"
        ]

        # Use Google Sheets to pick a topic not used in the last 2 days
        selected_topic = None
        random.shuffle(topics)
        for t in topics:
            if not self.already_posted_topic(t):
                selected_topic = t
                break
        
        if not selected_topic:
            selected_topic = random.choice(topics)
            logging.warning("⚠️ All topics recently posted. Picking a random one.")

        tweet_text = self.generate_tweet_with_groq(selected_topic)

        if tweet_text:
            tweet_id = self.post_tweet(tweet_text)
            if tweet_id:
                self.mark_posted(selected_topic, tweet_text, tweet_id)
                return tweet_text
        else:
            logging.error(f"❌ Failed to generate or post tweet for {schedule_time}")
            return None

    def run_bot(self):
        """Main bot execution with scheduling"""
        logging.info("🚀 Starting Twitter bot...")

        if not self.oauth:
            logging.error("❌ Twitter authentication failed. Exiting.")
            return []

        posted_tweets = []

        if os.environ.get('POST_IMMEDIATELY', 'false').lower() == 'true':
            logging.info("🔹 Posting immediate tweet")
            tweet = self.generate_and_post("immediate")
            if tweet:
                posted_tweets.append(tweet)

        schedule_times_str = os.environ.get('SCHEDULE_TIMES', '["09:00", "14:00", "18:00"]')
        schedule_times = json.loads(schedule_times_str)

        for time_str in schedule_times:
            try:
                schedule.every().day.at(time_str).do(lambda t=time_str: self.generate_and_post(t))
                logging.info(f"⏰ Scheduled tweet for {time_str}")
            except schedule.InvalidTimeError:
                logging.error(f"❌ Invalid schedule time: {time_str}")

        duration_hours = float(os.environ.get('RUN_DURATION_HOURS', '24'))
        end_time = time.time() + (duration_hours * 60 * 60)

        logging.info(f"🕒 Bot will run for {duration_hours} hours")

        while time.time() < end_time and schedule.get_jobs():
            schedule.run_pending()
            time.sleep(60)

        logging.info("✅ Bot execution completed")
        return posted_tweets

def main():
    try:
        bot = TwitterBot()
        posted_tweets = bot.run_bot()
        logging.info(f"🎉 Session complete. Posted {len(posted_tweets)} tweets.")

        if posted_tweets:
            logging.info("📋 Posted tweets:")
            for i, tweet in enumerate(posted_tweets, 1):
                logging.info(f"{i}. {tweet}")

    except KeyboardInterrupt:
        logging.info("🛑 Bot stopped by user")
    except Exception as e:
        logging.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()
